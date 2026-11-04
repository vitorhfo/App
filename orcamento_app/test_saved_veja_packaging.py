"""VEJA reference BOM includes three packaging components absent in the saved copy."""

from pathlib import Path
import sqlite3
import unittest

from reader_v3 import process_complete_project


class SavedVejaPackagingTest(unittest.TestCase):
    def test_three_reference_bom_rows_are_saved_without_changing_other_purchases(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file(): self.skipTest('Banco salvo indisponível')
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            root=Path(conn.execute('SELECT folder_path FROM projects WHERE id=1').fetchone()[0])
            if not root.is_dir(): self.skipTest('Projeto VEJA indisponível')
            fresh={item['item_num']:item for item in process_complete_project(root)['materials']}
            for item_num,qty in ((37,20),(38,0.08),(39,1)):
                with self.subTest(item_num=item_num):
                    source=fresh[item_num]
                    self.assertEqual(source['quantity'],qty)
                    self.assertIn('#page=6',source['source_page'])
                    row=conn.execute('SELECT * FROM materials WHERE project_id=1 AND item_num=?',
                                     (item_num,)).fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual((row['description'],row['quantity'],row['item_type']),
                                     (source['description'],qty,'comprado'))
            tape=conn.execute('SELECT quantity FROM materials WHERE project_id=1 AND item_num=36').fetchone()
            self.assertEqual(tape['quantity'],3)
