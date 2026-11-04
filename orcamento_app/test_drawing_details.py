"""Dimensions printed on a part drawing, outside the BOM row."""
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

import pymupdf

from reader_v3 import (details, parameterized_details, process_complete_project, shared_side_drawing,
                       technical_table_bom, title_weight)
from mass_math import calculated_weight, reconcile_item_weight
from backfill_validated_sheets import validated_blank_dimensions
from manual_validation import linked_drawing


DRAWINGS=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'ILHA CASH RECKITT'/
          'PROJETO'/'APARADOR BASE Ilha Cash RECKITT')
RECKITT_BASE=DRAWINGS.parent/'CORPO Ilha Cash RECKITT'/'BASE Ilha Cash RECKITT'
DURACELL=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'JOSÉ VITOR'/
          'TESTES DE ORÇAMENTO'/'FLAVIO PAPILE'/'Display Balcão DURACELL'/
          'PROJETO'/'PSAI Display Balcão DURACELL')
DURACELL_METAL=DURACELL.parent/'ESTR. Display Balcão DURACELL'
ALPA_5X5=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'JOSÉ VITOR'/
          'TESTES DE ORÇAMENTO'/'ALPARGATAS'/'ALPA BASICO 5x5'/'PROJETO'/
          'ALP0155M01_GERAL_BASICO 5x5.pdf')
TROPERO=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'JOSÉ VITOR'/
         'TESTES DE ORÇAMENTO'/'FLAVIO PAPILE'/'DISPLAY BALCÃO TROPERO ALIMENTOS')
HELLMANNS_103=(Path(__file__).resolve().parent/'data'/'uploads'/'proj_103'/
               '1aaea6ab1c434e64b1e34d5141ca85ae'/'source')


