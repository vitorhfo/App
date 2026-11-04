"""Cut allowance must affect material use, not the finished CAD mass."""

from pathlib import Path
import unittest
from unittest.mock import patch

import pymupdf

from comparator import analyze_weights
from reader_v3 import empty_item, parameterized_details, title_weight
from wire_allowance import apply_wire_allowance, mass_per_mm


ROOT=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'ILHA CASH RECKITT'/
      'PROJETO'/'CORPO Ilha Cash RECKITT')


class WireAllowanceTest(unittest.TestCase):
    def test_cut_length_and_pdf_weight_are_distinct(self):
        item=empty_item('ARAME APARADOR',3,'p.pdf#page=1','Arame',
                        length=40,radius_diam=5,unit_weight=0.006205,
                        total_weight=0.018615,item_type='materia_prima')
        self.assertTrue(apply_wire_allowance(item))
        self.assertFalse(apply_wire_allowance(item))
        self.assertEqual((item['drawing_length'],item['length']),(40,60))
        self.assertAlmostEqual(item['unit_weight'],0.006205+20*mass_per_mm(5),places=6)
        result=analyze_weights([item],nominal_pdf_weight=item['finished_total_weight'])
        self.assertEqual(result['status_pdf_compare'],'OK')
        self.assertGreater(result['total_cut_weight'],result['total_product_weight'])

    def test_unknown_mass_is_an_incomplete_comparison(self):
        item=empty_item('RODÍZIO',4,'p.pdf#page=1','Ferragens',
                        item_type='comprado')
        result=analyze_weights([item],nominal_pdf_weight=1)
        self.assertEqual(result['status_pdf_compare'],'INCOMPLETO')
        self.assertEqual(result['missing_weight_count'],1)

    def test_length_inferred_from_mass_requires_review(self):
        item=empty_item('ARCO DE ARAME',1,'p.pdf#page=1','Arame',
                        radius_diam=5,unit_weight=0.3,item_type='materia_prima')
        self.assertTrue(apply_wire_allowance(item))
        self.assertGreater(item['length'],item['drawing_length'])
        self.assertIn('confirmar no desenho',item['pending_issue'])

    def test_manual_wire_edit_does_not_add_allowance_twice(self):
        from app import create_project,create_material,update_material,ProjectCreate,MaterialCreate,MaterialUpdate
        from database import init_db,get_connection
        test_root=Path(__file__).resolve().parent/'data'/'test_runs'
        test_root.mkdir(exist_ok=True)
        with patch('database.DB_PATH',str(test_root/'wire_allowance_test.db')):
            init_db()
            project_id=create_project(ProjectCreate(name='Arame de teste'))['id']
            item_id=create_material(project_id,MaterialCreate(
                description='ARAME TESTE',group_name='Arame',item_type='materia_prima',
                radius_diam=5,length=40,quantity=2))['id']
            conn=get_connection()
            first=dict(conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone())
            conn.close()
            self.assertEqual((first['drawing_length'],first['length']),(40,60))
            update_material(project_id,item_id,MaterialUpdate(quantity=3))
            conn=get_connection()
            second=dict(conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone())
            conn.close()
            self.assertEqual((second['drawing_length'],second['length']),(40,60))
            self.assertAlmostEqual(second['finished_total_weight'],
                                   second['finished_unit_weight']*3,places=4)
            update_material(project_id,item_id,MaterialUpdate(length=100))
            conn=get_connection()
            revised=dict(conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone())
            conn.close()
            self.assertEqual((revised['drawing_length'],revised['length']),(80,100))

    @unittest.skipUnless(ROOT.is_dir(),'Desenhos RECKITT indisponíveis')
    def test_parameterized_metal_and_decimal_drawing_scale(self):
        with pymupdf.open(ROOT/'TRAVESSA CORPO Ilha Cash RECKITT.PDF') as pdf:
            detail=parameterized_details(pdf[0].get_text(),
                'TRAVESSA CORPO Ilha Cash RECKITT - 660')
        self.assertEqual((detail['length'],detail['width'],detail['depth'],detail['thickness']),
                         (660,20,20,0.9))
        self.assertGreater(detail['unit_weight'],0.3)
        drawing=ROOT.parent/'BATEDOR Ilha Cash RECKITT'/'CH BATEDOR Ilha Cash RECKITT.PDF'
        if drawing.is_file():
            with pymupdf.open(drawing) as pdf:
                self.assertAlmostEqual(title_weight(pdf[0].get_text()),0.119176)


if __name__=='__main__':
    unittest.main()
