"""The FLEXVERO wire table is a set of alternatives, not three priced cuts."""

import sqlite3
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import pymupdf

from wire_variants import insert_wire_variants, parse_parameterized_wire_table
from reader_v3 import details
import ai_pdf_review
import database


APP = Path(__file__).resolve().parent
DB = APP / 'data' / 'orcamento.db'


class ParameterizedWireTest(unittest.TestCase):
    def real_pdf(self):
        conn = sqlite3.connect(DB)
        row = conn.execute('SELECT folder_path FROM projects WHERE id=86').fetchone()
        conn.close()
        self.assertIsNotNone(row)
        return Path(row[0]) / 'APARADOR Grade Prateleira.PDF'

    def test_real_aparador_table_uses_comprimento_not_measure_a_or_bend(self):
        pdf = self.real_pdf()
        with pymupdf.open(pdf) as doc:
            page_text = doc[0].get_text()
        variants = parse_parameterized_wire_table(page_text)
        self.assertEqual([v['code'] for v in variants], ['332853', '332854', '332855'])
        self.assertEqual([v['measure_a'] for v in variants], [345, 495, 540])
        self.assertEqual([v['cut_length'] for v in variants], [400, 550, 595])
        self.assertEqual([v['diameter'] for v in variants], [5, 5, 5])
        self.assertTrue(all(v['quantity'] is None for v in variants))
        self.assertEqual(details(page_text)['length'], 0)
        from reader_v3 import process_complete_project
        project = process_complete_project(pdf.parent)
        self.assertEqual([v['cut_length'] for v in project['wire_variants']], [400, 550, 595])
        self.assertEqual(len(project['materials']), 1)
        self.assertEqual(project['materials'][0]['item_type'], 'subconjunto')

    def test_sheet_measure_a_and_wire_without_comprimento_are_not_variants(self):
        sheet = ('"A"\n15\nMEDIDA "A"\n80\n150\n230\n'
                 'Material:\nCHAPA F.F. SAE 1008 D.O. ESP. 0,90mm\n')
        wire = '"A"\n35\nMaterial:\nARAME BTC Ø5mm\n'
        self.assertEqual(parse_parameterized_wire_table(sheet), [])
        self.assertEqual(parse_parameterized_wire_table(wire), [])

    def test_rejects_ambiguous_or_duplicate_codes(self):
        text = ('CÓDIGO\nNOMINAL\nMEDIDA "A"\nCOMPRIMENTO\n'
                '332853\n345 x 35h\n345\n400\n'
                '332853\n495 x 35h\n495\n550\n'
                'Material:\nARAME BTC Ø5mm\n')
        self.assertEqual(parse_parameterized_wire_table(text), [])

    def test_ai_button_stores_options_without_cost_then_selected_quantity_uses_cut(self):
        from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions
        from app import (WireVariantSelection, delete_material, get_project_full_data,
                         select_wire_variant, update_material, MaterialUpdate)

        scratch = APP / 'data' / 'test_runs'
        scratch.mkdir(exist_ok=True)
        root = scratch / f'wire_variant_{uuid.uuid4().hex}'
        root.mkdir()
        self.addCleanup(shutil.rmtree, root)
        with self.subTest('isolated real PDF import'):
            source = root / 'source'
            source.mkdir()
            pdf = source / 'APARADOR Grade Prateleira.PDF'
            shutil.copy2(self.real_pdf(), pdf)
            with patch.object(database, 'DB_PATH', str(root / 'quote.db')), \
                 patch.object(ai_pdf_review, 'REVIEW_DIR', root / 'reviews'):
                database.init_db()
                conn = database.get_connection()
                project_id = conn.execute('INSERT INTO projects(name,folder_path) VALUES (?,?)',
                                          ('Teste variantes', str(source))).lastrowid
                parent_id = conn.execute('''INSERT INTO materials
                    (project_id,description,group_name,item_type,quantity,source_page)
                    VALUES (?,?,?,?,?,?)''',
                    (project_id, 'APARADOR Grade Prateleira', 'Subconjunto',
                     'subconjunto', 1, f'{pdf.name}#page=1')).lastrowid
                conn.commit()
                with pymupdf.open(pdf) as drawing:
                    variants = parse_parameterized_wire_table(drawing[0].get_text())
                for model in (ai_pdf_review.AUTO_MODEL, ai_pdf_review.FALLBACK_MODEL):
                    result = ai_pdf_review.normalize_response({'items': [
                        {'item_number': v['code'], 'description': 'APARADOR Grade Prateleira',
                         'item_type': 'materia_prima', 'material': v['material'],
                         'dimension_basis': 'corte', 'length': v['cut_length'],
                         'radius_diam': v['diameter'], 'quantity': None,
                         'evidence': f"COMPRIMENTO {v['cut_length']} Ø{v['diameter']}"}
                        for v in variants]})
                    ai_pdf_review.save_review(project_id, pdf.name, 1, pdf, result, model)
                    conn.execute('''INSERT INTO ai_review_jobs
                        (project_id,path,page,model,state) VALUES (?,?,1,?,'done')''',
                        (project_id, pdf.name, model))
                conn.commit()
                conn.close()
                self.assertEqual(preview_pending_ai_dimensions(project_id)['new_wire_variants'], 3)
                self.assertEqual(apply_pending_ai_dimensions(project_id)['new_wire_variants'], 3)
                self.assertEqual(apply_pending_ai_dimensions(project_id)['new_wire_variants'], 0)
                self.assertEqual(preview_pending_ai_dimensions(project_id)['unlinked_ai_items'], 0)
                self.assertEqual(preview_pending_ai_dimensions(project_id)['pending_wire_quantities'], 3)
                before = get_project_full_data(project_id)
                self.assertEqual(len(before['materials']), 1)
                self.assertEqual(before['materials'][0]['id'], parent_id)
                self.assertEqual([v['cut_length'] for v in before['wire_variants']], [400, 550, 595])
                self.assertTrue(all(v['quantity'] is None for v in before['wire_variants']))
                self.assertTrue(all(v['ai_agreement_count'] == 2 for v in before['wire_variants']))
                self.assertEqual(before['markup_result']['cost_mp'], 0)
                selected_id = before['wire_variants'][0]['id']
                added = select_wire_variant(project_id, selected_id, WireVariantSelection(quantity=2))
                after = get_project_full_data(project_id)
                wire = next(m for m in after['materials'] if m['id'] == added['id'])
                self.assertEqual((wire['drawing_length'], wire['length'], wire['quantity']),
                                 (400, 420, 2))
                self.assertGreaterEqual(wire['finished_unit_weight'], .062156)
                self.assertEqual(wire['raw_code'], '332853')
                self.assertEqual(wire['source_page'], f'{pdf.name}#page=1')
                self.assertEqual(after['wire_variants'][0]['current_quantity'], 2)
                self.assertEqual(preview_pending_ai_dimensions(project_id)['pending_wire_quantities'], 2)
                conn = database.get_connection()
                changed_source = {**variants[0], 'source_page': f'{pdf.name}#page=1',
                                  'description': pdf.stem, 'cut_length': 430,
                                  'ai_agreement_count': 3}
                self.assertEqual(insert_wire_variants(conn, project_id, [changed_source]), 0)
                conn.commit()
                conn.close()
                self.assertEqual(get_project_full_data(project_id)['wire_variants'][0]['cut_length'], 400)
                update_material(project_id, added['id'], MaterialUpdate(quantity=3))
                self.assertEqual(get_project_full_data(project_id)['wire_variants'][0]['current_quantity'], 3)
                delete_material(project_id, added['id'])
                self.assertIsNone(get_project_full_data(project_id)['wire_variants'][0]['material_id'])
                second_id = before['wire_variants'][1]['id']
                second = select_wire_variant(project_id, second_id,
                                             WireVariantSelection(quantity=1))
                larger = next(m for m in get_project_full_data(project_id)['materials']
                              if m['id'] == second['id'])
                self.assertEqual((larger['drawing_length'], larger['length']), (550, 570))
                self.assertGreater(larger['finished_unit_weight'], .08)


if __name__ == '__main__':
    unittest.main()
