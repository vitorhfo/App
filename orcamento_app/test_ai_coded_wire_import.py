"""A parent BOM code selects one developed wire cut from a child drawing."""

import json
import unittest
from pathlib import Path

import pymupdf
from reportlab.pdfgen import canvas

import ai_pdf_review
import database
import test_ai_dimension_application as fixture
from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions
from ai_coded_wire_import import parse_coded_wire_table


class AiCodedWireImportTest(unittest.TestCase):
    setUp = fixture.AiDimensionApplicationTest.setUp

    def _fixture(self):
        path = self.source / 'ARCO Grade Prateleira.pdf'
        pdf = canvas.Canvas(str(path))
        lines = ('CÓDIGO', 'NOMINAL', 'MEDIDA "A"', 'MEDIDA "B"',
                 'COMPRIMENTO', '332857', 'GRDIMBAP', '580', '515', '2155',
                 '332856', 'CONGIMBAP', '535', '610', '2255', 'ARAME BTC Ø6mm')
        for index, line in enumerate(lines):
            pdf.drawString(50, 750 - 18 * index, line)
        pdf.save()
        answer = ai_pdf_review.normalize_response({'items': [
            {'item_number': '332857', 'description': 'GRDIMBAP', 'material': 'ARAME BTC',
             'length': 2155, 'radius_diam': 6, 'dimension_basis': 'perfil_comercial',
             'evidence': 'Código 332857 COMPRIMENTO 2155 Ø6'},
            {'item_number': '332856', 'description': 'CONGIMBAP', 'material': 'ARAME BTC',
             'length': 2255, 'radius_diam': 6, 'dimension_basis': 'perfil_comercial',
             'evidence': 'Código 332856 COMPRIMENTO 2255 Ø6'}]})
        ai_pdf_review.save_review(self.project, path.name, 1, path, answer,
                                  ai_pdf_review.AUTO_MODEL)
        conn = database.get_connection()
        conn.execute('''INSERT INTO ai_review_jobs
            (project_id,path,page,model,state,attempts,next_attempt_at,force)
            VALUES (?,?,1,?,'done',1,0,0)''',
            (self.project, path.name, ai_pdf_review.AUTO_MODEL))
        conn.execute('''UPDATE materials SET description=?,group_name='Outros Comprados',
            item_type='comprado',material='',length=0,width=0,thickness=0,
            unit_weight=0,unit_area=0,unit_price=NULL,raw_code='332856',
            source_page=?,pending_issue=? WHERE id=?''',
            ('ARCO Grade Prateleira - CONGIMBAP', 'MALHA CONGIMBAP.pdf#page=1',
             'Desenho da peça não localizado; conferir dimensões e peso.', self.item))
        conn.commit()
        conn.close()
        return path

    def test_real_arco_table_has_distinct_codes_and_developed_cuts(self):
        root = Path(__file__).parent / 'data' / 'uploads' / 'proj_92'
        files = list(root.rglob('ARCO Grade Prateleira.PDF'))
        if not files:
            self.skipTest('PDF real do projeto #92 indisponível')
        with pymupdf.open(files[0]) as pdf:
            rows = parse_coded_wire_table(pdf[0].get_text())
        self.assertEqual((rows['332856']['cut_length'], rows['332856']['diameter']),
                         (2255, 6))
        self.assertEqual(rows['332857']['cut_length'], 2155)

    def test_import_selects_parent_code_keeps_quantity_and_welding_allowance(self):
        self._fixture()
        self.assertEqual(preview_pending_ai_dimensions(self.project)['coded_wire_items'], 1)
        result = apply_pending_ai_dimensions(self.project)
        self.assertEqual(result['applied_coded_wire_items'], 1)
        conn = database.get_connection()
        row = dict(conn.execute('SELECT * FROM materials WHERE id=?', (self.item,)).fetchone())
        conn.close()
        self.assertEqual((row['group_name'], row['item_type'], row['quantity']),
                         ('Arame', 'materia_prima', 2))
        self.assertEqual((row['drawing_length'], row['length'], row['radius_diam']),
                         (2255, 2275, 6))
        self.assertEqual(apply_pending_ai_dimensions(self.project)['applied_coded_wire_items'], 0)

    def test_wrong_code_or_manual_change_does_not_import(self):
        self._fixture()
        conn = database.get_connection()
        conn.execute("UPDATE materials SET raw_code='999999' WHERE id=?", (self.item,))
        conn.commit()
        conn.close()
        self.assertEqual(preview_pending_ai_dimensions(self.project)['coded_wire_items'], 0)
        conn = database.get_connection()
        conn.execute("UPDATE materials SET raw_code='332856' WHERE id=?", (self.item,))
        conn.execute('''INSERT INTO material_changes(project_id,material_id,before_json,after_json)
            VALUES (?,?,?,?)''', (self.project, self.item,
                                  json.dumps({'length': 50}), json.dumps({'length': 0})))
        conn.commit()
        conn.close()
        self.assertEqual(preview_pending_ai_dimensions(self.project)['coded_wire_items'], 0)


if __name__ == '__main__':
    unittest.main()
