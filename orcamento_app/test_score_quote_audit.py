"""A completed company quote is evidence, including repeated geometry."""

import unittest
from pathlib import Path

from score_quote_audit import read_calculo_total, compare_cuts


ROOT = Path(__file__).parent / 'data' / 'brahma_user_budget'
BOOKS = sorted(ROOT.glob('CÁLCULO+N.*.xls'))


@unittest.skipUnless(len(BOOKS) == 3, 'Orçamento BRAHMA copiado indisponível')
class ScoreQuoteAuditTest(unittest.TestCase):
    def test_same_sheet_size_in_two_workbooks_stays_two_source_rows(self):
        rows = read_calculo_total(BOOKS)
        same = [r for r in rows if r['kind'] == 'sheet' and
                (r['length'], r['width'], r['thickness']) == (2359, 159, .7)]
        self.assertEqual(len(same), 2)
        self.assertEqual(sum(r['quantity'] for r in same), 4)
        self.assertNotEqual(same[0]['source'], same[1]['source'])

    def test_audit_matches_confirmed_steel_without_merging_bought_psai(self):
        from reader_v3 import process_complete_project
        sample = Path(__file__).parent / 'data' / 'brahma_fixture'
        if not sample.is_dir():
            self.skipTest('PDF BRAHMA indisponível')
        project = process_complete_project(sample)
        differences = compare_cuts(read_calculo_total(BOOKS), project['materials'])
        extra = [d for d in differences if d['kind'] == 'sheet' and
                 d['length'] == 1250 and d['width'] == 520 and d['thickness'] == 3]
        self.assertEqual(extra, [])
        steel = next(x for x in project['materials']
                     if x['drawing_id']=='BRAHMA_ORCAMENTO_MANUAL: TAMPA TESTEIRA')
        bought = next(x for x in project['materials'] if x['description']=='FECHAMENTO SUPERIOR')
        self.assertEqual((steel['quantity'], steel['item_type']), (1, 'materia_prima'))
        self.assertEqual(bought['item_type'], 'comprado')


if __name__ == '__main__':
    unittest.main()
