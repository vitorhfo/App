"""Durable, sequential Gemini review of every page in imported project PDFs."""

import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pymupdf

from ai_pdf_review import (AUTO_MODEL, AUTO_MODELS, FALLBACK_MODEL, ProviderRateLimitError,
                           UnstructuredResponseError,
                           configured_key, load_review, page_payload, request_google,
                           resolve_pdf, save_review, validate_model)
from ai_apply_dimensions import apply_review
from wire_variants import sync_ai_wire_page
from database import get_connection
from source_inventory import list_project_pdfs


_lock = threading.Lock()
_wake = threading.Event()
_worker = None


def _page_count(path):
    try:
        with pymupdf.open(path) as pdf:
            return max(1, len(pdf))
    except (pymupdf.FileDataError, ValueError, OSError):
        # Keep a visible failed job rather than silently omitting the PDF.
        return 1


def _sibling_review(conn, project_id, folder_path, relative_path, page, pdf_path, model):
    """Reuse a valid review only for another saved copy of the same source folder."""
    for row in conn.execute('SELECT id FROM projects WHERE folder_path=? AND id!=?',
                            (folder_path, project_id)):
        saved = load_review(row['id'], relative_path, page, pdf_path, model)
        if saved:
            return saved
    return None


def enqueue_pdf(project_id, relative_path, model=AUTO_MODEL, force=False):
    """Queue all pages of one PDF; valid cached pages need no new API call."""
    validate_model(model)
    conn = get_connection()
    try:
        project = conn.execute('SELECT folder_path FROM projects WHERE id=?', (project_id,)).fetchone()
        if project is None:
            raise ValueError('Projeto não encontrado')
        pdf_path = resolve_pdf(project['folder_path'] or '', relative_path)
        count = _page_count(pdf_path)
        cached_pages = []
        for page in range(1, count + 1):
            cached = None if force else load_review(project_id, relative_path, page, pdf_path, model)
            if cached is None and not force:
                cached = _sibling_review(conn, project_id, project['folder_path'],
                                         relative_path, page, pdf_path, model)
                if cached:
                    cached = save_review(project_id, relative_path, page, pdf_path,
                                         cached['result'], model)
            state = 'done' if cached else 'pending'
            if cached:
                cached_pages.append((page, cached['result']))
            conn.execute('''INSERT INTO ai_review_jobs
                (project_id,path,page,model,state,attempts,next_attempt_at,force,error)
                VALUES (?,?,?,?,?,0,0,?,NULL)
                ON CONFLICT(project_id,path,page,model) DO UPDATE SET
                    state=excluded.state, attempts=0, next_attempt_at=0,
                    force=excluded.force, error=NULL, updated_at=CURRENT_TIMESTAMP''',
                (project_id, relative_path, page, model, state, int(force)))
        conn.commit()
        for page, result in cached_pages:
            apply_review(project_id, relative_path, page, result, model)
        return count
    finally:
        conn.close()


def enqueue_project(project_id, model=AUTO_MODEL):
    """Rebuild the queue after an import, including PDFs without linked materials."""
    validate_model(model)
    conn = get_connection()
    try:
        project = conn.execute('SELECT folder_path FROM projects WHERE id=?', (project_id,)).fetchone()
        if project is None:
            raise ValueError('Projeto não encontrado')
        paths = [row['path'] for row in list_project_pdfs(project['folder_path'], [])]
        conn.execute('DELETE FROM ai_review_jobs WHERE project_id=?', (project_id,))
        conn.commit()
    finally:
        conn.close()
    pages = sum(enqueue_pdf(project_id, path, model) for path in paths)
    return {'pdfs': len(paths), 'pages': pages}


