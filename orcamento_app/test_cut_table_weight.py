"""Part cut tables and conservative drawing-weight reconciliation."""

from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import pymupdf

from mass_math import calculated_weight, reconcile_item_weight
from reader_v3 import (cut_table_rows, details, empty_item, material_cell_spec,
                       process_complete_project)


ROOT=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'JOSÉ VITOR'/
      'TESTES DE ORÇAMENTO'/'TAMBASA'/'DISPLAY DE CHAO TAMBASA'/'PROJETO')
RECKITT=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'ILHA CASH RECKITT'/
         'PROJETO'/'CORPO Ilha Cash RECKITT')
MOVEL=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'JOSÉ VITOR'/
       'TESTES DE ORÇAMENTO'/'FLAVIO PAPILE'/'MOVEL PONTA ATACADÃO')
TROPERO=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'JOSÉ VITOR'/
         'TESTES DE ORÇAMENTO'/'FLAVIO PAPILE'/'DISPLAY BALCÃO TROPERO ALIMENTOS')
JUNGLE=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'JOSÉ VITOR'/
        'TESTES DE ORÇAMENTO'/'FLAVIO PAPILE'/'DISPLAY DE CHÃO JUNGLE')


class CutTableWeightTest(unittest.TestCase):
    @unittest.skipUnless(MOVEL.is_dir(),'Desenho MOVEL PONTA indisponível')
    def test_parameterized_cut_table_keeps_rows_after_variable_length(self):
        front=next(MOVEL.rglob('QUADRO FR. TEST. MOVEL PONTA ATACADAO.PDF'))
        rear=next(MOVEL.rglob('QUADRO TRAS. TEST. MOVEL PONTA ATACADAO.PDF'))
        with pymupdf.open(front) as pdf:
            front_rows=cut_table_rows(pdf[0].get_text(),pdf[0])
        with pymupdf.open(rear) as pdf:
            rear_rows=cut_table_rows(pdf[0].get_text(),pdf[0])
        self.assertEqual([(r['item_num'],r['length'],r['quantity']) for r in front_rows],
                         [(1,233,3),(2,0,1),(3,1710,1)])
        self.assertEqual([(r['item_num'],r['length'],r['quantity']) for r in rear_rows],
                         [(1,215,3),(2,0,1),(3,350,2),(4,1710,2),(5,0,1),(6,1710,1)])
        project=process_complete_project(MOVEL)
        front_parts=[item for item in project['materials']
                     if 'QUADRO FR. TEST.' in item['drawing_id'] and ': corte ' in item['drawing_id']]
        rear_parts=[item for item in project['materials']
                    if 'QUADRO TRAS. TEST.' in item['drawing_id'] and ': corte ' in item['drawing_id']]
        self.assertEqual((len(front_parts),len(rear_parts)),(3,6))
        self.assertTrue(all(item['pending_issue'] for item in front_parts+rear_parts
                            if item['length']==0))

    def test_saved_fractional_tubes_match_their_part_drawings(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file():
            self.skipTest('Banco salvo indisponível')
        expected={719:(120,15.875,0.9),721:(855,19.05,1.2),
                  724:(70,22.225,1.2),728:(300,19.05,1.2),
                  988:(150,22.2,1.2)}
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            for item_id,profile in expected.items():
                with self.subTest(item_id=item_id):
                    row=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
                    self.assertIsNotNone(row)
                    self.assertEqual(row['group_name'],'Tubo Redondo')
                    self.assertAlmostEqual(row['length'],profile[0],places=2)
                    self.assertAlmostEqual(row['radius_diam'],profile[1],delta=0.05)
                    self.assertAlmostEqual(row['thickness'],profile[2],places=2)
                    self.assertGreaterEqual(row['unit_weight']+1e-6,calculated_weight(dict(row)))
            cleaned=conn.execute('SELECT material FROM materials WHERE id=988').fetchone()[0]
            self.assertNotIn('mm/8"',cleaned)

    def test_saved_projects_have_each_cut_table_row_as_a_separate_item(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file():
            self.skipTest('Banco salvo indisponível')
        expected={11:{706:2,707:2,712:2,713:2,716:4,723:2,732:3},
                  15:{847:2},17:{994:2,996:2,999:2,1004:2},18:{1030:3}}
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            for project_id,items in expected.items():
                for item_id,count in items.items():
                    with self.subTest(project_id=project_id,item_id=item_id):
                        original=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
                        self.assertIsNotNone(original)
                        self.assertEqual(original['project_id'],project_id)
                        rows=conn.execute('''SELECT * FROM materials WHERE project_id=?
                            AND parent_assembly=? AND drawing_id LIKE ? ORDER BY drawing_id''',
                            (project_id,original['parent_assembly'],
                             original['drawing_id'].split(': corte ')[0]+': corte %')).fetchall()
                        self.assertEqual(len(rows),count)
                        self.assertEqual({row['drawing_id'].rsplit(': corte ',1)[1] for row in rows},
                                         {str(index) for index in range(1,count+1)})
                        self.assertTrue(all(row['unit_weight']>0 and row['quantity']>0 for row in rows))
                        if item_id==1030:
                            self.assertEqual(rows[2]['group_name'],'Chapa')
                            self.assertEqual(rows[2]['item_type'],'materia_prima')

    @unittest.skipUnless(TROPERO.is_dir(),'Desenhos TROPERO indisponíveis')
    def test_fractional_inch_round_tube_uses_diameter_and_weight_checked_length(self):
        poste=next(TROPERO.rglob('TB. POSTE Display Balcao TROPERO ALIM.PDF'))
        with pymupdf.open(poste) as pdf:
            found=details(pdf[0].get_text())
        self.assertAlmostEqual(found['diameter'],19.05,places=2)
        self.assertEqual(found['thickness'],1.2)
        self.assertEqual(found['length'],855)
        mass=calculated_weight({'group_name':'Tubo Redondo','material':found['material'],
                                'length':found['length'],'radius_diam':found['diameter'],
                                'thickness':found['thickness']})
        self.assertLess(abs(mass-found['unit_weight'])/found['unit_weight'],0.03)
        test=next(TROPERO.rglob('TB. TEST. Display Balcao TROPERO ALIM.PDF'))
        with pymupdf.open(test) as pdf:
            other=details(pdf[0].get_text())
        self.assertAlmostEqual(other['diameter'],19.05,places=2)
        self.assertEqual((other['length'],other['thickness']),(300,1.2))

    @unittest.skipUnless(JUNGLE.is_dir(),'Desenhos JUNGLE indisponíveis')
    def test_flat_iron_is_raw_metal_and_third_cut_keeps_its_own_weight(self):
        self.assertEqual((material_cell_spec('FERRO LAMINADO 1-2\'\' X 1-8\'\'')['width'],
                          material_cell_spec('FERRO LAMINADO 1-2\'\' X 1-8\'\'')['thickness']),
                         (12.7,3.175))
        project=process_complete_project(JUNGLE)
        cuts=[item for item in project['materials'] if 'TB. TEST.' in item['drawing_id']
              and ': corte ' in item['drawing_id']]
        self.assertEqual(len(cuts),3)
        self.assertEqual([item['quantity'] for item in cuts],[1,1,1])
        self.assertEqual((cuts[2]['group_name'],cuts[2]['item_type'],cuts[2]['length'],
                          cuts[2]['width'],cuts[2]['thickness']),
                         ('Chapa','materia_prima',290,12.7,3.175))
        self.assertGreaterEqual(sum(item['total_weight'] for item in cuts),0.493826)

    @unittest.skipUnless(MOVEL.is_dir(),'Desenho MOVEL PONTA indisponível')
    def test_mixed_wire_and_tube_cut_table_becomes_three_pieces(self):
        path=next(MOVEL.rglob('*140803.PDF'))
        with pymupdf.open(path) as pdf:
            rows=cut_table_rows(pdf[0].get_text(),pdf[0])
        self.assertEqual([(r['quantity'],r['length']) for r in rows],
                         [(3,556.667),(2,730),(1,4948.496)])
        project=process_complete_project(MOVEL)
        pieces=[x for x in project['materials'] if '140803' in x['drawing_id']]
        self.assertEqual(len(pieces),3)
        self.assertEqual([(x['group_name'],x['quantity']) for x in pieces],
                         [('Arame',3),('Tubo Quadrado/Retangular',2),
                          ('Tubo Quadrado/Retangular',1)])
        self.assertEqual(pieces[0]['length'],576.667)
        self.assertEqual([(x['width'],x['depth'],x['thickness']) for x in pieces[1:]],
                         [(20,20,0.9),(20,20,0.9)])
        self.assertGreaterEqual(sum(x['total_weight'] for x in pieces),3.750834)
        from manual_validation import linked_drawing
        conn=sqlite3.connect(':memory:')
        conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE projects(id INTEGER,folder_path TEXT)')
        conn.execute('INSERT INTO projects VALUES (?,?)',(16,str(MOVEL)))
        try:
            drawings=[linked_drawing(conn,{**item,'project_id':16}) for item in pieces]
        finally:
            conn.close()
        self.assertEqual([drawing['length'] for drawing in drawings],
                         [556.667,730,4948.496])
        self.assertEqual([drawing['diameter'] for drawing in drawings],[6,0,0])
        self.assertLess(max(drawing['unit_weight'] for drawing in drawings),3.750834)

    @unittest.skipUnless(MOVEL.is_dir(),'Desenho MOVEL PONTA indisponível')
    def test_angle_columns_keep_both_tube_lengths(self):
        path=next(MOVEL.rglob('*140746.PDF'))
        with pymupdf.open(path) as pdf:
            rows=cut_table_rows(pdf[0].get_text(),pdf[0])
        self.assertEqual([(r['length'],r['quantity']) for r in rows],
                         [(1286,1),(323,1)])
        project=process_complete_project(MOVEL)
        parts=[item for item in project['materials']
               if '140746' in item['drawing_id']]
        self.assertEqual(len(parts),4)
        self.assertEqual(sorted(item['length'] for item in parts),[323,323,1286,1286])
        self.assertTrue(all(item['group_name']=='Tubo Quadrado/Retangular'
                            and item['quantity']==1 for item in parts))

    def test_header_and_two_material_rows(self):
        text=('Nº DO ITEM\nMATERIAL\nCOMPRIMENTO\nQTD.\n'
              '1\nTUBO IND 20X20X0,9mm\n510\n1\n'
              '2\nTUBO IND 20X20X0,9mm\n850\n1\n'
              '699.004\n1:5\n-\n')
        rows=cut_table_rows(text)
        self.assertEqual([(r['length'],r['quantity']) for r in rows],[(510,1),(850,1)])
        item=details(text)
        self.assertEqual((item['length'],item['width'],item['depth'],item['thickness']),
                         (1360,20,20,0.9))

    def test_math_above_pdf_is_adopted(self):
        item=empty_item('ARAME TESTE',2,'x.pdf#page=1','Arame',
                        material='ARAME BTC Ø4mm',length=1000,radius_diam=4,
                        unit_weight=0.05,item_type='materia_prima')
        expected=calculated_weight(item)
        self.assertTrue(reconcile_item_weight(item))
        self.assertGreaterEqual(item['unit_weight'],expected)
        self.assertGreaterEqual(item['total_weight'],expected*2)
        self.assertIn('folha 50.000 g',item['observation'])

    def test_manual_edit_cannot_lower_below_geometry(self):
        from app import create_project,create_material,update_material,ProjectCreate,MaterialCreate,MaterialUpdate
        from database import init_db,get_connection
        test_runs=Path(__file__).resolve().parent/'data'/'test_runs'
        test_runs.mkdir(exist_ok=True)
        with patch('database.DB_PATH',str(test_runs/'cut_table_weight_test.db')):
            init_db()
            project_id=create_project(ProjectCreate(name='Conferência de massa'))['id']
            item_id=create_material(project_id,MaterialCreate(
                description='ARAME BTC Ø4mm',group_name='Arame',item_type='materia_prima',
                material='ARAME BTC Ø4mm',radius_diam=4,length=1000,quantity=2))['id']
            update_material(project_id,item_id,MaterialUpdate(unit_weight=0.001))
            conn=get_connection()
            item=dict(conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone())
            conn.close()
            self.assertGreaterEqual(item['unit_weight'],calculated_weight(item))
            self.assertGreaterEqual(item['total_weight'],item['unit_weight']*2)

    @unittest.skipUnless(RECKITT.is_dir(),'Desenhos RECKITT indisponíveis')
    def test_straight_tube_profile_and_length_from_drawing(self):
        with pymupdf.open(RECKITT/'POSTE Ilha Cash RECKITT.PDF') as pdf:
            detail=details(pdf[0].get_text())
        self.assertEqual((detail['material'],detail['length'],detail['width'],
                          detail['depth'],detail['thickness']),
                         ('TUBO IND. RET 50x30x2mm',1500,50,30,2))
        item=empty_item('POSTE',1,'poste.pdf#page=1','Tubo Quadrado/Retangular',
                        material=detail['material'],length=detail['length'],
                        width=detail['width'],depth=detail['depth'],
                        thickness=detail['thickness'],unit_weight=detail['unit_weight'])
        self.assertTrue(reconcile_item_weight(item))
        self.assertEqual(item['unit_weight'],3.5796)
        self.assertIn('Tubo retangular 50x30x2 mm; comprimento 1500 mm',item['observation'])
        self.assertIn('folha 3446.567 g',item['observation'])

    @unittest.skipUnless(RECKITT.is_dir(),'Desenhos RECKITT indisponíveis')
    def test_bent_tube_without_developed_length_stays_unresolved(self):
        path=RECKITT/'TESTEIRA Ilha Cash RECKITT'/'ARCO TESTEIRA Ilha Cash RECKITT.PDF'
        if not path.is_file(): self.skipTest('ARCO TESTEIRA indisponível')
        with pymupdf.open(path) as pdf:
            detail=details(pdf[0].get_text())
        self.assertEqual(detail['length'],0)
        self.assertEqual((detail['width'],detail['depth'],detail['thickness']),(20,20,0.9))

    @unittest.skipUnless(ROOT.is_dir(),'Desenhos TAMBASA indisponíveis')
    def test_real_bent_wire_uses_developed_length_and_sheet_mass(self):
        path=next(ROOT.rglob('ARCO LATERAL CESTO*.PDF'))
        with pymupdf.open(path) as pdf:
            item=details(pdf[0].get_text())
        self.assertEqual((item['length'],item['diameter']),(757.133,4))
        self.assertEqual(item['cut_table_rows'][0]['quantity'],1)
        self.assertAlmostEqual(item['unit_weight'],0.075164)
        project=process_complete_project(ROOT)
        wire=next(x for x in project['materials'] if x['description'].startswith('ARCO LATERAL'))
        self.assertEqual(wire['quantity'],2)
        self.assertEqual((wire['drawing_length'],wire['length']),(757.133,777.133))
        self.assertGreaterEqual(wire['finished_unit_weight'],item['unit_weight'])
        self.assertGreaterEqual(wire['unit_weight'],calculated_weight({**wire,'length':777.133}))
        self.assertGreaterEqual(wire['finished_total_weight'],item['unit_weight']*2)

    @unittest.skipUnless(ROOT.is_dir(),'Desenhos TAMBASA indisponíveis')
    def test_single_pdf_is_a_raw_material(self):
        path=next(ROOT.rglob('ARCO LATERAL CESTO*.PDF'))
        with patch('pathlib.Path.rglob',return_value=iter([path])):
            project=process_complete_project(path.parent)
        self.assertEqual(len(project['materials']),1)
        wire=project['materials'][0]
        self.assertEqual(wire['group_name'],'Arame')
        self.assertEqual(wire['quantity'],1)
        self.assertEqual(wire['drawing_length'],757.133)
        self.assertGreaterEqual(wire['finished_unit_weight'],0.075164)


if __name__=='__main__':
    unittest.main()
