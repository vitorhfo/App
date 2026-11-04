"""Both OP01 copies must include all three physical lateral components."""

from pathlib import Path
import sqlite3
import unittest

from reader_v3 import process_complete_project


class SavedOp01LateralTest(unittest.TestCase):
    def test_both_saved_copies_include_lateral_bom(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file():
            self.skipTest('Banco salvo indisponível')
        names={'QUADRO COMUNICAÇÃO LATERAL','CHAPA COMUNICAÇÃO LATERAL',
               'CANALETA COMUNICAÇÃO LATERAL'}
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            for project_id in (3,20):
                with self.subTest(project_id=project_id):
                    project=conn.execute('SELECT folder_path FROM projects WHERE id=?',
                                         (project_id,)).fetchone()
                    if not project or not Path(project['folder_path']).is_dir():
                        self.skipTest('Desenho OP01 indisponível')
                    fresh=[item for item in process_complete_project(project['folder_path'])['materials']
                           if item['description'] in names]
                    self.assertEqual({item['description'] for item in fresh},names)
                    self.assertEqual({item['quantity'] for item in fresh},{2})
                    saved=conn.execute('''SELECT * FROM materials WHERE project_id=?
                        AND description IN (?,?,?)''',(project_id,*names)).fetchall()
                    self.assertEqual({item['description'] for item in saved},names)
                    self.assertEqual({item['quantity'] for item in saved},{2})
                    self.assertTrue(all('#page=7' in item['source_page'] for item in saved))


if __name__=='__main__':
    unittest.main()
