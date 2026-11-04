"""SCORE drawing packages: nested BOM, separate tube cuts, and safe envelopes."""

import unittest
import sqlite3
from pathlib import Path

import pymupdf

from reader_v3 import process_complete_project
from pricing import metal_price_basis
from score_package import read_score_package
from mass_math import calculated_weight


SAMPLE = Path(__file__).resolve().parent / 'data' / 'brahma_fixture' / 'AMB_2239_25_BRAHMA_ILHA.pdf'


@unittest.skipUnless(SAMPLE.is_file(), 'Amostra SCORE BRAHMA indisponível')
class ScorePackageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = process_complete_project(SAMPLE.parent)

    def test_bom_expands_assemblies_across_last_two_pages(self):
        parts = self.project['materials']
        physical = [item for item in parts if item['item_type'] != 'subconjunto']
        self.assertGreaterEqual(len(physical), 50)
        shelf = next(item for item in parts if item['description'] == 'PRATELEIRA'
                     and item['item_type'] == 'subconjunto')
        self.assertEqual(shelf['quantity'], 4)
        precifier = next(item for item in physical if 'Precifica' in item['description'])
        self.assertEqual(precifier['quantity'], 12)
        self.assertIn('PRATELEIRA', precifier['parent_assembly'])
        self.assertAlmostEqual(self.project['nominal_weight_pdf'], 151.51)

    def test_cut_table_is_separate_and_envelope_does_not_become_cut(self):
        physical = [item for item in self.project['materials']
                    if item['item_type'] != 'subconjunto']
        cuts = [item for item in physical
                if item['drawing_id'].startswith('AMB_2239_25_03_PRT_16: corte')]
        self.assertEqual(len(cuts), 7)
        self.assertEqual([item['quantity'] for item in cuts if item['length'] == 251], [8])
        self.assertTrue(all(item['width'] == 40 and item['depth'] == 20 and
                            item['thickness'] == 1.06 for item in cuts))
        self.assertFalse(any(item['description'] == 'ESTRUTURA PRATELEIRA'
                             for item in physical))
        batedor = next(item for item in physical if item['description'] == 'BATEDOR')
        self.assertEqual(batedor['length'], 0)
        self.assertIn('comprimento', batedor['pending_issue'].lower())
        aparador = next(item for item in physical if item['description'] == 'APARADOR')
        self.assertEqual(aparador['radius_diam'], 5)
        self.assertEqual(aparador['length'], 0)

    def test_sheet_and_bought_parts_keep_their_materials(self):
        physical = [item for item in self.project['materials']
                    if item['item_type'] != 'subconjunto']
        front = next(item for item in physical if item['description'] == 'LOGO BRAHMA FRONTAL')
        self.assertEqual((front['group_name'], front['item_type'], front['quantity']),
                         ('Polímero/PSAI', 'comprado', 2))
        sheet = next(item for item in physical
                     if item['description'] == 'FECHAMENTO FRONTAL/TRASEIRO')
        self.assertEqual((sheet['length'], sheet['width'], sheet['thickness']),
                         (2359, 159, .7))
        self.assertEqual(sheet['quantity'], 2)
        support = [item for item in physical
                   if item['drawing_id'].startswith('AMB_2239_25_03_PRT_12: componente')]
        self.assertEqual(len(support), 2)
        sheet = next(item for item in support if 'chapa' in item['drawing_id'])
        flat = next(item for item in support if 'ferro chato' in item['drawing_id'])
        self.assertEqual((sheet['quantity'], sheet['length'], sheet['width'], sheet['thickness']),
                         (2, 748, 400, 1.5))
        self.assertEqual((flat['quantity'], flat['length'], flat['width'], flat['thickness']),
                         (2, 394, 20, 2))
        self.assertNotEqual(sheet['drawing_id'], flat['drawing_id'])
        upper = next(item for item in physical
                     if item['description'] == 'FECHAMENTO SUPERIOR BASE')
        self.assertIn('Peso bruto', upper['pending_issue'])
        consumption = sum(x['total_weight'] for x in physical)
        self.assertGreater(consumption, self.project['nominal_weight_pdf'])
        self.assertLess(consumption, 180)  # Acrylic must not be counted as steel.
        self.assertTrue(any(x['title']=='Pacote SCORE preliminar'
                            for x in self.project['pending_decisions']))

    def test_corrupted_acrylic_label_uses_polymer_density_not_steel(self):
        physical = [item for item in self.project['materials']
                    if item['item_type'] != 'subconjunto']
        logo = next(item for item in physical
                    if item['description'] == 'LOGO BRAHMA FRONTAL')
        self.assertEqual(logo['quantity'], 2)
        self.assertGreater(calculated_weight(logo), .7)
        self.assertLess(calculated_weight(logo), 1.0)
        self.assertLess(logo['unit_weight'], 1.0)
        steel = {**logo, 'group_name': 'Chapa', 'material': 'Chapa de aço'}
        self.assertGreater(calculated_weight(steel), 5)

    def test_user_confirmed_same_size_parts_keep_distinct_identity(self):
        physical = [item for item in self.project['materials']
                    if item['item_type'] != 'subconjunto']
        side_pairs = [item for item in physical
                      if (item['length'], item['width'], item['thickness']) ==
                         (2359, 159, .7)]
        self.assertEqual(len(side_pairs), 2)
        self.assertEqual(sum(item['quantity'] for item in side_pairs), 4)
        self.assertNotEqual(side_pairs[0]['drawing_id'], side_pairs[1]['drawing_id'])
        steel_top = next(item for item in physical
                         if item['drawing_id']=='BRAHMA_ORCAMENTO_MANUAL: TAMPA TESTEIRA')
        bought_top = next(item for item in physical
                          if item['description']=='FECHAMENTO SUPERIOR')
        self.assertEqual((steel_top['item_type'], bought_top['item_type']),
                         ('materia_prima', 'comprado'))
        self.assertEqual((steel_top['length'], steel_top['width'], steel_top['thickness']),
                         (1250, 520, 3))

    def test_quote_explains_reinforcement_tube_and_two_plates_per_part(self):
        physical = [item for item in self.project['materials']
                    if item['item_type'] != 'subconjunto']
        for code, tube_length in (('PRT_21', 417), ('PRT_22', 317)):
            components = [item for item in physical
                          if code in item['drawing_id'] and 'componente' in item['drawing_id']]
            self.assertEqual(len(components), 3)
            tube = next(item for item in components
                        if item['group_name']=='Tubo Quadrado/Retangular')
            self.assertEqual((tube['length'], tube['width'], tube['depth'],
                              tube['thickness'], tube['quantity']),
                             (tube_length, 25, 25, 1.2, 4))
            plates = {(item['length'], item['width'], item['thickness'], item['quantity'])
                      for item in components if item['group_name']=='Chapa'}
            self.assertEqual(plates, {(150, 60, 1, 4), (90, 60, 1, 4)})

    def test_sheet_row_in_testeira_cut_table_gets_its_own_drawing_dimensions(self):
        sheet = next(item for item in self.project['materials']
                     if item['drawing_id']=='AMB_2239_25_03_PRT_06: corte 3')
        self.assertEqual((sheet['quantity'], sheet['length'], sheet['width'],
                          sheet['thickness']), (2, 80, 50, 3))
        self.assertEqual(sheet['group_name'], 'Chapa')

    def test_brahma_50x30_uses_106_wall_for_mass_and_2mm_catalog_for_rate(self):
        tube = next(item for item in self.project['materials']
                    if item['group_name'] == 'Tubo Quadrado/Retangular'
                    and (item['width'], item['depth'], item['thickness']) == (50, 30, 1.06)
                    and item['length'] == 99)
        thicker = {**tube, 'thickness': 2.0}
        self.assertLess(calculated_weight(tube), calculated_weight(thicker))
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('''CREATE TABLE catalog_prices (
                id INTEGER PRIMARY KEY, description TEXT, normalized TEXT, value REAL,
                unit TEXT, source TEXT, approved INTEGER)''')
            conn.executemany('INSERT INTO catalog_prices VALUES (?,?,?,?,?,?,?)', [
                (1, 'TUBO RETANGULAR 50X30X2,0MM', '', 11.3, 'kg', 'Comprados / Tubos', 1),
                (2, 'TUBO RETANGULAR 50X30X2,65MM', '', 12.2, 'kg', 'Comprados / Tubos', 1),
            ])
            basis = metal_price_basis(tube, {
                'mp_tubo_acrescimo_ipi': 3.25,
                'mp_tubo_fator_liquido': 78.75,
            }, conn)
            self.assertEqual((basis['rate'], basis['thickness_used']), (11.3, 2.0))
            self.assertEqual(basis['weight'], tube['unit_weight'])
            self.assertIn('esp 1.06→2 mm', basis['source'])
        finally:
            conn.close()

    def test_solidworks_family_is_not_read_as_score(self):
        other = (Path(__file__).resolve().parents[2] / 'DADOS' / 'JOSÉ VITOR' /
                 'TESTES DE ORÇAMENTO' / 'FLAVIO PAPILE' /
                 'DISPLAY BALCÃO TROPERO ALIMENTOS' / 'PROJETO' /
                 'CANALETA Display Balcao TROPERO ALIM.PDF')
        with pymupdf.open(other) as pdf:
            bom, cuts = read_score_package(pdf)
        self.assertEqual((bom, cuts), ([], {}))

    def test_missing_wire_cut_is_not_priced_from_stamped_weight(self):
        parts = self.project['materials']
        wire = next(x for x in parts if x['description']=='APARADOR')
        sheet_cut = next(x for x in parts
                         if x['drawing_id']=='AMB_2239_25_03_PRT_06: corte 3')
        known_sheet = next(x for x in parts
                           if x['description']=='FECHAMENTO FRONTAL/TRASEIRO')
        rules = {'mp_arame':6.34, 'mp_arame_fator_liquido':78.75,
                 'mp_chapa_aco':7.02}
        self.assertIsNone(metal_price_basis(wire,rules,None))
        self.assertIsNotNone(metal_price_basis(sheet_cut,rules,None))
        self.assertIsNotNone(metal_price_basis(known_sheet,rules,None))
        flat = next(x for x in parts if x['drawing_id'].endswith(': componente ferro chato'))
        self.assertIsNone(metal_price_basis(flat,rules,None))


if __name__ == '__main__':
    unittest.main()
