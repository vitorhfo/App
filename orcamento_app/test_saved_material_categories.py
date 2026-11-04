"""Regression checks for saved bought accessories and raw flat bars."""

from pathlib import Path
import sqlite3
import unittest

from calc_engine import resolve_material_group
from mass_math import calculated_weight
from reader_v3 import material_cell_spec


class SavedMaterialCategoriesTest(unittest.TestCase):
    def test_flat_bar_profile_does_not_turn_a_screw_into_raw_metal(self):
        spec=material_cell_spec('FERRO CHATO 3/4" X 1/8"')
        self.assertEqual((spec['width'],spec['thickness']),(19.05,3.175))
        self.assertEqual(resolve_material_group('TRAVA','FERRO CHATO 3/4" X 1/8"'),'Chapa')
        self.assertEqual(resolve_material_group('PARAFUSO SEXTAVADO','AÇO 1/4"'),'Ferragens')

    def test_saved_categories_and_dimensions_match_real_materials(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file():
            self.skipTest('Banco salvo indisponível')
        bought=(146,188,206,219,250,828,1272)
        raw=(1034,1286,1296)
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            for item_id in bought:
                with self.subTest(item_id=item_id):
                    item=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
                    self.assertEqual(item['item_type'],'comprado')
                    self.assertEqual(item['group_name'],'Polímero/PSAI')
            for item_id in raw:
                with self.subTest(item_id=item_id):
                    item=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
                    self.assertEqual(item['item_type'],'materia_prima')
                    self.assertEqual(item['group_name'],'Chapa')
                    self.assertGreater(item['width'],0)
                    self.assertEqual(item['thickness'],3.175)
                    if item['length']>0:
                        self.assertGreaterEqual(item['unit_weight']+1e-6,
                                                calculated_weight(dict(item)))


if __name__=='__main__':
    unittest.main()