def job_status(project_id):
    conn = get_connection()
    try:
        rows = conn.execute('''SELECT path,page,model,state,attempts,next_attempt_at,error
            FROM ai_review_jobs WHERE project_id=? ORDER BY path COLLATE NOCASE,page,model''',
            (project_id,)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def reuse_completed_sibling_reviews(project_id):
    """Finish queued pages already reviewed for another copy of this source."""
    conn = get_connection()
    reused = 0
    try:
        project = conn.execute('SELECT folder_path FROM projects WHERE id=?',
                               (project_id,)).fetchone()
        if project is None:
            raise ValueError('Projeto não encontrado')
        jobs = conn.execute('''SELECT path,page,model FROM ai_review_jobs
            WHERE project_id=? AND (state IN ('pending','retry')
                OR (state='fallback' AND model=?))
            ORDER BY CASE model WHEN ? THEN 0 WHEN ? THEN 1 ELSE 2 END,path,page''',
            (project_id, AUTO_MODEL, AUTO_MODEL, FALLBACK_MODEL)).fetchall()
        for job in jobs:
            try:
                pdf_path = resolve_pdf(project['folder_path'] or '', job['path'])
            except ValueError:
                continue
            saved = _sibling_review(conn, project_id, project['folder_path'],
                                    job['path'], job['page'], pdf_path, job['model'])
            if not saved:
                continue
            save_review(project_id, job['path'], job['page'], pdf_path,
                        saved['result'], job['model'])
            apply_review(project_id, job['path'], job['page'], saved['result'], job['model'])
            sync_ai_wire_page(project_id, job['path'], job['page'])
            conn.execute('''UPDATE ai_review_jobs SET state='done',error=NULL,
                next_attempt_at=0,updated_at=CURRENT_TIMESTAMP
                WHERE project_id=? AND path=? AND page=? AND model=?
                  AND (state IN ('pending','retry')
                       OR (state='fallback' AND model=?))''',
                (project_id, job['path'], job['page'], job['model'], AUTO_MODEL))
            conn.commit()
            reused += 1
        conn.execute('''UPDATE ai_review_jobs SET state='fallback',
            error='Outra conferência automática desta página já foi concluída',
            next_attempt_at=0,updated_at=CURRENT_TIMESTAMP
            WHERE project_id=? AND model IN (?,?) AND state IN ('pending','retry')
              AND EXISTS (SELECT 1 FROM ai_review_jobs finished
                  WHERE finished.project_id=ai_review_jobs.project_id
                    AND finished.path=ai_review_jobs.path
                    AND finished.page=ai_review_jobs.page
                    AND finished.model IN (?,?) AND finished.state='done')''',
            (project_id, *AUTO_MODELS, *AUTO_MODELS))
        conn.commit()
        return reused
    finally:
        conn.close()


def pause_until(model=AUTO_MODEL):
    conn = get_connection()
    try:
        validate_model(model)
        row = conn.execute('SELECT value FROM app_meta WHERE key=?',
                           (f'ai_review_pause_until:{model}',)).fetchone()
        return float(row[0]) if row else 0
    finally:
        conn.close()


def _claim_next():
    conn = get_connection()
    try:
        now = time.time()
        rows = conn.execute('''SELECT project_id,path,page,model,attempts,force
            FROM ai_review_jobs WHERE state IN ('pending','retry') AND next_attempt_at<=?
            ORDER BY updated_at,project_id,path,page''', (now,)).fetchall()
        pauses = {row['key']: float(row['value']) for row in conn.execute(
            "SELECT key,value FROM app_meta WHERE key LIKE 'ai_review_pause_until:%'")}
        row = next((candidate for candidate in rows if
                    pauses.get(f"ai_review_pause_until:{candidate['model']}", 0) <= now), None)
        if row is None:
            return None
        job = dict(row)
        conn.execute('''UPDATE ai_review_jobs SET state='running',updated_at=CURRENT_TIMESTAMP
            WHERE project_id=? AND path=? AND page=? AND model=?''',
            (job['project_id'], job['path'], job['page'], job['model']))
        conn.commit()
        return job
    finally:
        conn.close()


def _finish(job, state, error=None, next_attempt_at=0):
    conn = get_connection()
    try:
        conn.execute('''UPDATE ai_review_jobs SET state=?,attempts=attempts+1,
            next_attempt_at=?,force=0,error=?,updated_at=CURRENT_TIMESTAMP
            WHERE project_id=? AND path=? AND page=? AND model=?''',
            (state, next_attempt_at, error, job['project_id'], job['path'],
             job['page'], job['model']))
        conn.commit()
    finally:
        conn.close()


def _pause_after_provider_error(model, daily=False):
    """A 429 or 5xx pauses only this model's queued pages."""
    conn = get_connection()
    try:
        strikes_key = f'ai_review_quota_strikes:{model}'
        pause_key = f'ai_review_pause_until:{model}'
        row = conn.execute('SELECT value FROM app_meta WHERE key=?', (strikes_key,)).fetchone()
        strikes = min(12, int(row[0]) + 1 if row else 1)
        if daily:
            pacific = datetime.now(ZoneInfo('America/Los_Angeles'))
            tomorrow = (pacific + timedelta(days=1)).date()
            until = datetime.combine(tomorrow, datetime.min.time(),
                                     tzinfo=pacific.tzinfo).timestamp() + 120
        else:
            # A prolonged 503 should not leave a recovered model asleep for hours.
            until = time.time() + min(900, 60 * 2 ** (strikes - 1))
        conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES (?,?)',
                     (strikes_key, str(strikes)))
        conn.execute('INSERT OR REPLACE INTO app_meta(key,value) VALUES (?,?)',
                     (pause_key, str(until)))
        conn.commit()
        return until
    finally:
        conn.close()


