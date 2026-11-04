"""Protect the eight-roll photo variant from accidentally inheriting ten-roll BOMs."""

import unittest

from database import get_connection
from quote_rehau_floor_structural import build_items, structural_checks


class RehauFloorStructuralQuoteTest(unittest.TestCase):
    def test_eight_rolls_fit_and_are_supported_without_double_charging(self):
        conn = get_connection()
        try:
            rows = build_items(conn, 0)
        finally:
            conn.close()
        axles = [r for r in rows if 'kit de eixo, buchas e batentes' in r['description']]
        casters = [r for r in rows if 'rodízio giratório' in r['description']]
        self.assertEqual(sum(r['quantity'] for r in axles), 8)
        self.assertEqual(sum(r['quantity'] for r in casters), 4)
        self.assertTrue(all(r['unit_price'] is not None for r in rows))
        self.assertTrue(all(r['item_type'] != 'subconjunto' for r in rows))
        checks = structural_checks()
        self.assertLessEqual(checks['roll_stack_mm'], checks['frame_height_mm'])
        self.assertLessEqual(checks['overall_height_mm'], 1900)
        self.assertLess(checks['caster_three_point_kg'], checks['caster_nominal_kg'])
        self.assertLess(checks['rail_deflection_mm'], 1)


if __name__ == '__main__':
    unittest.main()
