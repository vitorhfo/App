"""The 5x5 lateral BOM contains one 420 mm foot on each side."""

from pathlib import Path
import sqlite3
import unittest

from reader_v3 import process_complete_project


class SavedAlpaFeetTest(unittest.TestCase):
    def test_five_by_five_keeps_both_foot_tubes(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file():
            self.skipTest('Banco salvo indisponível')
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            project=conn.execute('SELECT folder_path FROM projects WHERE id=14').fetchone()
            if not project or not Path(project['folder_path']).is_dir():
                self.skipTest('PDF 5x5 indisponível')
            source=[x for x in process_complete_project(project['folder_path'])['materials']
                    if x['description']=='TUBO PEZINHOS']
            self.assertEqual(len(source),1)
            self.assertEqual((source[0]['quantity'],source[0]['length'],source[0]['width'],
                              source[0]['depth'],source[0]['thickness']),
                             (2,420,25,25,0.9))
            saved=conn.execute("SELECT * FROM materials WHERE project_id=14 AND description='TUBO PEZINHOS'").fetchall()
            self.assertEqual(len(saved),1)
            self.assertEqual((saved[0]['quantity'],saved[0]['length'],saved[0]['width'],
                              saved[0]['depth'],saved[0]['thickness']),
                             (2,420,25,25,0.9))
            self.assertGreaterEqual(saved[0]['unit_weight'],source[0]['unit_weight'])


if __name__=='__main__':
    unittest.main()
