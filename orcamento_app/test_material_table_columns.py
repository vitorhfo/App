"""Read CAD Lista de Materiais in its named column order."""

from pathlib import Path
import unittest

import pymupdf

from reader_v3 import technical_table_bom, process_complete_project, table_diameter


PDF = (Path(__file__).resolve().parents[2] / 'DADOS' / 'JOSÉ VITOR' /
       'TESTES DE ORÇAMENTO' / 'ALPARGATAS' / 'ALPA BASICO 5x5' /
       'PROJETO' / 'ALP0155M01_GERAL_BASICO 5x5.pdf')


@unittest.skipUnless(PDF.is_file(), 'PDF ALPA não está neste computador')
class MaterialTableColumnsTest(unittest.TestCase):
    def test_radius_and_diameter_markers(self):
        self.assertEqual(table_diameter('R4'),(8,True))
        self.assertEqual(table_diameter('RAIO 2,5 mm'),(5,True))
        self.assertEqual(table_diameter('Ø5'),(5,False))
        self.assertEqual(table_diameter('6'),(6,False))

    def test_exact_columns_preserve_blanks_code_and_observation(self):
        with pymupdf.open(PDF) as pdf:
            rows=technical_table_bom(pdf[1].get_text(),pdf[1])
        self.assertEqual(len(rows),14)
        by_number={row['item_num']:row for row in rows}
        self.assertEqual((by_number[3]['description'],by_number[3]['quantity'],
                          by_number[3]['drawing_id']),
                         ('SM BARRA DE GANCHOS',5,'ALP0155M04'))
        self.assertEqual((by_number[5]['thickness'],by_number[5]['diameter'],
                          by_number[5]['width'],by_number[5]['depth'],
                          by_number[5]['length']), (0.9,0,70,22.5,0))
        self.assertEqual(by_number[5]['drawing_id'],'ALP0155P18')
        self.assertEqual(by_number[5]['unit_weight'],0.01)
        self.assertEqual(by_number[5]['observation'],'IMPRESSÃO FRENTE')
        self.assertEqual((by_number[9]['raw_code'],by_number[9]['drawing_id'],
                          by_number[9]['width'],by_number[9]['depth']),
                         ('21204015','ALP0155P14',25,25))

    def test_import_keeps_source_measure_and_uses_planar_measure_for_quote(self):
        data=process_complete_project(PDF.parent)
        tag=next(item for item in data['materials']
                 if item['description']=='CHAPA TAG PARA QR CODE')
        self.assertEqual((tag['width'],tag['depth'],tag['length']),(70,22.5,22.5))
        self.assertIn('Profundidade',tag['observation'])
        bought=next(item for item in data['materials']
                    if item['description'].startswith('PONTEIRA INTERNA'))
        self.assertEqual(bought['raw_code'],'21204015')
        self.assertEqual(bought['drawing_id'],'ALP0155P14')
        pezinhos=[item for item in data['materials']
                  if item['description']=='TUBO PEZINHOS']
        self.assertEqual([(item['quantity'],bool(item['mirrored_assembly']))
                          for item in pezinhos],[(2,True)])


if __name__=='__main__':
    unittest.main()