def _clear_quota_pause(model):
    conn = get_connection()
    try:
        conn.execute('DELETE FROM app_meta WHERE key IN (?,?)',
                     (f'ai_review_quota_strikes:{model}', f'ai_review_pause_until:{model}'))
        conn.commit()
    finally:
        conn.close()


def _route_daily_exhaustion(model):
    """Move all unfinished pages to the next PDF-capable model, keeping an audit row."""
    if model != AUTO_MODEL:
        return 0
    conn = get_connection()
    try:
        pages = conn.execute('''SELECT COUNT(*) FROM ai_review_jobs
            WHERE model=? AND state IN ('pending','retry')''', (model,)).fetchone()[0]
        with conn:
            conn.execute('''INSERT OR IGNORE INTO ai_review_jobs
                (project_id,path,page,model,state,attempts,next_attempt_at,force,error)
                SELECT project_id,path,page,?,'pending',0,0,force,NULL
                FROM ai_review_jobs WHERE model=? AND state IN ('pending','retry')''',
                (FALLBACK_MODEL, model))
            conn.execute('''UPDATE ai_review_jobs SET state='fallback',
                error=?,updated_at=CURRENT_TIMESTAMP
                WHERE model=? AND state IN ('pending','retry')''',
                (f'Cota diária esgotada; transferida para {FALLBACK_MODEL}', model))
        return pages
    finally:
        conn.close()


def _route_unstructured_page(job, message):
    conn = get_connection()
    try:
        with conn:
            conn.execute('''INSERT OR IGNORE INTO ai_review_jobs
                (project_id,path,page,model,state,attempts,next_attempt_at,force,error)
                VALUES (?,?,?,?,'pending',0,0,0,NULL)''',
                (job['project_id'], job['path'], job['page'], FALLBACK_MODEL))
            conn.execute('''UPDATE ai_review_jobs SET state='fallback',
                attempts=attempts+1,error=?,updated_at=CURRENT_TIMESTAMP
                WHERE project_id=? AND path=? AND page=? AND model=?''',
                (f'{message}; transferida para {FALLBACK_MODEL}',
                 job['project_id'], job['path'], job['page'], job['model']))
    finally:
        conn.close()


