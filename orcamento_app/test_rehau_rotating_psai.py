"""Protect the separate rotating REHAU photo quote and its mechanical BOM."""

import unittest

from database import get_connection
from quote_rehau_floor_psai import build_items as floor_items
from quote_rehau_rotating_psai import build_items, mechanical_checks


class RehauRotatingPsaiQuoteTest(unittest.TestCase):
    def test_four_faces_rotation_and_manual_conventions(self):
        conn = get_connection()
        try:
            rows = build_items(conn, 0)
            floor = floor_items(conn, 0)
        finally:
            conn.close()

        self.assertEqual(sum(r['quantity'] for r in rows if 'EIXO ROLO' in r['description']), 32)
        self.assertEqual(sum(r['quantity'] for r in rows if 'PORTA PREÇO' in r['description']), 32)
        self.assertEqual(sum(r['quantity'] for r in rows if 'PÉ NIVELADOR' in r['description']), 4)
        self.assertTrue(any('PRATO GIRATÓRIO' in r['description'] for r in rows))
        self.assertTrue(any('GUIA RADIAL' in r['description'] for r in rows))
        self.assertTrue(any('TRAVA DE GIRO' in r['description'] for r in rows))
        self.assertFalse(any('RODÍZIO' in r['description'] or 'MDF' in r['description']
                             or r['thickness'] == 10 for r in rows))
        self.assertTrue(all(r['item_type'] != 'subconjunto' and r['unit_price'] is not None
                            for r in rows))
        psai = [r for r in rows if r['group_name'] == 'Polímero/PSAI']
        self.assertTrue(psai)
        self.assertTrue(all(r['item_type'] == 'comprado' and r['thickness'] == 2
                            for r in psai))
        self.assertEqual(sum(r['quantity'] for r in psai if 'PSAI PAINEL FACE' in r['description']), 4)
        self.assertTrue(any(r['description'].startswith('TUBO QUADRADO ') for r in rows))
        self.assertFalse(any('MIÓLO' in r['description'] for r in rows))
        self.assertEqual(sum(r['quantity'] for r in floor if 'kit de eixo, buchas e batentes'
                             in r['description']), 10)

        checks = mechanical_checks(rows)
        self.assertEqual(checks['overall_height_mm'], 1900)
        self.assertLessEqual(checks['stack_height_mm'], checks['available_roll_height_mm'])
        self.assertLess(checks['bearing_design_load_kg'], checks['bearing_static_rating_kg'])
        self.assertLess(checks['leveler_three_point_kg'], checks['leveler_target_kg'])


if __name__ == '__main__':
    unittest.main()
