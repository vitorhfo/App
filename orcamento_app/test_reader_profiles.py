"""Neighboring PDF layouts must not claim each other's columns or lose rows."""
from pathlib import Path
import unittest

import pymupdf

from reader_profiles.cad import cad_bom
from reader_profiles.outpromo import outpromo_bom
from reader_profiles.router import read_technical_table, technical_table_bom
from test_rise_drawing_first_bom import drawn_table


class ReaderProfileTests(unittest.TestCase):
    def test_ordered_grid_wins_without_becoming_a_compact_cut_or_cad_list(self):
        doc, page = drawn_table()
        try:
            text = page.get_text()
            result = read_technical_table(text, page)
            self.assertEqual(result.profile, 'technical_ordered_grid')
            self.assertEqual([(r['quantity'], r['drawing_id']) for r in result.rows],
                             [(2, 'RDS007M02-01'), (4, 'RDS007P10-01'),
                              (8, 'COMPRADO: Presilha Canoa Preta')])
            self.assertEqual(len(result.sections), 1)
            self.assertEqual(technical_table_bom(text, page), result.rows)
            self.assertEqual(cad_bom(text), [])
            self.assertEqual(cad_bom(text,page), [])
            self.assertEqual(outpromo_bom(text)[0], [])
        finally:
            doc.close()

    def test_generic_column_words_do_not_select_a_reader(self):
        doc = pymupdf.open()
        try:
            page = doc.new_page()
            page.insert_text((30, 40), 'ITEM MATERIAL QTD COMPRIMENTO\nSem lista de pecas')
            result = read_technical_table(page.get_text(), page)
            self.assertEqual(result.profile, 'unrecognized')
            self.assertEqual(result.rows, [])
        finally:
            doc.close()

    def test_cad_still_reads_its_own_header_with_drawing_codes(self):
        text = 'Nº\nDESCRIÇÃO\nCODIGO\nQTD\n1\nARAME GANCHO\nPC00000123\n30\nPESO LIQ'
        self.assertEqual(cad_bom(text), [dict(item_num=1, description='ARAME GANCHO',
                                            raw_code='PC00000123', quantity=30)])
        self.assertEqual(read_technical_table(text).rows, [])

    def test_real_alpa_grid_keeps_blank_columns_and_does_not_claim_compact_format(self):
        root = Path(__file__).resolve().parents[2] / 'DADOS'
        sample = next(root.glob('JOS*/TESTES*/ALPARGATAS/ALPA BASICO 5x5/PROJETO/ALP0155*.pdf'))
        with pymupdf.open(sample) as doc:
            result = read_technical_table(doc[1].get_text(), doc[1])
        self.assertEqual(result.profile, 'technical_14_grid')
        self.assertEqual(len(result.rows), 14)
        tag = next(r for r in result.rows if r['item_num'] == 5)
        self.assertEqual((tag['drawing_id'], tag['thickness'], tag['width'], tag['depth'], tag['length']),
                         ('ALP0155P18', .9, 70, 22.5, 0))


if __name__ == '__main__':
    unittest.main()
