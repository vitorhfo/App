"""The seven-column OUTPROMO BOM has material gauge plus stock sheet size."""
from pathlib import Path
import unittest

import pymupdf

from reader_v3 import (material_cell_spec, outpromo_bom,
                       outpromo_detail_dimensions, process_complete_project)


ROOT = Path(__file__).resolve().parents[2] / 'DADOS' / 'E03704167 - MPDV SAZONAL - CASH&CARRY'
SAMPLE = next((p for p in ROOT.rglob('*.pdf') if 'OP01' in p.name), None) if ROOT.exists() else None
CAN_BASE = next((p for p in ROOT.rglob('*.pdf') if 'OP03' in p.name), None) if ROOT.exists() else None


class MaterialCellSyntaxTest(unittest.TestCase):
    def test_stock_sheet_is_not_part_geometry(self):
        parsed=material_cell_spec('CHAPA DE AÇO 0,90 - 1200X3000','ESP. 0,9mm')
        self.assertEqual((parsed['thickness'],parsed['stock_length'],parsed['stock_width']),
                         (0.9,1200,3000))
        self.assertEqual((parsed['width'],parsed['depth']),(0,0))
        self.assertEqual(material_cell_spec('PSAI BRANCO 1,5 - 1250X2200')['thickness'],1.5)
        self.assertEqual(material_cell_spec('CHAPA DE PVC 0,5 - 1000X2000')['thickness'],0.5)

    def test_material_specific_syntax(self):
        wire=material_cell_spec('ARAME Ø4MM','Ø4mm')
        self.assertEqual(wire['diameter'],4)
        tube=material_cell_spec('TUBO 20X20X0,9','VER DET.')
        self.assertEqual((tube['width'],tube['depth'],tube['thickness']),(20,20,0.9))
        mixed=material_cell_spec('TUBO 20X20X0,9 / TUBO 40X20X0,9','VER DET.')
        self.assertEqual((mixed['width'],mixed['thickness']),(0,0))
        self.assertIn('Mais de um perfil',mixed['observation'])


@unittest.skipUnless(SAMPLE and SAMPLE.is_file(), 'PDF OUTPROMO não está neste computador')
class OutpromoPdfSyntaxTest(unittest.TestCase):
    def test_header_and_source_cells(self):
        with pymupdf.open(SAMPLE) as pdf:
            rows,heading=outpromo_bom(pdf[1].get_text())
        self.assertEqual(heading,'')
        self.assertEqual(len(rows),20)
        fundo=next(row for row in rows if row['description']=='FUNDO')
        self.assertEqual(fundo['quantity'],2)
        self.assertIn('0,90 - 1200X3000',fundo['material'])
        self.assertEqual(fundo['dimension_cell'],'ESP. 0,9mm')

    def test_import_expands_sides_and_preserves_stock_as_note(self):
        data=process_complete_project(SAMPLE.parent)
        fundo=next(item for item in data['materials'] if item['description']=='FUNDO')
        self.assertEqual((fundo['quantity'],fundo['thickness'],fundo['width'],fundo['length']),
                         (2,0.9,0,0))
        self.assertIn('1200',fundo['observation'])
        self.assertEqual(fundo['group_name'],'Chapa')
        pvc=next(item for item in data['materials'] if item['description']=='BOLSA PVC DA BANDEJA')
        self.assertEqual((pvc['group_name'],pvc['item_type'],pvc['thickness']),
                         ('Polímero/PSAI','comprado',0.5))
        lateral=next(item for item in data['materials']
                     if item['description'].startswith('CHAPA COMUNICA'))
        self.assertEqual(lateral['quantity'],2)
        self.assertIn('direito e esquerdo',lateral['observation'])


@unittest.skipUnless(CAN_BASE and CAN_BASE.is_file(), 'PDF CAN BASE não está neste computador')
class CanBaseDetailTest(unittest.TestCase):
    def test_named_psai_detail_has_cut_dimensions(self):
        with pymupdf.open(CAN_BASE) as pdf:
            details=outpromo_detail_dimensions(pdf[11].get_text())
        self.assertEqual({key:(value['length'],value['width'],value['printing'])
                          for key,value in details.items()},
                         {'COMUNICACAO SAIA MAIOR':(1345,249,'4x4'),
                          'COMUNICACAO SAIA MENOR':(1105,249,'4x4'),
                          'COMUNICACAO TESTEIRA':(645,274,'4x0'),
                          'COMUNICACAO LATERAL':(430,998,'4x4')})

    def test_import_keeps_raw_sheet_separate_from_cut_piece(self):
        data=process_complete_project(CAN_BASE.parent)
        by_name={item['description']:item for item in data['materials']}
        sheet=by_name['CHAPA SAIA FRONTAL']
        self.assertEqual((sheet['thickness'],sheet['length'],sheet['width']),(0.9,1350,250))
        self.assertIn('1200',sheet['observation'])
        self.assertIn('página 4',sheet['observation'])
        self.assertGreater(sheet['unit_weight'],0)
        psai=by_name['PSAI - SAIA FRONTAL E TRASEIRA']
        self.assertEqual((psai['length'],psai['width'],psai['thickness'],psai['printing']),
                         (1345,249,1.5,'4x4'))
        self.assertGreater(psai['unit_weight'],0)
        self.assertIn('página 12',psai['observation'])

    def test_metal_views_are_linked_without_using_envelope_as_cut(self):
        data=process_complete_project(CAN_BASE.parent)
        by_number={item['item_num']:item for item in data['materials']}
        self.assertTrue(all('Cotas de corte' in by_number[n]['observation'] or
                            'Cotas gerais do desenho' in by_number[n]['observation']
                            for n in range(1,19)))
        self.assertEqual((by_number[5]['length'],by_number[5]['width']),(1110,250))
        self.assertEqual((by_number[9]['length'],by_number[9]['width'],
                          by_number[9]['depth']),(1050,40,20))
        self.assertEqual((by_number[10]['length'],by_number[10]['width']), (800,25))
        self.assertEqual((by_number[16]['length'],by_number[16]['width']),(1000,435))
        self.assertEqual(by_number[7]['length'],0)
        self.assertIn('1530',by_number[7]['observation'])


if __name__=='__main__':
    unittest.main()
