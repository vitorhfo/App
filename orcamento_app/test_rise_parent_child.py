"""RISE multi-page assemblies multiply their own children, not sibling parts."""

import unittest
from pathlib import Path

from reader_v3 import process_complete_project


SAMPLE = (Path(__file__).resolve().parent / 'data' / 'pepsi_amb0021_fixture')


@unittest.skipUnless(any(SAMPLE.glob('*.pdf')), 'PDF RISE AMB0021 indisponível')
class RiseParentChildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = process_complete_project(SAMPLE)
        cls.parts = cls.result['materials']

    def part(self, code, parent=None):
        matches = [item for item in self.parts if item['drawing_id'] == code
                   and (parent is None or parent in item['parent_assembly'])]
        self.assertEqual(len(matches), 1, (code, parent, matches))
        return matches[0]

    def test_bandeja_children_are_multiplied_by_three(self):
        parent = self.part('AMB0021M11.SLDPRT')
        self.assertEqual((parent['item_type'], parent['quantity']), ('subconjunto', 3))
        for code, expected_quantity in (
                ('AMB0021P25', 3), ('AMB0021P26', 3), ('AMB0021P27', 6),
                ('AMB0021P28', 9), ('AMB0021P29', 3)):
            child = self.part(code, 'BANDEJA')
            self.assertEqual(child['quantity'], expected_quantity)
            self.assertIn('#page=11', child['source_page'])
            self.assertNotEqual(child['item_type'], 'subconjunto')

    def test_sibling_quantities_and_distinct_laterals_stay_intact(self):
        self.assertEqual(self.part('AMB0021P30')['quantity'], 2)
        self.assertEqual(self.part('AMB0021P07')['quantity'], 1)
        self.assertEqual(self.part('AMB0021P18', 'TESTEIRA')['quantity'], 2)
        laterals = [item for item in self.parts if item['drawing_id'] == 'AMB0021P01']
        # Identical left/right cuts may be consolidated, but both sides count.
        self.assertEqual(sum(item['quantity'] for item in laterals), 2)
        self.assertTrue(any('Quadro Lateral Esq.' in
                            (item.get('mirrored_assembly') or item['parent_assembly'])
                            for item in laterals))
        # A separate older drawing (M12, page 14) is not a child of M11.
        self.assertFalse(any(item['drawing_id'] in ('AMB0021P33', 'AMB0021P34')
                             for item in self.parts))

    def test_accessories_without_description_cell_are_not_dropped(self):
        # The RISE table leaves DESCRIÇÃO blank and names these in MATERIAL.
        encaixes = [item for item in self.parts if
                    'Encaixe de Aço SAE-1010' in item['description']]
        self.assertEqual(sum(item['quantity'] for item in encaixes), 24)
        self.assertTrue(any(item['quantity'] == 12 and
                            'BANDEJA' in item['parent_assembly'] for item in encaixes))
        self.assertTrue(any('Bucha para Tub.' in item['description'] and
                            item['quantity'] == 4 for item in self.parts))

    def test_identical_material_rows_keep_their_pdf_quantities(self):
        tape = [item for item in self.parts if
                'Fita Dupla Face Gel 3M' in item['description']]
        self.assertEqual(sorted(item['quantity'] for item in tape), [3, 12])


if __name__ == '__main__':
    unittest.main()
