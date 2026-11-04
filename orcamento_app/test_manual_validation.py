"""Manual tube edits must be consistent with geometry and the linked PDF."""

from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from mass_math import calculated_weight, strip_weight_note
from manual_validation import linked_drawing


RECKITT=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'ILHA CASH RECKITT'/
         'PROJETO'/'CORPO Ilha Cash RECKITT')
PALLET_SIDE_SOURCE=(Path(__file__).resolve().parent/'data'/'uploads'/'proj_113' /
                    '2fcf05a21bcf403688a1689794a89f85'/'source')


@unittest.skipUnless((PALLET_SIDE_SOURCE/'PROJETO'/'ABA SUP. Pallet Side.PDF').is_file(),
                     'PDF real Pallet Side indisponível')
class LinkedDrawingPageLifetimeTest(unittest.TestCase):
    def test_drawing_details_are_read_before_pdf_is_closed(self):
        conn=sqlite3.connect(':memory:')
        conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE projects (id INTEGER, folder_path TEXT)')
        conn.execute('INSERT INTO projects VALUES (?,?)',(113,str(PALLET_SIDE_SOURCE)))
        item={'project_id':113,'source_page':'PROJETO/ABA SUP. Pallet Side.PDF#page=1',
              'drawing_id':'ABA SUP. Pallet Side',
              'description':'ABA SUP. Pallet Side'}

        def read_live_page(text,cut_rows=None,page=None):
            return {'page_text':page.get_text('text')}

        with patch('manual_validation.parameterized_details',return_value=None), \
                patch('manual_validation.details',side_effect=read_live_page):
            result=linked_drawing(conn,item)

        conn.close()
        self.assertIsInstance(result,dict)
        self.assertTrue(result['page_text'])


@unittest.skipUnless(RECKITT.is_dir(),'Desenho RECKITT indisponível')
class ManualValidationTest(unittest.TestCase):
    def setUp(self):
        from app import create_project,create_material,ProjectCreate,MaterialCreate
        from database import init_db,get_connection
        root=Path(__file__).resolve().parent/'data'/'test_runs'
        root.mkdir(exist_ok=True)
        self.db_patch=patch('database.DB_PATH',str(root/'manual_validation_test.db'))
        self.db_patch.start()
        init_db()
        self.project_id=create_project(ProjectCreate(
            name='Teste de edição de tubo',folder_path=str(RECKITT)))['id']
        self.item_id=create_material(self.project_id,MaterialCreate(
            description='POSTE Ilha Cash RECKITT',group_name='Tubo Quadrado/Retangular',
            item_type='materia_prima',material='TUBO IND. RET 50x30x2mm',
            width=50,depth=30,thickness=2,length=1500,quantity=2))['id']
        conn=get_connection()
        conn.execute('''UPDATE materials SET source_page=?,drawing_id=?,unit_weight=?,
            total_weight=?,observation=? WHERE id=?''',
            ('POSTE Ilha Cash RECKITT.PDF#page=1','POSTE Ilha Cash RECKITT',
             3.5796,7.1592,
             'Conferência de peso: cálculo bruto 3579.600 g; folha 3446.567 g; adotado 3579.600 g por peça.',
             self.item_id))
        conn.commit();conn.close()

    def tearDown(self):
        self.db_patch.stop()

    def update(self,**fields):
        from app import update_material,MaterialUpdate
        return update_material(self.project_id,self.item_id,MaterialUpdate(**fields))

    def test_profile_text_edit_updates_dimensions_and_keeps_pdf_floor(self):
        result=self.update(material='TUBO IND. QUAD 20x20x0,9mm',
                           width=50,depth=30,thickness=2,unit_weight=3.5796)
        item=result['material']; check=result['validation']
        self.assertEqual((item['width'],item['depth'],item['thickness']),(20,20,0.9))
        self.assertEqual(item['unit_weight'],3.446567)
        self.assertGreaterEqual(item['unit_weight'],check['pdf_weight'])
        self.assertGreaterEqual(item['unit_weight'],calculated_weight(item))
        self.assertIn('Medidas manuais diferentes do PDF',item['observation'])
        self.assertEqual(item['observation'].count('Conferência de peso:'),1)

    def test_length_edit_recalculates_and_checks_original_pdf(self):
        result=self.update(length=1000,unit_weight=3.5796)
        item=result['material']; check=result['validation']
        self.assertEqual(item['unit_weight'],3.446567)
        self.assertEqual(check['pdf_weight'],3.446567)
        self.assertIn('comprimento 1500→1000 mm',check['drawing_difference'])
        self.assertEqual(item['total_weight'],6.893134)

    def test_weight_below_minimum_is_adjusted_and_high_weight_is_kept(self):
        low=self.update(unit_weight=0.1)
        self.assertTrue(low['validation']['adjusted'])
        self.assertEqual(low['material']['unit_weight'],3.5796)
        high=self.update(unit_weight=4)
        self.assertFalse(high['validation']['adjusted'])
        self.assertEqual(high['material']['unit_weight'],4)
        self.assertEqual(high['material']['total_weight'],8)
        self.assertIn('folha 3446.567 g; adotado 4000.000 g',
                      high['material']['observation'])

    def test_conflicting_profile_and_fields_are_rejected(self):
        with self.assertRaises(HTTPException) as caught:
            self.update(material='TUBO IND 20x20x0,9mm',width=25,depth=20,thickness=0.9)
        self.assertEqual(caught.exception.status_code,400)
        from database import get_connection
        conn=get_connection()
        row=conn.execute('SELECT width,depth,thickness FROM materials WHERE id=?',
                         (self.item_id,)).fetchone()
        conn.close()
        self.assertEqual(tuple(row),(50,30,2))

    def test_quantity_edit_keeps_validated_unit_weight(self):
        result=self.update(quantity=3,unit_weight=3.5796)
        self.assertIsNone(result['validation'])
        self.assertEqual(result['material']['unit_weight'],3.5796)
        self.assertEqual(result['material']['total_weight'],10.7388)

    def test_numeric_profile_edit_rewrites_material_text(self):
        result=self.update(width=40)
        item=result['material']
        self.assertIn('40x30x2mm',item['material'])
        self.assertEqual(item['width'],40)
        self.assertEqual(item['unit_weight'],3.446567)
        self.assertIn('largura 50→40 mm',result['validation']['drawing_difference'])

    def test_round_profile_can_be_validated_manually(self):
        from manual_validation import synchronize_tube_profile
        before={'group_name':'Tubo Redondo','material':'TUBO RED Ø30x1,2mm',
                'radius_diam':30,'thickness':1.2}
        edited={**before,'material':'TUBO RED Ø40x1,5mm'}
        self.assertIsNone(synchronize_tube_profile(edited,before))
        self.assertEqual((edited['radius_diam'],edited['thickness']),(40,1.5))

    def test_user_note_survives_comparison_replacement(self):
        note=('Revisar acabamento. Tubo retangular 50x30x2 mm; comprimento 1500 mm. '
              'Conferência de peso: cálculo bruto 3579.600 g; folha 3446.567 g; '
              'adotado 3579.600 g por peça.')
        self.assertEqual(strip_weight_note(note),'Revisar acabamento.')


if __name__=='__main__':
    unittest.main()