class DrawingDetailsTest(unittest.TestCase):
    @unittest.skipUnless(HELLMANNS_103.is_dir(),'Projeto HELLMANNS #103 indisponível')
    def test_hellmanns_laterals_read_overall_dimensions_from_view_not_description(self):
        project=process_complete_project(HELLMANNS_103)
        dimensions={item['description']:(item['length'],item['width'],item['thickness'])
                    for item in project['materials']}
        expected={
            'LAT DIR Porta Sache Grav HELLMANNS':(222.8,150.0,0.9),
            'LAT ESQ Porta Sache Grav HELLMANNS':(222.8,150.0,0.9),
            'CH FR Porta Sache Grav HELLMANNS':(264.7,130.0,0.9),
            'DIVISORIA Porta Sache Grav HELLMANNS':(198.0,155.3,0.9),
        }
        for description,wanted in expected.items():
            with self.subTest(description=description):
                self.assertEqual(dimensions[description],wanted)
                item=next(x for x in project['materials'] if x['description']==description)
                self.assertIn('.PDF#page=1',item['source_page'])
            gross=calculated_weight({'group_name':item['group_name'],
                'material':item['material'],'length':item['length'],
                'width':item['width'],'thickness':item['thickness']})
            self.assertGreaterEqual(item['unit_weight'],gross)
            self.assertIn('Cálculo acima da folha',item['observation'])
        front=next(item for item in project['materials']
                   if item['description'].startswith('CH Porta Sache'))
        self.assertEqual((front['length'],front['width'],front['thickness']),
                         (368.0,264.7,0.9))

    def test_visual_sheet_fallback_rejects_assembly_dimensions_from_other_projects(self):
        root=Path(__file__).resolve().parent.parent.parent/'DADOS'
        samples=(
            (root/'DISPLAY CARMED'/'CIM006_DISPLAY SLIM CARMED - REV.00.pdf',9),
            (root/'E03704167 - MPDV SAZONAL - CASH&CARRY'/
             'PG - OP01 - PONTA DE GÔNDOLA - MODULO A (1 2 pallet)'/'REFERÊNCIA'/
             'PG - OP01 - PONTA DE GÔNDOLA - MODULO A (1 2 pallet).pdf',4),
            (root/'E03704167 - MPDV SAZONAL - CASH&CARRY'/
             'PG - OP03 - CAN BASE - MODULO D (1 pallet)'/'REFERÊNCIA'/
             'PG - OP03 - CAN BASE - MODULO D (1 pallet).pdf',3),
        )
        for drawing,page_index in samples:
            with self.subTest(drawing=drawing.name,page=page_index+1):
                if not drawing.is_file(): self.skipTest(f'Desenho indisponível: {drawing}')
                with pymupdf.open(drawing) as pdf:
                    page=pdf[page_index]
                    found=details(page.get_text(),page=page)
                self.assertEqual((found['length'],found['width']),(0.0,0.0))

    def test_visual_sheet_fallback_recovers_other_projects_single_part_drawings(self):
        root=Path(__file__).resolve().parent.parent.parent/'DADOS'
        samples=(
            (root/'ILHA CASH RECKITT'/'PROJETO'/'BARRA DE CARGA Ilha Cash RECKITT'/
             'CH BARRA DE CARGA Ilha Cash RECKITT.PDF',0,(70.0,60.0,2.0)),
            (root/'JOSÉ VITOR'/'TESTES DE ORÇAMENTO'/'FLAVIO PAPILE'/'ILHA FOR WAY'/
             'PROJETO'/'SUPORTE TEST. ILHA FOR WAY'/'CH. INF. SUPORTE TEST. ILHA FOR WAY.PDF',
             0,(80.0,41.1,2.0)),
            (root/'P&G0560_DISPLAY DE CHÃO SOFT - BB - GILLETTE - 2627'/'REFERENCIA'/
             'P&G0560 - DISPLAY DE CHÃO SOFT - BB - GILLETTE - 2627 - REV.0.pdf',
             20,(250.0,225.0,0.9)),
        )
        for drawing,page_index,wanted in samples:
            with self.subTest(drawing=drawing.name,page=page_index+1):
                if not drawing.is_file(): self.skipTest(f'Desenho indisponível: {drawing}')
                with pymupdf.open(drawing) as pdf:
                    page=pdf[page_index]
                    text=page.get_text()
                    self.assertEqual((details(text)['length'],details(text)['width']),(0.0,0.0))
                    found=details(text,page=page)
                self.assertEqual((found['length'],found['width'],found['thickness']),wanted)

    @unittest.skipUnless(RECKITT_BASE.is_dir(),'Projeto RECKITT indisponível')
    def test_single_color_psai_drawing_keeps_its_printing_code(self):
        source=(RECKITT_BASE.parent.parent/'PSAI Ilha Cash RECKITT'/'Harpic'/
                'PSAI INF TESTEIRA Ilha Cash RECKITT - Harpic.PDF')
        with pymupdf.open(source) as pdf:
            found=details(pdf[0].get_text())
        self.assertEqual((found['length'],found['width'],found['thickness'],
                          found['printing']),(700,700,1,'1x0'))
        veja=(RECKITT_BASE.parent.parent/'PSAI Ilha Cash RECKITT'/'Veja'/
              'PSAI INF TESTEIRA Ilha Cash RECKITT - Veja.PDF')
        with pymupdf.open(veja) as pdf:
            other=details(pdf[0].get_text())
        self.assertEqual((other['length'],other['width'],other['printing']),
                         (700,700,'1x0'))

    @unittest.skipUnless(RECKITT_BASE.is_dir(),'Desenho CH BASE indisponível')
    def test_blank_sheet_mass_can_exceed_finished_weight_after_cutouts(self):
        with pymupdf.open(RECKITT_BASE/'CH BASE Ilha Cash RECKITT.PDF') as pdf:
            found=details(pdf[0].get_text())
        self.assertEqual((found['length'],found['width'],found['thickness']),
                         (718.7,700,0.75))
        gross=calculated_weight({'group_name':'Chapa','material':found['material'],
                                 'length':found['length'],'width':found['width'],
                                 'thickness':found['thickness']})
        self.assertGreaterEqual(gross,found['unit_weight'])
        self.assertLessEqual(gross,found['unit_weight']*1.10)

    @unittest.skipUnless(RECKITT_BASE.is_dir(),'Desenho FIX BATEDOR indisponível')
    def test_hole_position_is_not_sheet_width_even_if_it_appears_second(self):
        drawing=RECKITT_BASE/'FIX BATEDOR BASE Ilha Cash RECKITT.PDF'
        with pymupdf.open(drawing) as pdf:
            found=details(pdf[0].get_text())
        self.assertEqual((found['length'],found['width'],found['thickness']),
                         (130,20,3))
        gross=calculated_weight({'group_name':'Chapa','material':found['material'],
                                 'length':found['length'],'width':found['width'],
                                 'thickness':found['thickness']})
        self.assertGreaterEqual(gross,found['unit_weight'])

    @unittest.skipUnless(TROPERO.is_dir(),'Desenho TROPERO indisponível')
    def test_developed_plate_selection_does_not_use_inner_fold_dimension(self):
        drawing=next(TROPERO.rglob('TRAVESSA Display Balcao TROPERO ALIM.PDF'))
        with pymupdf.open(drawing) as pdf:
            found=details(pdf[0].get_text())
        self.assertEqual((found['length'],found['width'],found['thickness']),
                         (660,56.2,1.2))

    @unittest.skipUnless(TROPERO.is_dir(),'Desenho TROPERO indisponível')
    def test_mdf_title_material_contains_sheet_thickness_and_drawn_dimensions(self):
        path=next(TROPERO.rglob('MDF Display Balcao TROPERO ALIM.PDF'))
        with pymupdf.open(path) as pdf:
            found=details(pdf[0].get_text())
        self.assertEqual((found['length'],found['width'],found['thickness']),
                         (700,450,9))

    def test_saved_mdf_and_round_tube_match_their_part_drawings(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file(): self.skipTest('Banco salvo indisponível')
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            mdf=conn.execute('SELECT * FROM materials WHERE id=736').fetchone()
            tube=conn.execute('SELECT * FROM materials WHERE id=989').fetchone()
            self.assertEqual((mdf['length'],mdf['width'],mdf['thickness']),
                             (700,450,9))
            self.assertAlmostEqual(tube['radius_diam'],25.4,places=2)
            self.assertAlmostEqual(tube['thickness'],1.5,places=2)
            self.assertAlmostEqual(tube['unit_weight'],0.707348,places=6)

    def test_saved_mdf_copies_are_bought_without_changing_existing_manual_price(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file(): self.skipTest('Banco salvo indisponível')
        with sqlite3.connect(db) as conn:
            mdf_manual=conn.execute('''SELECT group_name,item_type,unit_price,width,length
                FROM materials WHERE id=736 AND project_id=11''').fetchone()
            mdf_repaired=conn.execute('''SELECT group_name,item_type,unit_price,width,length
                FROM materials WHERE id=1572 AND project_id=87''').fetchone()
            self.assertEqual(mdf_manual,('Outros Comprados','comprado',60.0,450.0,700.0))
            self.assertEqual(mdf_repaired,('Outros Comprados','comprado',None,450.0,700.0))
            self.assertEqual(conn.execute(
                'SELECT count(*) FROM material_changes WHERE project_id=87').fetchone()[0],5)

    @unittest.skipUnless(DRAWINGS.is_dir(),'Desenhos RECKITT indisponíveis')
    def test_blank_sheet_backfill_requires_matching_drawing_mass(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            good=dict(conn.execute('SELECT * FROM materials WHERE id=526').fetchone())
            bad=dict(conn.execute('SELECT * FROM materials WHERE id=505').fetchone())
            self.assertEqual(validated_blank_dimensions({**good,'length':0,'width':0},
                             linked_drawing(conn,good)),
                             {'length':702.3,'width':644.8})
            self.assertEqual(validated_blank_dimensions(bad,linked_drawing(conn,bad)),{})
            manually_blank=dict(conn.execute('SELECT * FROM materials WHERE id=883').fetchone())
            self.assertEqual(validated_blank_dimensions({**manually_blank,'length':0,'width':0},
                             linked_drawing(conn,manually_blank)),
                             {'length':1103.0,'width':393.1})

    def test_saved_cutout_sheets_keep_pdf_validated_blank_dimensions(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file(): self.skipTest('Banco salvo indisponível')
        expected={511:(718.7,700),708:(660,56.2),859:(397,55.8),
                  922:(1429.3,1128.3),942:(55,41.5)}
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            for item_id,pair in expected.items():
                with self.subTest(item_id=item_id):
                    item=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
                    self.assertEqual((item['length'],item['width']),pair)

    def test_saved_reckitt_psai_panels_keep_drawing_and_unpriced_single_color_print(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file(): self.skipTest('Banco salvo indisponível')
        expected=(72,96,104,112,537,590,638,686,1077,1130,1178,1226)
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            for item_id in expected:
                with self.subTest(item_id=item_id):
                    item=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
                    self.assertEqual((item['length'],item['width'],item['thickness'],
                                      item['printing']),(700,700,1,'1x0'))
                    self.assertIn('PSAI BRANCO',item['material'])
                    self.assertIsNone(item['unit_price'])

    def test_saved_reckitt_manual_hole_distance_is_not_sheet_width(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file(): self.skipTest('Banco salvo indisponível')
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            for item_id in (46,505,553,606,654,1045,1093,1146,1194):
                with self.subTest(item_id=item_id):
                    row=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
                    self.assertEqual((row['length'],row['width'],row['thickness']),
                                     (130,20,3))
                    self.assertAlmostEqual(row['unit_weight'],0.06123,places=5)
                    self.assertAlmostEqual(row['unit_price'],round(0.06123*7.02,4),places=4)
            for item_id in (88,582,1122):
                with self.subTest(item_id=item_id):
                    row=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
                    self.assertEqual((row['length'],row['width'],row['thickness']),
                                     (70,60,2))
                    self.assertAlmostEqual(row['unit_weight'],0.06594,places=5)

    @unittest.skipUnless(DRAWINGS.is_dir(), 'Desenhos RECKITT indisponíveis')
    def test_sheet_dimensions_and_title_weight(self):
        path=DRAWINGS/'CH APARADOR BASE Ilha Cash RECKITT.PDF'
        with pymupdf.open(path) as pdf:
            item=details(pdf[0].get_text())
        self.assertEqual((item['length'],item['width'],item['thickness']),
                         (20.0,15.0,0.75))
        self.assertAlmostEqual(item['unit_weight'],0.00148)
        self.assertIn('SAE',item['material'])

    @unittest.skipUnless(DRAWINGS.is_dir(), 'Desenhos RECKITT indisponíveis')
    def test_wire_single_length_and_diameter(self):
        path=DRAWINGS/'ARAME APARADOR BASE Ilha Cash RECKITT.PDF'
        with pymupdf.open(path) as pdf:
            item=details(pdf[0].get_text())
        self.assertEqual((item['length'],item['diameter']),(40.0,5.0))
        self.assertAlmostEqual(item['unit_weight'],0.006205)
        self.assertIn('BTC',item['material'])

    def test_unrelated_numbers_do_not_become_weight(self):
        self.assertEqual(title_weight('20\n15\n0,75\nPERSPECTIVA ISOMÉTRICA'),0)

    @unittest.skipUnless(DURACELL.is_dir(), 'Desenhos DURACELL indisponíveis')
    def test_developed_sheet_uses_overall_dimensions_and_flags_weight_conflict(self):
        with pymupdf.open(DURACELL/'PSAI GAVETA Display Balcão DURACELL.PDF') as pdf:
            found=details(pdf[0].get_text())
        self.assertEqual((found['length'],found['width'],found['thickness']),
                         (281.2,246.2,1.0))
        item={'group_name':'Polímero/PSAI','material':found['material'],
              'length':found['length'],'width':found['width'],
              'thickness':found['thickness'],'unit_weight':found['unit_weight'],
              'quantity':1,'observation':''}
        self.assertAlmostEqual(calculated_weight(item),0.072693012)
        reconcile_item_weight(item)
        self.assertAlmostEqual(item['unit_weight'],0.083646)
        self.assertIn('Folha acima do peso bruto calculado',item['observation'])
        project=process_complete_project(DURACELL.parent.parent)
        saved=next(x for x in project['materials'] if x['description'].startswith('PSAI GAVETA'))
        self.assertAlmostEqual(saved['unit_area'],found['unit_area'])

    @unittest.skipUnless(DURACELL.is_dir(), 'Desenhos DURACELL indisponíveis')
    def test_saved_gaveta_gets_missing_dimensions_from_its_own_pdf_only(self):
        from backfill_drawing_details import proposals
        conn=sqlite3.connect(':memory:')
        conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE projects (id INTEGER, folder_path TEXT)')
        conn.execute('''CREATE TABLE materials (id INTEGER, project_id INTEGER,
                     group_name TEXT, description TEXT, drawing_id TEXT,
                     source_page TEXT, length REAL, width REAL,
                     thickness REAL, unit_weight REAL)''')
        conn.execute('INSERT INTO projects VALUES (?,?)',(12,str(DURACELL.parent)))
        drawing='PSAI GAVETA Display Balcão DURACELL'
        child=f'PSAI Display Balcão DURACELL/{drawing}.PDF#page=1'
        parent='Display Balcão DURACELL.PDF#page=1'
        variant='CH. Display Balcão DURACELL'
        variant_pdf=f'ESTR. Display Balcão DURACELL/{variant}.PDF#page=1'
        conn.executemany('INSERT INTO materials VALUES (?,?,?,?,?,?,?,?,?,?)',[
            (1,12,'Polímero/PSAI',drawing, drawing,child,0,0,1,0.083646),
            (2,12,'Polímero/PSAI',drawing, drawing,parent,0,0,1,0.083646),
            (3,12,'Polímero/PSAI',drawing, drawing,child,300,200,1,0.083646),
            (4,12,'Chapa',variant+' - 80',variant,variant_pdf,80,0,0.9,0.008424),
        ])
        try:
            found=list(proposals(conn,12))
        finally:
            conn.close()
        self.assertEqual([item['id'] for item,_,_ in found],[1,4])
        self.assertEqual(found[0][1],{'length':281.2,'width':246.2})
        self.assertEqual(found[1][1],{'width':15.0})

    def test_sheet_with_competing_large_dimensions_remains_unresolved(self):
        sample=('281,2\n246,2\n245\n110\nPERSPECTIVA ISOMÉTRICA\n'
                'LOCAL DIGITAL:\nPSAI BRANCO #1mm\n19/02/2025\n')
        found=details(sample)
        self.assertEqual((found['length'],found['width']),(0,0))

    @unittest.skipUnless(DURACELL_METAL.is_dir(), 'Desenhos metálicos DURACELL indisponíveis')
    def test_duracell_bent_sheets_use_blank_dimensions_verified_by_weight(self):
        expected={
            'PERFIL SUP. Display Balcão DURACELL':(245.8,110.0,0.75),
            'CANTONEIRA Display Balcão DURACELL':(135.0,38.3,0.9),
        }
        for drawing,dimensions in expected.items():
            with self.subTest(drawing=drawing),pymupdf.open(DURACELL_METAL/(drawing+'.PDF')) as pdf:
                found=details(pdf[0].get_text())
                self.assertEqual((found['length'],found['width'],found['thickness']),dimensions)
                mass=calculated_weight({'group_name':'Chapa','material':found['material'],
                    'length':found['length'],'width':found['width'],
                    'thickness':found['thickness']})
                self.assertLess(abs(mass-found['unit_weight'])/found['unit_weight'],0.03)

    @unittest.skipUnless(DURACELL_METAL.is_dir(), 'Desenhos metálicos DURACELL indisponíveis')
    def test_duracell_a_dimension_comes_from_parent_bom_and_width_from_child(self):
        with pymupdf.open(DURACELL_METAL/'CH. Display Balcão DURACELL.PDF') as pdf:
            text=pdf[0].get_text()
        for length in (80,150,230):
            with self.subTest(length=length):
                found=parameterized_details(text,f'CH. Display Balcão DURACELL - {length}')
                self.assertEqual((found['length'],found['width'],found['thickness']),
                                 (float(length),15.0,0.9))
                mass=calculated_weight({'group_name':'Chapa','material':found['material'],
                    'length':found['length'],'width':found['width'],
                    'thickness':found['thickness']})
                self.assertLess(abs(mass-found['unit_weight'])/found['unit_weight'],0.02)
        project=process_complete_project(DURACELL.parent.parent)
        variants={item['length']:item for item in project['materials']
                  if item['description'].startswith('CH. Display Balcão DURACELL - ')}
        self.assertEqual({length:item['quantity'] for length,item in variants.items()},
                         {80.0:2,150.0:4,230.0:5})
        self.assertEqual({item['width'] for item in variants.values()},{15.0})

    def test_parameterized_sheet_with_two_possible_widths_stays_unresolved(self):
        sample=('"A"\n15\n20\nPERSPECTIVA ISOMÉTRICA\nMEDIDA "A"\n'
                '80\n150\n8.424\n1:1\n-\nLOCAL DIGITAL:\n'
                'CHAPA F.F. SAE 1008 ESP. 0,90mm\n22/01/2025\n')
        found=parameterized_details(sample,'CH. Display - 80')
        self.assertEqual(found['width'],0)

    def test_ambiguous_bent_sheet_without_unique_weight_match_stays_unresolved(self):
        sample=('110\n245,8\n230\nPERSPECTIVA ISOMÉTRICA\n'
                '145.000\n1:3\n-\nLOCAL DIGITAL:\n'
                'CHAPA F.F. SAE 1008 ESP. 0,75mm\n06/01/2025\n')
        found=details(sample)
        self.assertEqual((found['length'],found['width']),(0,0))

    @unittest.skipUnless(DURACELL.is_dir(), 'Desenhos DURACELL indisponíveis')
    def test_shared_side_drawing_supplies_both_duracell_laterals(self):
        project=process_complete_project(DURACELL.parent.parent)
        laterals=[item for item in project['materials']
                  if item['description'].startswith('PSAI LAT.')]
        self.assertEqual(len(laterals),2)
        self.assertEqual({item['description'].split()[2] for item in laterals},
                         {'DIR','ESQ'})
        for item in laterals:
            self.assertEqual((item['length'],item['width'],item['thickness']),
                             (250.0,150.0,1.0))
            self.assertAlmostEqual(item['unit_weight'],0.042297)
            self.assertIn('PSAI LAT. Display Balcão DURACELL.PDF#page=1',
                          item['source_page'])
            self.assertNotIn('Desenho da peça não localizado',item['pending_issue'])

    def test_all_saved_copies_of_duracell_keep_child_lateral_drawing(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file():
            self.skipTest('Banco salvo do aplicativo indisponível')
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            projects=conn.execute('''SELECT id,folder_path FROM projects
                WHERE name=?''',('Display Balcão DURACELL',)).fetchall()
            by_folder={}
            for project in projects:
                by_folder.setdefault(project['folder_path'],[]).append(project['id'])
            duplicated=[ids for ids in by_folder.values() if len(ids)>1]
            if not duplicated:
                self.skipTest('Não há cópias DURACELL da mesma pasta')
            for ids in duplicated:
                for project_id in ids:
                    with self.subTest(project_id=project_id):
                        rows=conn.execute('''SELECT description,length,width,thickness,
                            source_page,pending_issue FROM materials WHERE project_id=?
                            AND description LIKE 'PSAI LAT.%' ORDER BY description''',
                            (project_id,)).fetchall()
                        self.assertEqual(len(rows),2)
                        for row in rows:
                            self.assertEqual((row['length'],row['width'],row['thickness']),
                                             (250.0,150.0,1.0))
                            self.assertIn('PSAI LAT. Display Balcão DURACELL.PDF#page=1',
                                          row['source_page'])
                            self.assertNotIn('Desenho da peça não localizado',
                                             row['pending_issue'] or '')

    def test_all_saved_copies_of_duracell_keep_parameterized_ch_dimensions(self):
        db=Path(__file__).resolve().parent/'data'/'orcamento.db'
        if not db.is_file():
            self.skipTest('Banco salvo do aplicativo indisponível')
        with sqlite3.connect(db) as conn:
            conn.row_factory=sqlite3.Row
            projects=conn.execute('''SELECT id,folder_path FROM projects
                WHERE name=?''',('Display Balcão DURACELL',)).fetchall()
            by_folder={}
            for project in projects:
                by_folder.setdefault(project['folder_path'],[]).append(project['id'])
            duplicated=[ids for ids in by_folder.values() if len(ids)>1]
            if not duplicated:
                self.skipTest('Não há cópias DURACELL da mesma pasta')
            for ids in duplicated:
                for project_id in ids:
                    with self.subTest(project_id=project_id):
                        rows=conn.execute('''SELECT description,quantity,length,width,
                            thickness,source_page FROM materials WHERE project_id=?
                            AND description LIKE 'CH. Display Balcão DURACELL - %'
                            ORDER BY length''',(project_id,)).fetchall()
                        self.assertEqual(len(rows),3)
                        self.assertEqual([(row['length'],row['width'],row['thickness'],
                                           row['quantity']) for row in rows],
                                         [(80.0,15.0,0.9,2),(150.0,15.0,0.9,4),
                                          (230.0,15.0,0.9,5)])
                        for row in rows:
                            self.assertIn('CH. Display Balcão DURACELL.PDF#page=1',
                                          row['source_page'])

    def test_side_neutral_drawing_requires_explicit_both_sides(self):
        drawing=Path('PSAI LAT Display.pdf')
        description='PSAI LAT DIR Display'
        one_side={drawing:{'stem':'PSAI LAT DISPLAY','text':'DIREITO 250 150'}}
        both_sides={drawing:{'stem':'PSAI LAT DISPLAY',
                             'text':'ESQUERDO DIREITO 250 150'}}
        self.assertIsNone(shared_side_drawing(description,one_side))
        self.assertEqual(shared_side_drawing(description,both_sides),drawing)
        other=Path('outra pasta/PSAI LAT Display.pdf')
        self.assertIsNone(shared_side_drawing(description,
            {**both_sides,other:both_sides[drawing]}))

    @unittest.skipUnless(ALPA_5X5.is_file(), 'Desenho ALPA 5x5 indisponível')
    def test_last_measure_before_drawing_code_is_kept(self):
        with pymupdf.open(ALPA_5X5) as pdf:
            rows=technical_table_bom(pdf[1].get_text())
        tag=next(x for x in rows if x['description']=='CHAPA TAG PARA QR CODE')
        front=next(x for x in rows if x['description']=='TESTEIRA')
        self.assertEqual((tag['thickness'],tag['width'],tag['length']),(.9,70,22.5))
        self.assertEqual((front['thickness'],front['width'],front['length']),
                         (1.5,264,1263.5))
        self.assertEqual((tag['printing_hint'],front['printing_hint']),('frente','frente'))

    def test_manual_dimension_edit_preserves_controlv_area(self):
        from app import (MaterialCreate,MaterialUpdate,ProjectCreate,
                         create_material,create_project,update_material)
        from database import get_connection,init_db
        db=Path(__file__).resolve().parent/'data'/'test_runs'/'controlv_area_test.db'
        with patch('database.DB_PATH',str(db)):
            init_db()
            project=create_project(ProjectCreate(name='Controle area PSAI'))['id']
            item=create_material(project,MaterialCreate(
                description='PSAI GAVETA',group_name='Polímero/PSAI',
                item_type='comprado',material='PSAI BRANCO #1mm',
                length=281.2,width=246.2,thickness=1,quantity=1))['id']
            conn=get_connection()
            conn.execute('UPDATE materials SET unit_area=? WHERE id=?',(0.107731203,item))
            conn.commit();conn.close()
            result=update_material(project,item,MaterialUpdate(length=282))
            self.assertAlmostEqual(result['material']['unit_area'],0.107731203)


if __name__=='__main__':
    unittest.main()
