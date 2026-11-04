"""Automatic review covers every PDF page and survives Free-tier interruptions."""

from io import BytesIO
from pathlib import Path
import time
import unittest
import uuid
import shutil
from unittest.mock import patch

import pymupdf
from fastapi import BackgroundTasks
from reportlab.pdfgen import canvas

import ai_pdf_review
import ai_review_queue
import database
from migrate_ai_jobs_to_lite import migrate, recover_unstructured_errors
from app import import_project_folder, get_all_pdf_reviews
from config import DATA_DIR


def make_pdf(path, labels):
    buffer = BytesIO()
    drawing = canvas.Canvas(buffer)
    for label in labels:
        drawing.drawString(40, 740, label)
        drawing.showPage()
    drawing.save()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buffer.getvalue())


class AutomaticAiReviewTest(unittest.TestCase):
    def setUp(self):
        scratch = Path(DATA_DIR) / 'test_runs'
        scratch.mkdir(exist_ok=True)
        self.root = scratch / f'ai_queue_{uuid.uuid4().hex}'
        self.root.mkdir()
        self.assertTrue(self.root.resolve().is_relative_to(scratch.resolve()))
        self.addCleanup(shutil.rmtree, self.root)
        self.db_patch = patch.object(database, 'DB_PATH', str(self.root / 'quote.db'))
        self.cache_patch = patch.object(ai_pdf_review, 'REVIEW_DIR', self.root / 'reviews')
        self.db_patch.start()
        self.cache_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.cache_patch.stop)
        database.init_db()
        self.source = self.root / 'source'
        self.source.mkdir()
        make_pdf(self.source / 'PROJETO' / 'desenho.pdf', ['FOLHA 1', 'FOLHA 2', 'FOLHA 3'])
        make_pdf(self.source / 'PROJETO' / 'sem_item.pdf', ['FOLHA AVULSA'])
        conn = database.get_connection()
        self.project_id = conn.execute('INSERT INTO projects(name,folder_path) VALUES (?,?)',
                                       ('Teste multipágina', str(self.source))).lastrowid
        conn.commit()
        conn.close()

    def test_import_enqueues_every_page_and_read_only_review(self):
        background = BackgroundTasks()
        with patch('app.process_complete_project', return_value={'materials': []}), \
             patch('app.start_worker') as worker:
            result = import_project_folder(self.project_id, str(self.source), background)
            self.assertEqual(result['ai_pages_queued'], 4)
            self.assertEqual(len(background.tasks), 1)
            self.assertIs(background.tasks[0].func, worker)
        jobs = ai_review_queue.job_status(self.project_id)
        self.assertEqual([(job['path'], job['page']) for job in jobs], [
            ('PROJETO/desenho.pdf', 1), ('PROJETO/desenho.pdf', 2),
            ('PROJETO/desenho.pdf', 3), ('PROJETO/sem_item.pdf', 1)])
        self.assertTrue(all(job['state'] == 'pending' for job in jobs))
        self.assertTrue(all(job['model'] == ai_pdf_review.AUTO_MODEL for job in jobs))
        conn = database.get_connection()
        item_id = conn.execute('''INSERT INTO materials
            (project_id,description,group_name,item_type,source_page,length,quantity)
            VALUES (?,?,?,?,?,0,1)''', (self.project_id, 'Peça da folha 2', 'Chapa',
                                     'materia_prima', 'PROJETO/desenho.pdf#page=2')).lastrowid
        conn.commit()
        before = dict(conn.execute('SELECT * FROM materials WHERE id=?', (item_id,)).fetchone())
        conn.close()

        def fake_google(pdf_bytes, key, model):
            with pymupdf.open(stream=pdf_bytes, filetype='pdf') as pdf:
                title = pdf[0].get_text().strip()
            return ai_pdf_review.normalize_response({'drawing_title': title, 'items': [
                {'description': title, 'length': 250 if title == 'FOLHA 2' else 100}]})

        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, 'request_google', side_effect=fake_google) as provider:
            while ai_review_queue.process_next_job():
                pass
        self.assertEqual(provider.call_count, 4)
        self.assertTrue(all(job['state'] == 'done' for job in ai_review_queue.job_status(self.project_id)))
        batch = get_all_pdf_reviews(self.project_id, 'PROJETO/desenho.pdf')
        self.assertEqual([page['result']['review']['result']['drawing_title']
                          for page in batch['pages']], ['FOLHA 1', 'FOLHA 2', 'FOLHA 3'])
        page_two = batch['pages'][1]['result']['comparisons'][0]
        self.assertEqual(page_two['script_item_id'], item_id)
        self.assertEqual(next(field['state'] for field in page_two['fields']
                              if field['field'] == 'length'), 'ai_only')
        conn = database.get_connection()
        self.assertEqual(dict(conn.execute('SELECT * FROM materials WHERE id=?',
                                           (item_id,)).fetchone()), before)
        conn.close()
        self.assertEqual(ai_review_queue.enqueue_project(self.project_id)['pages'], 4)
        self.assertTrue(all(job['state'] == 'done' for job in ai_review_queue.job_status(self.project_id)))

    def test_detail_page_links_only_to_part_in_same_pdf(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf')
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/sem_item.pdf')
        conn = database.get_connection()
        item_id = conn.execute('''INSERT INTO materials
            (project_id,description,group_name,item_type,source_page,
             length,width,depth,thickness,quantity)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (self.project_id, 'TUBO VERTICAL FUNDO', 'Tubo Quadrado/Retangular',
             'materia_prima', 'PROJETO/desenho.pdf#page=1',
             1630, 25, 25, .9, 2)).lastrowid
        conn.execute("UPDATE ai_review_jobs SET state='done' WHERE project_id=? "
                     'AND ((path=? AND page=2) OR path=?)',
                     (self.project_id, 'PROJETO/desenho.pdf', 'PROJETO/sem_item.pdf'))
        conn.commit()
        conn.close()
        result = ai_pdf_review.normalize_response({'items': [{
            'item_number': '1', 'description': 'TUBO VERTICAL FUNDO',
            'item_type': 'materia_prima', 'material': 'TUBO QUADRADO 25X25X0,9',
            'length': 1630, 'width': 25, 'depth': 25, 'thickness': .9,
            'quantity': 1, 'quantity_scope': 'local_table'}]})
        for path, page in [('desenho.pdf', 2), ('sem_item.pdf', 1)]:
            ai_pdf_review.save_review(self.project_id, f'PROJETO/{path}', page,
                                      self.source / 'PROJETO' / path, result,
                                      ai_pdf_review.AUTO_MODEL)
        linked = get_all_pdf_reviews(self.project_id, 'PROJETO/desenho.pdf')['pages'][1]
        unrelated = get_all_pdf_reviews(self.project_id, 'PROJETO/sem_item.pdf')['pages'][0]
        self.assertEqual(linked['result']['comparisons'][0]['script_item_id'], item_id)
        self.assertIsNone(unrelated['result']['comparisons'][0]['script_item_id'])

    def test_quota_retry_does_not_skip_other_pages(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf')
        calls = 0

        def flaky_google(pdf_bytes, key, model):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ValueError('Google API recusou a consulta (HTTP 429).')
            return ai_pdf_review.normalize_response({'items': [
                {'description': 'Corte', 'length': 40}]})

        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, 'request_google', side_effect=flaky_google):
            self.assertTrue(ai_review_queue.process_next_job())
            jobs = ai_review_queue.job_status(self.project_id)
            self.assertEqual(jobs[0]['state'], 'retry')
            self.assertGreater(jobs[0]['next_attempt_at'], time.time())
            self.assertFalse(ai_review_queue.process_next_job())
            self.assertEqual(calls, 1)
            conn = database.get_connection()
            conn.execute("UPDATE app_meta SET value='0' WHERE key=?",
                         (f'ai_review_pause_until:{ai_pdf_review.AUTO_MODEL}',))
            conn.commit()
            conn.close()
            self.assertTrue(ai_review_queue.process_next_job())
            self.assertEqual(ai_review_queue.job_status(self.project_id)[1]['state'], 'done')
            conn = database.get_connection()
            conn.execute("UPDATE ai_review_jobs SET next_attempt_at=0 WHERE state='retry'")
            conn.commit()
            conn.close()
            while ai_review_queue.process_next_job():
                pass
        self.assertEqual(calls, 4)
        self.assertTrue(all(job['state'] == 'done' for job in ai_review_queue.job_status(self.project_id)))

    def test_restart_resumes_running_page_and_bad_pdf_is_visible(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf')
        conn = database.get_connection()
        conn.execute("UPDATE ai_review_jobs SET state='running' WHERE project_id=? AND page=1",
                     (self.project_id,))
        conn.commit()
        conn.close()
        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, '_work'):
            self.assertTrue(ai_review_queue.start_worker())
            ai_review_queue._worker.join(timeout=2)
        self.assertEqual(ai_review_queue.job_status(self.project_id)[0]['state'], 'pending')

        broken = self.source / 'PROJETO' / 'quebrado.pdf'
        broken.write_bytes(b'arquivo ilegivel')
        self.assertEqual(ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/quebrado.pdf'), 1)
        conn = database.get_connection()
        conn.execute("DELETE FROM ai_review_jobs WHERE project_id=? AND path!=?",
                     (self.project_id, 'PROJETO/quebrado.pdf'))
        conn.commit()
        conn.close()
        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'):
            self.assertTrue(ai_review_queue.process_next_job())
        job = ai_review_queue.job_status(self.project_id)[0]
        self.assertEqual(job['state'], 'error')
        self.assertTrue(job['error'])

    def test_provider_503_pauses_all_pending_pages(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf')
        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, 'request_google',
                          side_effect=ValueError('Google API recusou a consulta (HTTP 503).')) as provider:
            self.assertTrue(ai_review_queue.process_next_job())
            self.assertFalse(ai_review_queue.process_next_job())
        self.assertEqual(provider.call_count, 1)
        self.assertGreater(ai_review_queue.pause_until(), time.time())
        self.assertEqual([job['state'] for job in ai_review_queue.job_status(self.project_id)],
                         ['retry', 'pending', 'pending'])
        page = get_all_pdf_reviews(self.project_id, 'PROJETO/desenho.pdf', model='auto')['pages'][0]
        self.assertEqual(page['state'], 'retry')
        self.assertGreater(page['next_attempt_at'], time.time())

    def test_same_source_project_reuses_finished_page_without_google_call(self):
        second = database.get_connection()
        sibling_id = second.execute('INSERT INTO projects(name,folder_path) VALUES (?,?)',
                                    ('Segunda cópia', str(self.source))).lastrowid
        other_source = self.root / 'other_source'
        other_source.mkdir()
        make_pdf(other_source / 'PROJETO' / 'desenho.pdf', ['OUTRA FOLHA'])
        unrelated_id = second.execute('INSERT INTO projects(name,folder_path) VALUES (?,?)',
                                      ('Outra origem', str(other_source))).lastrowid
        second.commit()
        second.close()
        pdf_path = self.source / 'PROJETO' / 'desenho.pdf'
        result = ai_pdf_review.normalize_response({'items': [
            {'description': 'Corte 1', 'length': 250, 'evidence': 'cota 250 na folha'}]})
        ai_pdf_review.save_review(self.project_id, 'PROJETO/desenho.pdf', 1, pdf_path,
                                  result, ai_pdf_review.AUTO_MODEL)
        with patch.object(ai_review_queue, 'request_google') as provider:
            ai_review_queue.enqueue_pdf(sibling_id, 'PROJETO/desenho.pdf')
            self.assertEqual(ai_review_queue.job_status(sibling_id)[0]['state'], 'done')
            self.assertEqual(ai_pdf_review.load_review(sibling_id, 'PROJETO/desenho.pdf',
                             1, pdf_path, ai_pdf_review.AUTO_MODEL)['result'], result)
            ai_review_queue.enqueue_pdf(unrelated_id, 'PROJETO/desenho.pdf')
            self.assertEqual(ai_review_queue.job_status(unrelated_id)[0]['state'], 'pending')
        provider.assert_not_called()

    def test_existing_retry_reuses_sibling_and_skips_redundant_fallback(self):
        conn = database.get_connection()
        sibling_id = conn.execute('INSERT INTO projects(name,folder_path) VALUES (?,?)',
                                  ('Segunda cópia', str(self.source))).lastrowid
        conn.commit()
        conn.close()
        ai_review_queue.enqueue_pdf(sibling_id, 'PROJETO/desenho.pdf')
        ai_review_queue.enqueue_pdf(sibling_id, 'PROJETO/desenho.pdf',
                                    ai_pdf_review.FALLBACK_MODEL)
        conn = database.get_connection()
        conn.execute("UPDATE ai_review_jobs SET state='retry',error='HTTP 503',next_attempt_at=? "
                     'WHERE project_id=? AND page=1 AND model=?',
                     (time.time() + 3600, sibling_id, ai_pdf_review.AUTO_MODEL))
        conn.commit()
        conn.close()
        pdf_path = self.source / 'PROJETO' / 'desenho.pdf'
        ai_pdf_review.save_review(self.project_id, 'PROJETO/desenho.pdf', 1, pdf_path,
                                  ai_pdf_review.normalize_response({'items': [
                                      {'description': 'Corte', 'length': 250}]}),
                                  ai_pdf_review.AUTO_MODEL)
        with patch.object(ai_review_queue, 'request_google') as provider:
            self.assertEqual(ai_review_queue.reuse_completed_sibling_reviews(sibling_id), 1)
        provider.assert_not_called()
        jobs = ai_review_queue.job_status(sibling_id)
        self.assertEqual(next(job['state'] for job in jobs if job['page'] == 1 and
                              job['model'] == ai_pdf_review.AUTO_MODEL), 'done')
        self.assertEqual(next(job['state'] for job in jobs if job['page'] == 1 and
                              job['model'] == ai_pdf_review.FALLBACK_MODEL), 'fallback')
        self.assertEqual(next(job['state'] for job in jobs if job['page'] == 2 and
                              job['model'] == ai_pdf_review.AUTO_MODEL), 'pending')

    def test_fallback_page_reuses_primary_result_from_same_source(self):
        conn = database.get_connection()
        sibling_id = conn.execute('INSERT INTO projects(name,folder_path) VALUES (?,?)',
                                  ('Segunda cópia', str(self.source))).lastrowid
        conn.commit()
        conn.close()
        ai_review_queue.enqueue_pdf(sibling_id, 'PROJETO/desenho.pdf')
        ai_review_queue.enqueue_pdf(sibling_id, 'PROJETO/desenho.pdf',
                                    ai_pdf_review.FALLBACK_MODEL)
        conn = database.get_connection()
        conn.execute("UPDATE ai_review_jobs SET state='fallback' WHERE project_id=? "
                     'AND page=1 AND model=?', (sibling_id, ai_pdf_review.AUTO_MODEL))
        conn.execute("UPDATE ai_review_jobs SET state='retry',error='HTTP 503' "
                     'WHERE project_id=? AND page=1 AND model=?',
                     (sibling_id, ai_pdf_review.FALLBACK_MODEL))
        conn.commit()
        conn.close()
        pdf_path = self.source / 'PROJETO' / 'desenho.pdf'
        ai_pdf_review.save_review(self.project_id, 'PROJETO/desenho.pdf', 1, pdf_path,
                                  ai_pdf_review.normalize_response({'items': [
                                      {'description': 'Corte', 'length': 250}]}),
                                  ai_pdf_review.AUTO_MODEL)
        self.assertEqual(ai_review_queue.reuse_completed_sibling_reviews(sibling_id), 1)
        jobs = ai_review_queue.job_status(sibling_id)
        self.assertEqual(next(job['state'] for job in jobs if job['page'] == 1 and
                              job['model'] == ai_pdf_review.AUTO_MODEL), 'done')
        self.assertEqual(next(job['state'] for job in jobs if job['page'] == 1 and
                              job['model'] == ai_pdf_review.FALLBACK_MODEL), 'fallback')

    def test_http_503_is_described_as_temporary_service_failure(self):
        error = ai_pdf_review.urllib.error.HTTPError('url', 503, 'Unavailable', {}, BytesIO(b''))
        with patch.object(ai_pdf_review.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaisesRegex(ValueError, 'temporariamente indisponível') as raised:
                ai_pdf_review.request_google(b'%PDF', 'test-key')
        self.assertNotIn('chave', str(raised.exception).lower())

    def test_repeated_temporary_errors_never_pause_a_model_for_hours(self):
        for _ in range(8):
            until = ai_review_queue._pause_after_provider_error(ai_pdf_review.AUTO_MODEL)
        self.assertLessEqual(until - time.time(), 901)

    def test_exhausted_complex_model_does_not_block_automatic_pdf_model(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf',
                                    ai_pdf_review.MODEL)
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/sem_item.pdf')
        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, 'request_google',
                          side_effect=[ValueError('Google API recusou a consulta (HTTP 429).'),
                                       ai_pdf_review.normalize_response({'items': []})]) as provider:
            self.assertTrue(ai_review_queue.process_next_job())
            self.assertGreater(ai_review_queue.pause_until(ai_pdf_review.MODEL), time.time())
            self.assertEqual(ai_review_queue.pause_until(ai_pdf_review.AUTO_MODEL), 0)
            self.assertTrue(ai_review_queue.process_next_job())
        self.assertEqual([call.kwargs['model'] for call in provider.call_args_list],
                         [ai_pdf_review.MODEL, ai_pdf_review.AUTO_MODEL])
        jobs = ai_review_queue.job_status(self.project_id)
        self.assertEqual(next(job['state'] for job in jobs if job['model'] ==
                              ai_pdf_review.AUTO_MODEL), 'done')
        self.assertEqual(len([job for job in jobs if job['model'] == ai_pdf_review.MODEL]), 3)

    def test_legacy_queue_migration_keeps_completed_reviews_and_materials(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf',
                                    ai_pdf_review.MODEL)
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf',
                                    ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        try:
            conn.execute("UPDATE ai_review_jobs SET state='done' WHERE model=? AND page=1",
                         (ai_pdf_review.MODEL,))
            conn.execute("UPDATE ai_review_jobs SET state='done' WHERE model=? AND page=2",
                         (ai_pdf_review.AUTO_MODEL,))
            conn.execute('INSERT INTO materials (project_id,description,group_name,item_type) '
                         'VALUES (?,?,?,?)', (self.project_id, 'Item manual', 'Chapa',
                                            'materia_prima'))
            conn.commit()
            material = dict(conn.execute('SELECT * FROM materials WHERE description=?',
                                         ('Item manual',)).fetchone())
            self.assertEqual(migrate(conn), 2)
            self.assertEqual(migrate(conn), 0)
            self.assertEqual(dict(conn.execute('SELECT * FROM materials WHERE description=?',
                                               ('Item manual',)).fetchone()), material)
            jobs = ai_review_queue.job_status(self.project_id)
            self.assertEqual([(job['page'], job['state']) for job in jobs
                              if job['model'] == ai_pdf_review.MODEL], [(1, 'done')])
            self.assertEqual([(job['page'], job['state']) for job in jobs
                              if job['model'] == ai_pdf_review.AUTO_MODEL],
                             [(1, 'pending'), (2, 'done'), (3, 'pending')])
        finally:
            conn.close()

    def test_daily_quota_moves_all_unfinished_pages_and_auto_view_shows_model(self):
        ai_review_queue.enqueue_project(self.project_id)
        result = ai_pdf_review.normalize_response({'drawing_title': 'Reserva', 'items': []})
        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, 'request_google',
                          side_effect=[ai_pdf_review.ProviderRateLimitError('day'), result]) as provider:
            self.assertTrue(ai_review_queue.process_next_job())
            jobs = ai_review_queue.job_status(self.project_id)
            self.assertEqual(len([job for job in jobs if job['model'] ==
                                  ai_pdf_review.AUTO_MODEL and job['state'] == 'fallback']), 4)
            self.assertEqual(len([job for job in jobs if job['model'] ==
                                  ai_pdf_review.FALLBACK_MODEL and job['state'] == 'pending']), 4)
            self.assertTrue(ai_review_queue.process_next_job())
        self.assertEqual([call.kwargs['model'] for call in provider.call_args_list],
                         [ai_pdf_review.AUTO_MODEL, ai_pdf_review.FALLBACK_MODEL])
        pages = get_all_pdf_reviews(self.project_id, 'PROJETO/desenho.pdf', model='auto')['pages']
        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[0]['model'], ai_pdf_review.FALLBACK_MODEL)
        self.assertEqual(pages[0]['result']['review']['result']['drawing_title'], 'Reserva')
        self.assertEqual(pages[1]['state'], 'pending')

    def test_minute_quota_waits_without_spending_backup_daily_quota(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf')
        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, 'request_google',
                          side_effect=ai_pdf_review.ProviderRateLimitError('minute')):
            self.assertTrue(ai_review_queue.process_next_job())
        jobs = ai_review_queue.job_status(self.project_id)
        self.assertEqual({job['model'] for job in jobs}, {ai_pdf_review.AUTO_MODEL})
        self.assertEqual([job['state'] for job in jobs], ['retry', 'pending', 'pending'])
        self.assertGreater(ai_review_queue.pause_until(ai_pdf_review.AUTO_MODEL), time.time())

    def test_one_unstructured_page_uses_backup_without_moving_other_pages(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf')
        valid_review = ai_pdf_review.normalize_response({'items': []})
        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, 'request_google',
                          side_effect=[ai_pdf_review.UnstructuredResponseError('JSON inválido'),
                                       valid_review, valid_review, valid_review]):
            self.assertTrue(ai_review_queue.process_next_job())
            jobs = ai_review_queue.job_status(self.project_id)
            self.assertEqual(len([job for job in jobs if job['model'] ==
                                  ai_pdf_review.FALLBACK_MODEL]), 1)
            self.assertEqual(next(job['state'] for job in jobs if job['model'] ==
                                  ai_pdf_review.AUTO_MODEL and job['page'] == 1), 'fallback')
            while ai_review_queue.process_next_job():
                pass
        pages = get_all_pdf_reviews(self.project_id, 'PROJETO/desenho.pdf', model='auto')['pages']
        self.assertEqual(pages[0]['model'], ai_pdf_review.FALLBACK_MODEL)
        self.assertEqual(pages[0]['state'], 'done')
        self.assertEqual(pages[1]['model'], ai_pdf_review.AUTO_MODEL)
        self.assertEqual(pages[1]['state'], 'done')

    def test_saved_malformed_pages_move_to_backup_but_other_errors_stay(self):
        ai_review_queue.enqueue_pdf(self.project_id, 'PROJETO/desenho.pdf')
        conn = database.get_connection()
        try:
            conn.execute("UPDATE ai_review_jobs SET state='error',error=? WHERE page=1",
                         ('A IA não retornou JSON estruturado; nenhuma cota foi aplicada',))
            conn.execute("UPDATE ai_review_jobs SET state='error',error=? WHERE page=2",
                         ('Página PDF inválida',))
            conn.commit()
            self.assertEqual(recover_unstructured_errors(conn), 1)
            self.assertEqual(recover_unstructured_errors(conn), 0)
            jobs = ai_review_queue.job_status(self.project_id)
            self.assertEqual(next(job['state'] for job in jobs if job['page'] == 1 and
                                  job['model'] == ai_pdf_review.AUTO_MODEL), 'fallback')
            self.assertEqual(next(job['state'] for job in jobs if job['page'] == 1 and
                                  job['model'] == ai_pdf_review.FALLBACK_MODEL), 'pending')
            self.assertEqual(next(job['state'] for job in jobs if job['page'] == 2), 'error')
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
