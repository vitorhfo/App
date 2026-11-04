"""An AI reading can complete a linked part without overriding trusted values."""

import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from reportlab.pdfgen import canvas

import ai_pdf_review
import ai_review_queue
import database
from config import DATA_DIR


class AiDimensionApplicationTest(unittest.TestCase):
    def setUp(self):
        scratch = Path(DATA_DIR) / 'test_runs'
        scratch.mkdir(exist_ok=True)
        self.root = scratch / f'ai_apply_{uuid.uuid4().hex}'
        self.root.mkdir()
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
        drawing = self.source / 'PSAI FR. Display.pdf'
        pdf = canvas.Canvas(str(drawing))
        pdf.drawString(50, 700, 'PSAI FR. Display')
        pdf.save()
        conn = database.get_connection()
        self.project = conn.execute('INSERT INTO projects(name,folder_path) VALUES (?,?)',
                                    ('Teste', str(self.source))).lastrowid
        self.item = conn.execute('''INSERT INTO materials
            (project_id,description,group_name,item_type,material,source_page,
             length,width,thickness,unit_weight,unit_area,quantity,pending_issue)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (self.project, 'PSAI FR. Display', 'Polímero/PSAI', 'comprado',
             'PSAI BRANCO #1mm', 'PSAI FR. Display.pdf#page=1',
             0, 0, 1, .102365, .131708152, 2,
             'Conferir cotas/peso no desenho; extração parcial.')).lastrowid
        conn.commit()
        conn.close()

    def read(self):
        conn = database.get_connection()
        try:
            return dict(conn.execute('SELECT * FROM materials WHERE id=?', (self.item,)).fetchone())
        finally:
            conn.close()

    def test_auto_review_fills_linked_missing_dimensions_and_keeps_title_area(self):
        ai_review_queue.enqueue_pdf(self.project, 'PSAI FR. Display.pdf')
        answer = ai_pdf_review.normalize_response({'items': [{
            'description': 'PSAI FR. Display', 'item_type': 'comprado',
            'dimension_basis': 'externa', 'length': 299, 'width': 234,
            'thickness': 1, 'unit_weight_g': 102.365,
            'evidence': 'Cotas 299 x 234 na vista plana; 1 mm no carimbo'}]})
        with patch.object(ai_review_queue, 'configured_key', return_value='test-key'), \
             patch.object(ai_review_queue, 'request_google', return_value=answer):
            self.assertTrue(ai_review_queue.process_next_job())
        item = self.read()
        self.assertEqual((item['length'], item['width']), (299, 234))
        self.assertEqual(item['unit_area'], .131708152)
        self.assertGreaterEqual(item['unit_weight'], .102365)
        self.assertEqual(item['quantity'], 2)
        self.assertNotIn('Conferir cotas/peso', item['pending_issue'])
        self.assertIn('Gemini', item['observation'])
        conn = database.get_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM material_changes WHERE material_id=?',
                                      (self.item,)).fetchone()[0], 1)
        conn.close()

    def test_wrong_part_and_external_metal_do_not_fill_dimensions(self):
        from ai_apply_dimensions import apply_review
        wrong = ai_pdf_review.normalize_response({'items': [{
            'description': 'Outro produto', 'dimension_basis': 'corte',
            'length': 400, 'width': 300, 'evidence': 'Cotas 400 x 300'}]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 1, wrong,
                                      ai_pdf_review.AUTO_MODEL), 0)
        self.assertEqual(self.read()['length'], 0)
        conn = database.get_connection()
        conn.execute("UPDATE materials SET group_name='Chapa' WHERE id=?", (self.item,))
        conn.commit()
        conn.close()
        external = ai_pdf_review.normalize_response({'items': [{
            'description': 'PSAI FR. Display', 'dimension_basis': 'externa',
            'length': 299, 'width': 234, 'evidence': 'Cotas externas 299 x 234'}]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 1, external,
                                      ai_pdf_review.AUTO_MODEL), 0)
        self.assertEqual(self.read()['length'], 0)

    def test_prior_manual_dimension_is_never_replaced(self):
        from ai_apply_dimensions import apply_review
        conn = database.get_connection()
        before = self.read()
        conn.execute('''INSERT INTO material_changes(project_id,material_id,before_json,after_json)
            VALUES (?,?,?,?)''', (self.project, self.item,
                                   '{"length": 80}', '{"length": 0}'))
        conn.commit()
        conn.close()
        answer = ai_pdf_review.normalize_response({'items': [{
            'description': 'PSAI FR. Display', 'dimension_basis': 'externa',
            'length': 299, 'width': 234,
            'evidence': 'Cotas 299 x 234 na vista plana'}]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 1, answer,
                                      ai_pdf_review.AUTO_MODEL), 1)
        after = self.read()
        self.assertEqual(after['length'], before['length'])
        self.assertEqual(after['width'], 234)

    def test_two_numbered_cuts_keep_their_own_lengths_and_quantities(self):
        from ai_apply_dimensions import apply_review
        conn = database.get_connection()
        ids = []
        for number, quantity in ((1, 2), (2, 4)):
            ids.append(conn.execute('''INSERT INTO materials
                (project_id,description,group_name,item_type,material,source_page,
                 length,width,depth,thickness,quantity)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (self.project, f'TUBO IND 50 X 30 X 1,5mm - corte {number}',
                 'Tubo Quadrado/Retangular', 'materia_prima',
                 'TUBO IND 50 X 30 X 1,5mm', 'PSAI FR. Display.pdf#page=1',
                 0, 50, 30, 1.5, quantity)).lastrowid)
        conn.commit()
        conn.close()
        result = ai_pdf_review.normalize_response({'items': [
            {'item_number': '1', 'description': 'TUBO IND 50 X 30 X 1,5mm',
             'dimension_basis': 'perfil_comercial', 'length': 1286,
             'evidence': 'Quadro corte 1: comprimento 1286 mm'},
            {'item_number': '2', 'description': 'TUBO IND 50 X 30 X 1,5mm',
             'dimension_basis': 'perfil_comercial', 'length': 323,
             'evidence': 'Quadro corte 2: comprimento 323 mm'}]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 1, result,
                                      ai_pdf_review.AUTO_MODEL), 2)
        conn = database.get_connection()
        rows = [dict(conn.execute('SELECT length,quantity FROM materials WHERE id=?',
                                  (item_id,)).fetchone()) for item_id in ids]
        conn.close()
        self.assertEqual([(row['length'], row['quantity']) for row in rows],
                         [(1286, 2), (323, 4)])

    def test_dimension_without_number_in_evidence_is_not_applied(self):
        from ai_apply_dimensions import apply_review
        answer = ai_pdf_review.normalize_response({'items': [{
            'description': 'PSAI FR. Display', 'dimension_basis': 'externa',
            'length': 299, 'width': 234, 'evidence': 'Vista plana sem cotas legíveis'}]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 1, answer,
                                      ai_pdf_review.AUTO_MODEL), 0)
        self.assertEqual((self.read()['length'], self.read()['width']), (0, 0))

    def test_other_page_completes_unique_tube_without_changing_quantity(self):
        from ai_apply_dimensions import apply_review
        conn = database.get_connection()
        tube_id = conn.execute('''INSERT INTO materials
            (project_id,description,group_name,item_type,material,source_page,
             length,width,depth,thickness,quantity,unit_weight)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (self.project, 'TUBO VERTICAL FUNDO', 'Tubo Quadrado/Retangular',
             'materia_prima', 'TUBO QUAD. ACO 25 X 25 X 0.90MM',
             'PSAI FR. Display.pdf#page=1', 1630, 25, 0, .9, 2, 1.110138)).lastrowid
        conn.commit()
        conn.close()
        answer = ai_pdf_review.normalize_response({'items': [
            {'item_number': '1', 'description': 'TUBO VERTICAL FUNDO',
             'item_type': 'materia_prima', 'material': 'TUBO QUADRADO 25X25X0,9',
             'dimension_basis': 'perfil_comercial', 'length': 1630,
             'width': 25, 'depth': 25, 'thickness': .9, 'quantity': 1,
             'quantity_scope': 'local_table',
             'evidence': 'Tabela e cotas 1630, 25, 25, 0,9 nesta página'}]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 2, answer,
                                      ai_pdf_review.AUTO_MODEL), 1)
        conn = database.get_connection()
        row = dict(conn.execute('SELECT * FROM materials WHERE id=?', (tube_id,)).fetchone())
        conn.close()
        self.assertEqual((row['length'], row['width'], row['depth'], row['thickness']),
                         (1630, 25, 25, .9))
        self.assertEqual(row['quantity'], 2)
        self.assertEqual(row['source_page'], 'PSAI FR. Display.pdf#page=1')

    def test_folded_sheet_warning_blocks_false_cut_even_if_basis_says_cut(self):
        from ai_apply_dimensions import apply_review
        conn = database.get_connection()
        conn.execute("UPDATE materials SET group_name='Chapa',material='CHAPA ACO 2mm' "
                     'WHERE id=?', (self.item,))
        conn.commit()
        conn.close()
        answer = ai_pdf_review.normalize_response({'items': [{
            'description': 'PSAI FR. Display', 'dimension_basis': 'corte',
            'length': 96.8, 'width': 111.8,
            'evidence': 'Cotas 96,8 e 111,8 mm no desenho',
            'warnings': ['Peça possui dobras, dimensões externas extraídas das vistas']} ]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 1, answer,
                                      ai_pdf_review.AUTO_MODEL), 0)
        self.assertEqual((self.read()['length'], self.read()['width']), (0, 0))

    def test_sheet_candidate_must_match_title_weight_but_flat_strip_passes(self):
        from ai_apply_dimensions import apply_review
        conn = database.get_connection()
        conn.execute('''UPDATE materials SET group_name='Chapa',material='CHAPA SAE',
            thickness=2,unit_weight=0.154122 WHERE id=?''', (self.item,))
        conn.commit()
        conn.close()
        folded = ai_pdf_review.normalize_response({'items': [{
            'description': 'PSAI FR. Display', 'dimension_basis': 'planificacao',
            'length': 96.8, 'width': 111.8,
            'evidence': 'Cotas 96,8 x 111,8 mm'}]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 1, folded,
                                      ai_pdf_review.AUTO_MODEL), 0)
        self.assertEqual(self.read()['length'], 0)
        conn = database.get_connection()
        conn.execute('''UPDATE materials SET length=400,thickness=0.75,
            unit_weight=0.059411 WHERE id=?''', (self.item,))
        conn.commit()
        conn.close()
        strip = ai_pdf_review.normalize_response({'items': [{
            'description': 'PSAI FR. Display', 'dimension_basis': 'corte',
            'width': 25.4, 'evidence': 'Largura 25,4 mm'}]})
        self.assertEqual(apply_review(self.project, 'PSAI FR. Display.pdf', 1, strip,
                                      ai_pdf_review.AUTO_MODEL), 1)
        self.assertEqual(self.read()['width'], 25.4)


if __name__ == '__main__':
    unittest.main()
