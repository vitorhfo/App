"""Move unfinished legacy automatic PDF reviews to Flash-Lite, preserving results."""

from datetime import datetime
from pathlib import Path
import sqlite3

from ai_pdf_review import AUTO_MODEL, FALLBACK_MODEL, MODEL
from config import DB_PATH


def migrate(conn):
    before = {
        'projects': conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0],
        'materials': conn.execute('SELECT COUNT(*) FROM materials').fetchone()[0],
        'finished_complex': conn.execute('SELECT COUNT(*) FROM ai_review_jobs WHERE model=? AND state=?',
                                         (MODEL, 'done')).fetchone()[0],
    }
    old = conn.execute("SELECT COUNT(*) FROM ai_review_jobs WHERE model=? AND state!='done'",
                       (MODEL,)).fetchone()[0]
    with conn:
        conn.execute('''INSERT OR IGNORE INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force,error)
            SELECT project_id,path,page,?,'pending',0,0,0,NULL FROM ai_review_jobs
            WHERE model=? AND state!='done' ''', (AUTO_MODEL, MODEL))
        conn.execute("DELETE FROM ai_review_jobs WHERE model=? AND state!='done'", (MODEL,))
        conn.execute("DELETE FROM app_meta WHERE key IN ('ai_review_pause_until','ai_review_quota_strikes')")
    after = {
        'projects': conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0],
        'materials': conn.execute('SELECT COUNT(*) FROM materials').fetchone()[0],
        'finished_complex': conn.execute('SELECT COUNT(*) FROM ai_review_jobs WHERE model=? AND state=?',
                                         (MODEL, 'done')).fetchone()[0],
    }
    if after != before:
        raise RuntimeError(f'Invariantes do orçamento mudaram: {before} -> {after}')
    return old


def recover_unstructured_errors(conn):
    """Retry only existing malformed 3.5 replies with the PDF-capable reserve."""
    before = conn.execute('''SELECT COUNT(*) FROM ai_review_jobs
        WHERE model=? AND state='error' AND error LIKE 'A IA não retornou JSON estruturado%' ''',
        (AUTO_MODEL,)).fetchone()[0]
    with conn:
        conn.execute('''INSERT OR IGNORE INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force,error)
            SELECT project_id,path,page,?,'pending',0,0,0,NULL FROM ai_review_jobs
            WHERE model=? AND state='error' AND error LIKE 'A IA não retornou JSON estruturado%' ''',
            (FALLBACK_MODEL, AUTO_MODEL))
        conn.execute('''UPDATE ai_review_jobs SET state='fallback',
            error=error || '; transferida para ' || ?,updated_at=CURRENT_TIMESTAMP
            WHERE model=? AND state='error' AND error LIKE 'A IA não retornou JSON estruturado%' ''',
            (FALLBACK_MODEL, AUTO_MODEL))
    return before


if __name__ == '__main__':
    target = Path(DB_PATH)
    backup = target.parent / 'backups' / f'before_ai_lite_{datetime.now():%Y%m%d_%H%M%S}.db'
    backup.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(target) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    with sqlite3.connect(target) as conn:
        moved = migrate(conn)
        recovered = recover_unstructured_errors(conn)
        counts = conn.execute('SELECT model,state,COUNT(*) FROM ai_review_jobs '
                              'GROUP BY model,state ORDER BY model,state').fetchall()
    print(f'Backup: {backup}')
    print(f'Páginas antigas reprogramadas: {moved}')
    print(f'Respostas sem JSON enviadas à reserva: {recovered}')
    print(f'Fila atual: {counts}')
