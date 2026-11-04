"""Protect the corrected 10-roll, PSAI-clad floor quote."""

import unittest

from database import get_connection
from quote_rehau_floor_psai import build_items, structural_checks


class RehauFloorPsaiQuoteTest(unittest.TestCase):
    def test_ten_rolls_and_psai_cladding_without_mdf(self):
        conn = get_connection()
        try:
            rows = build_items(conn, 0)
        finally:
            conn.close()
        axles = [r for r in rows if 'kit de eixo, buchas e batentes' in r['description']]
        psai = [r for r in rows if r['group_name'] == 'Polímero/PSAI']
        self.assertEqual(sum(r['quantity'] for r in axles), 10)
        self.assertFalse(any('MDF' in r['description'].upper() for r in rows))
        self.assertFalse(any(r['thickness'] == 10 for r in rows))
        self.assertFalse(any('lastro' in r['description'].lower() for r in rows))
        self.assertTrue(any(r['description'].startswith('TUBO QUADRADO 30X30X1,5MM')
                            and '1820MM' in r['description'] for r in rows))
        self.assertTrue(any(r['description'] == 'PSAI LATERAL 1700X470X2MM'
                            and r['quantity'] == 2 for r in psai))
        self.assertTrue(any(r['description'] == 'PSAI TESTEIRA 500X220X2MM'
                            and r['quantity'] == 2 for r in psai))
        self.assertTrue(psai)
        self.assertTrue(all(r['item_type'] == 'comprado' and r['thickness'] == 2
                            and 'CONTROLV!D6' in r['price_source'] for r in psai))
        self.assertTrue(any('PSAI TAMPA BASE' in r['description']
                            for r in psai))
        self.assertTrue(any('GRADE DE APOIO DA TAMPA PSAI' in r['description']
                            for r in rows))
        self.assertFalse(any(r['group_name'] == 'Chapa' and r['length'] == 500
                             and r['width'] == 500 for r in rows))
        self.assertTrue(all(r['unit_price'] is not None for r in rows))
        checks = structural_checks()
        self.assertLessEqual(checks['roll_stack_mm'], checks['frame_height_mm'])
        self.assertLessEqual(checks['overall_height_mm'], 1900)
        self.assertLess(checks['caster_three_point_kg'], checks['caster_nominal_kg'])


if __name__ == '__main__':
    unittest.main()