def process_next_job():
    """Process one queued page, preserving failures and quota retries for inspection."""
    job = _claim_next()
    if job is None:
        return False
    try:
        conn = get_connection()
        try:
            project = conn.execute('SELECT folder_path FROM projects WHERE id=?',
                                   (job['project_id'],)).fetchone()
            if project is None:
                raise ValueError('Projeto não encontrado')
            pdf_path = resolve_pdf(project['folder_path'] or '', job['path'])
        finally:
            conn.close()
        cached = (None if job['force'] else load_review(job['project_id'], job['path'],
                                                        job['page'], pdf_path, job['model']))
        if cached:
            apply_review(job['project_id'], job['path'], job['page'],
                         cached['result'], job['model'])
            sync_ai_wire_page(job['project_id'], job['path'], job['page'])
            _finish(job, 'done')
            return True
        if not job['force']:
            conn = get_connection()
            try:
                sibling = _sibling_review(conn, job['project_id'], project['folder_path'],
                                          job['path'], job['page'], pdf_path, job['model'])
            finally:
                conn.close()
            if sibling:
                save_review(job['project_id'], job['path'], job['page'], pdf_path,
                            sibling['result'], job['model'])
                apply_review(job['project_id'], job['path'], job['page'],
                             sibling['result'], job['model'])
                sync_ai_wire_page(job['project_id'], job['path'], job['page'])
                _finish(job, 'done')
                return True
        key = configured_key()
        if not key:
            _finish(job, 'retry', 'Chave Google não configurada', time.time() + 3600)
            return True
        pdf_bytes, _ = page_payload(pdf_path, job['page'])
        result = request_google(pdf_bytes, key, model=job['model'])
        save_review(job['project_id'], job['path'], job['page'], pdf_path,
                    result, job['model'])
        apply_review(job['project_id'], job['path'], job['page'], result, job['model'])
        sync_ai_wire_page(job['project_id'], job['path'], job['page'])
        _clear_quota_pause(job['model'])
        _finish(job, 'done')
    except Exception as exc:
        # Google request_google already removes credentials and response bodies.
        message = str(exc)[:400] if isinstance(exc, ValueError) else type(exc).__name__
        if isinstance(exc, UnstructuredResponseError) and job['model'] == AUTO_MODEL:
            _route_unstructured_page(job, message)
            return True
        retryable = any(marker in message for marker in ('HTTP 429', 'HTTP 500', 'HTTP 502',
                                                           'HTTP 503', 'HTTP 504', 'URLError',
                                                           'TimeoutError'))
        if retryable:
            provider_busy = any(marker in message for marker in
                                ('HTTP 429', 'HTTP 500', 'HTTP 502', 'HTTP 503', 'HTTP 504'))
            daily = isinstance(exc, ProviderRateLimitError) and exc.period == 'day'
            next_attempt = (_pause_after_provider_error(job['model'], daily) if provider_busy else
                            time.time() + min(86400, 60 * 2 ** min(job['attempts'], 11)))
            _finish(job, 'retry', message, next_attempt)
            if daily:
                _route_daily_exhaustion(job['model'])
        else:
            _finish(job, 'error', message)
    return True


def _work():
    while True:
        if process_next_job():
            continue
        conn = get_connection()
        try:
            row = conn.execute("SELECT MIN(next_attempt_at) FROM ai_review_jobs WHERE state='retry'").fetchone()
            next_retry = row[0]
        finally:
            conn.close()
        _wake.wait(60 if next_retry is None else max(1, min(60, next_retry - time.time())))
        _wake.clear()


def start_worker():
    global _worker
    if not configured_key():
        return False
    with _lock:
        if _worker is not None and _worker.is_alive():
            _wake.set()
            return True
        conn = get_connection()
        try:
            conn.execute("UPDATE ai_review_jobs SET state='pending' WHERE state='running'")
            conn.commit()
        finally:
            conn.close()
        _worker = threading.Thread(target=_work, name='ai-pdf-review', daemon=True)
        _worker.start()
        return True
