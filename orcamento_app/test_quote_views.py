"""Independent script, AI and agreement budget views."""

import json
import unittest

import ai_pdf_review
import database
import test_ai_dimension_application as fixture
from fastapi import HTTPException
from app import get_quote_views
from quote_views import build_quote_views


class QuoteViewsTest(unittest.TestCase):
    setUp = fixture.AiDimensionApplicationTest.setUp

    def _review(self, model, *, length=299, width=234, scope='project_total'):
        pdf = self.source / 'PSAI FR. Display.pdf'
        result = ai_pdf_review.normalize_response({'items': [{
            'item_number': '1', 'description': 'PSAI FR. Display',
            'item_type': 'comprado', 'material': 'PSAI BRANCO #1mm',
            'length': length, 'width': width, 'thickness': 1,
            'quantity': 2, 'quantity_scope': scope,
            'dimension_basis': 'corte',
            'evidence': f'Tabela: 1 PSAI FR. Display QTD 2; corte {length} x {width} x 1 mm'}]})
        ai_pdf_review.save_review(self.project, pdf.name, 1, pdf, result, model)
        conn = database.get_connection()
        conn.execute('''INSERT INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force)
            VALUES (?,?,1,?,'done',1,0,0)''', (self.project, pdf.name, model))
        conn.commit()
        conn.close()

    def test_three_views_keep_ai_only_dimensions_out_of_agreed_cost(self):
        self._review(ai_pdf_review.AUTO_MODEL, scope='local_table')
        views = build_quote_views(self.project)
        self.assertEqual(len(views['script']['items']), 1)
        self.assertEqual(views['script']['items'][0]['length'], 0)
        self.assertEqual(len(views['ai']['items']), 1)
        self.assertEqual(views['ai']['items'][0]['length'], 299)
        self.assertEqual(views['ai']['items'][0]['quantity_scope'], 'local_table')
        self.assertEqual(views['agreement']['known_cost'], 0)
        self.assertEqual(views['agreement']['items'][0]['confirmed_fields'],
                         {'thickness': 1.0})

    def test_full_agreement_counts_known_script_cost_once(self):
        self._review(ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        conn.execute('''UPDATE materials SET length=299,width=234,unit_price=7,
            total_price=14 WHERE id=?''', (self.item,))
        conn.commit()
        conn.close()
        views = build_quote_views(self.project)
        agreed = views['agreement']['items']
        self.assertEqual(len(agreed), 1)
        self.assertEqual(agreed[0]['confirmed_fields']['length'], 299)
        self.assertEqual(agreed[0]['confirmed_fields']['quantity'], 2)
        self.assertEqual(views['agreement']['known_cost'], 14)
        self.assertEqual(views['script']['known_cost'], 14)

    def test_imported_ai_field_is_not_independent_script_agreement(self):
        self._review(ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        before = dict(conn.execute('SELECT * FROM materials WHERE id=?', (self.item,)).fetchone())
        after = {**before, 'length': 299, 'width': 234,
                 'observation': 'Cotas sugeridas pela IA (Gemini): length=299, width=234'}
        conn.execute('UPDATE materials SET length=299,width=234,observation=? WHERE id=?',
                     (after['observation'], self.item))
        conn.execute('''INSERT INTO material_changes
            (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
            (self.project, self.item, json.dumps(before), json.dumps(after)))
        conn.commit()
        conn.close()
        views = build_quote_views(self.project)
        self.assertEqual((views['script']['items'][0]['length'],
                          views['script']['items'][0]['width']), (0, 0))
        self.assertNotIn('length', views['agreement']['items'][0]['confirmed_fields'])
        self.assertNotIn('width', views['agreement']['items'][0]['confirmed_fields'])
        self.assertEqual(views['agreement']['known_cost'], 0)

    def test_conflicting_ai_models_remove_only_conflicted_field(self):
        self._review(ai_pdf_review.AUTO_MODEL, width=234)
        self._review(ai_pdf_review.FALLBACK_MODEL, width=250)
        conn = database.get_connection()
        conn.execute('''UPDATE materials SET length=299,width=234,unit_price=7,
            total_price=14 WHERE id=?''', (self.item,))
        conn.commit()
        conn.close()
        views = build_quote_views(self.project)
        self.assertEqual(len(views['ai']['items']), 1)
        agreed = views['agreement']['items'][0]
        self.assertEqual(agreed['confirmed_fields']['length'], 299)
        self.assertNotIn('width', agreed['confirmed_fields'])
        self.assertEqual(views['agreement']['known_cost'], 0)

    def test_missing_ai_dimension_is_ignored_without_failing_whole_project(self):
        self._review(ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        conn.execute('UPDATE materials SET depth=20 WHERE id=?', (self.item,))
        conn.commit()
        conn.close()
        views = build_quote_views(self.project)
        self.assertEqual(len(views['ai']['items']), 1)
        self.assertEqual(views['agreement']['items'][0]['confirmed_fields']['thickness'], 1)
        self.assertNotIn('depth', views['agreement']['items'][0]['confirmed_fields'])

    def test_agreement_screen_omits_item_with_only_disagreements(self):
        self._review(ai_pdf_review.AUTO_MODEL, length=310, width=250,
                     scope='local_table')
        conn = database.get_connection()
        conn.execute('''UPDATE materials SET length=299,width=234,thickness=2
            WHERE id=?''', (self.item,))
        conn.commit()
        conn.close()
        views = build_quote_views(self.project)
        self.assertEqual(len(views['ai']['items']), 1)
        self.assertEqual(views['agreement']['items'], [])

    def test_route_is_read_only_and_missing_project_is_404(self):
        self._review(ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        before = conn.execute('SELECT COUNT(*) FROM material_changes').fetchone()[0]
        conn.close()
        self.assertEqual(get_quote_views(self.project)['project_id'], self.project)
        conn = database.get_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM material_changes').fetchone()[0],
                         before)
        conn.close()
        with self.assertRaises(HTTPException) as error:
            get_quote_views(999999)
        self.assertEqual(error.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
