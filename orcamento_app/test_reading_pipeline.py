"""Real PDF -> import -> manual correction -> reimport -> workbook contents."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import openpyxl

import database
from app import (ProjectCreate, MaterialUpdate, create_project, import_project_folder,
                 update_material, get_project_full_data)
from exporter import export_budget_xlsx
from template_reports import _split_items


class ReadingPipelineTests(unittest.TestCase):
    def test_real_alpa_reimport_keeps_manual_geometry_other_parts_and_export(self):
        root = Path(__file__).resolve().parents[2] / 'DADOS'
        source = next(root.glob('JOS*/TESTES*/ALPARGATAS/ALPA BASICO 5x5/PROJETO'))
        runs = Path(__file__).resolve().parent / 'data' / 'test_runs'
        runs.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runs, prefix='reading_pipeline_') as folder:
            with patch.object(database, 'DB_PATH', str(Path(folder) / 'pipeline.db')):
                database.init_db()
                project_id = create_project(ProjectCreate(name='Regressão ALPA 5x5'))['id']
                self.assertIsNone(get_project_full_data(project_id)['reading_report'])
                import_project_folder(project_id, folder_path=str(source))
                before = get_project_full_data(project_id)
                tag = next(item for item in before['materials']
                           if item['description'] == 'CHAPA TAG PARA QR CODE')
                def unaffected(data):
                    return [(m['drawing_id'], m['parent_assembly'], m['quantity'],
                             m['width'], m['length'], m['thickness'], m['unit_weight'])
                            for m in data['materials'] if m['drawing_id'] != tag['drawing_id']]
                original_others = unaffected(before)
                update_material(project_id, tag['id'], MaterialUpdate(
                    width=71, observation='Largura conferida manualmente: 71 mm.'))
                import_project_folder(project_id, folder_path=str(source))
                after = get_project_full_data(project_id)
                edited = next(m for m in after['materials'] if m['drawing_id'] == tag['drawing_id'])
                self.assertEqual(edited['width'], 71)
                self.assertIn('Largura conferida manualmente', edited['observation'])
                self.assertEqual(unaffected(after), original_others)
                events = after['reading_report']['events']
                self.assertTrue(any(e['stage'] == 'selected' for e in events))
                self.assertTrue(any(e['profile'] == 'technical_14_grid' for e in events))
                self.assertTrue(all(e['source_page'] and e['reason'] for e in events))

                # Keep the company-template input contract: no assemblies in
                # either cost section, and polymers stay with bought items.
                groups = _split_items(after['materials'])
                self.assertTrue(any(m['drawing_id'] == edited['drawing_id'] for m in groups['bought']))
                self.assertFalse(any(m['item_type'] == 'subconjunto'
                                     for items in groups.values() for m in items))

                path = Path(folder) / 'conferencia.xlsx'
                export_budget_xlsx(after['project'], after['materials'], after['markup_result'],
                                   after['weight_result'], str(path), after['pending_decisions'])
                book = openpyxl.load_workbook(path, read_only=True, data_only=False)
                try:
                    rows = list(book['Lista de Materiais (BOM)'].iter_rows(min_row=2, values_only=True))
                    self.assertEqual(len(rows), len(after['materials']))
                    expected = [(m['quantity'], m['description'], m['material'], m['width'],
                                 m['length'], m['drawing_id'], m['source_page']) for m in after['materials']]
                    actual = [(r[1], r[2], r[5] or '', r[8], r[10], r[11], r[21]) for r in rows]
                    self.assertEqual(actual, expected)
                finally:
                    book.close()


if __name__ == '__main__':
    unittest.main()
