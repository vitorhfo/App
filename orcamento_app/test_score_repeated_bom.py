"""Repeated SCORE general lists are references, while detail lists remain physical."""

import unittest
from pathlib import Path

import pymupdf

from reader_v3 import process_complete_project
from score_package import read_score_package


ROOT = Path(__file__).resolve().parent / 'data' / 'bud_user_budget'
PDF = ROOT / 'REFERÊNCIA' / 'AMB_1902_24_BUD_ILHA.pdf'


@unittest.skipUnless(PDF.is_file(), 'PDF BUD ILHA indisponível')
class ScoreRepeatedBomTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with pymupdf.open(PDF) as pdf:
            cls.bom, cls.cuts = read_score_package(pdf)
        cls.parts = process_complete_project(ROOT)['materials']

    def test_repeated_general_list_is_counted_once(self):
        roots = [r for r in self.bom if r['drawing_id'] == 'AMB_1902_24_07_ASM_01']
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0]['page'], 13)  # revisão 03, não a 02 da página 81
        self.assertEqual(len([r for r in self.bom if
                              r['drawing_id'] == 'AMB_1902_24_07_PRT_23']), 1)
        self.assertEqual(len([r for r in self.parts if
                              r['drawing_id'] == 'AMB_1902_24_07_ASM_01']), 1)
        self.assertEqual(len([r for r in self.parts if
                              r['drawing_id'] == 'AMB_1902_24_07_PRT_23']), 1)

    def test_detail_lists_and_later_general_rows_survive(self):
        self.assertEqual(len([r for r in self.bom if
                              r['drawing_id'] == 'AMB_1902_24_07_PRT_04']), 1)
        # The same drawing is used by two different child assemblies.
        lateral = [r for r in self.bom if
                   r['drawing_id'] == 'AMB_1902_24_07_PRT_11']
        self.assertEqual({r['owner_assembly'] for r in lateral},
                         {'AMB_1902_24_07_ASM_03', 'AMB_1902_24_07_ASM_05'})
        self.assertFalse(any(r['description'].startswith('DIN 6921')
                             for r in self.bom))  # só aparece na revisão 02
        prateleira = [r for r in self.parts if
                      r['drawing_id'] == 'AMB_1902_24_07_PRT_23'][0]
        self.assertEqual(prateleira['quantity'], 4)
        cuts = [r for r in self.parts if
                r['drawing_id'].startswith('AMB_1902_24_07_PRT_23: corte')]
        self.assertEqual(sum(r['quantity'] for r in cuts), 28)

    def test_detail_weight_unit_is_validated_against_parent(self):
        # Page 31 is labelled Kg, yet 26372.11 equals the 26.37 kg ASM_02
        # parent only after conversion from grams. Page 62 already uses kg.
        base_sheet = next(r for r in self.bom if
                          r['drawing_id'] == 'AMB_1902_24_07_PRT_05')
        luminous = next(r for r in self.bom if
                        r['drawing_id'] == 'AMB_1902_24_07_PRT_11')
        self.assertAlmostEqual(base_sheet['unit_weight'], 4.01952, places=5)
        self.assertAlmostEqual(luminous['unit_weight'], 2.78, places=2)
        base_tube = next(r for r in self.bom if
                         r['drawing_id'] == 'AMB_1902_24_07_PRT_01')
        self.assertAlmostEqual(base_tube['unit_weight'], 9.68934, places=5)
        self.assertLess(sum(r.get('total_weight') or 0 for r in self.parts if
                            r['item_type'] == 'materia_prima'), 500)

    def test_detail_alias_rows_do_not_duplicate_physical_parts(self):
        self.assertFalse(any(r['drawing_id'] == 'Sheet' for r in self.parts))
        components = [r for r in self.parts if r['drawing_id'].startswith(
            'AMB_1902_24_07_PRT_14: componente')]
        self.assertEqual(len(components), 5)
        self.assertTrue(all('Estrutura prateleira central inf' in r['parent_assembly']
                            for r in components))
        self.assertTrue(any(r['drawing_id'] == 'AMB_1902_24_07_PRT_14'
                            and r['item_type'] == 'subconjunto' for r in self.parts))
        self.assertFalse(any(r['drawing_id'] == 'Tubo quadrado 25 x 25 x 1,06mm'
                             for r in self.parts))
        self.assertTrue(any(r['drawing_id'].startswith(
            'AMB_1902_24_07_PRT_04: corte') for r in self.parts))
        self.assertTrue(any(r['drawing_id'] == 'AMB_1902_24_07_PRT_05'
                            for r in self.parts))

    def test_wrapped_quantity_headers_and_assembly_ownership(self):
        for page in (20, 37, 53, 54, 68):
            self.assertTrue(any(r['page'] == page for r in self.bom), page)
        self.assertTrue(any(r['drawing_id'] == 'AMB_1902_24_07_PRT_12A'
                            for r in self.bom))
        testeira = [r for r in self.parts if
                    r['drawing_id'] == 'AMB_1902_24_07_PRT_35']
        self.assertEqual(len(testeira), 1)
        self.assertEqual(testeira[0]['quantity'], 2)
        self.assertIn('Conj Testeira', testeira[0]['parent_assembly'])

    def test_linear_diameter_parts_are_wire_cuts_not_bought_items(self):
        expected = {'PRT_25': (4, 585), 'PRT_26': (8, 643),
                    'PRT_32': (4, 776), 'PRT_33': (4, 595),
                    'PRT_20': (1, 1312), 'PRT_22': (1, 1307),
                    'PRT_21': (1, 1212)}
        for suffix, (qty, finished_length) in expected.items():
            item = next(r for r in self.parts if
                        r['drawing_id'] == 'AMB_1902_24_07_' + suffix)
            self.assertEqual(item['group_name'], 'Arame', suffix)
            self.assertEqual(item['item_type'], 'materia_prima', suffix)
            self.assertEqual(item['quantity'], qty, suffix)
            self.assertEqual(item['drawing_length'], finished_length, suffix)
            self.assertEqual(item['length'], finished_length + 20, suffix)
        self.assertFalse(any(r['drawing_id'].startswith('Arame ') for r in self.parts))


if __name__ == '__main__':
    unittest.main()
