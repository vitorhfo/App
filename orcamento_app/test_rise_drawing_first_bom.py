"""RISE table variant seen on DOCILE RDS007M01-01, sheet 1/2."""
import unittest
from pathlib import Path

import pymupdf

from item_types import infer_item_type
from mass_math import calculated_weight
from calc_engine import resolve_material_group
from reader_v3 import (process_complete_project, select_technical_root,
                       rise_cover_specifications, technical_drawing_code, technical_table_bom,
                       technical_title_dimensions)


HEADERS = (
    'ITEM', 'DESENHO', 'DESCRIÇÃO', 'GRUPO', 'MATERIAL', 'QTD',
    'ESPESSURA', 'Ø', 'LARGURA', 'ALTURA', 'COMPRIMENTO',
    'PESO (kg)', 'ÁREA (m²)', 'VOLUME (m³)', 'OBSERVAÇÃO',
)
WIDTHS = (25, 110, 155, 75, 155, 25, 70, 35, 75, 70, 100, 70, 70, 70, 100)
REAL_SAMPLES = Path(__file__).resolve().parent / 'data' / 'audits' / 'rise_samples'


def drawn_table(headers=HEADERS, rows=None):
    doc = pymupdf.open()
    page = doc.new_page(width=1280, height=320)
    if rows is None:
        rows = [
        ('1', 'RDS007M02-01', 'MTG MOVEL COMUNICACAO LATERAL',
         'Sub. Conjunto', 'Sub. Conjunto', '2', '-', '-', '-', '-', '-', '6.1903', '2.8350', '0.0026', ''),
        ('2', 'RDS007P10-01', 'COMUNICACAO FRONTAL DA BASE',
         'PSAI', 'Chapa PSAI branco #0,90mm', '4', '0.9', '', '370', '', '95', '0.0342', '0.0711', '', ''),
        ('3', '.', 'Presilha Canoa Preta', 'Acessórios',
         'Presilha Canoa 5mm [ACPNPT00RB48]', '8', '', '', '', '', '', '0.0003', '', '', ''),
        ]
    left = 30
    edges = [left]
    for width in WIDTHS:
        edges.append(edges[-1] + width)
    ys = (40, 65, 100, 135, 170)
    page.insert_text((600, 35), 'LISTA DE MATERIAIS', fontsize=11)
    for y in ys:
        for x0, x1 in zip(edges, edges[1:]):
            page.draw_line((x0, y), (x1, y))
    for y0, y1 in zip(ys, ys[1:]):
        for x in edges:
            page.draw_line((x, y0), (x, y1))
    for row_number, values in enumerate((headers, *rows)):
        y = ys[row_number] + 12
        for col, value in enumerate(values):
            if value:
                page.insert_text((edges[col] + 2, y), value, fontsize=6)
    return doc, page


class DrawingFirstBomTests(unittest.TestCase):
    def test_heinz_blank_description_rows_are_retained_and_not_assumed_steel(self):
        headers = ('ITEM', 'QTD', 'DESCRIÇÃO', 'GRUPO', 'MATERIAL',
                   'ESPESSURA', 'Ø', 'LARGURA', 'ALTURA', 'COMPRIMENTO',
                   'DESENHO', 'PESO (kg)', 'ÁREA (m²)', 'VOLUME (m³)', 'OBSERVAÇÃO')
        rows = [
            ('1', '1', '', 'METAL',
             'CHAPA DE PLASTICO PVC VIRGEM EXPANDIDO BRANCO FOSCO E: 10,00 MM',
             '10', '', '521', '589,96', '', 'HEI001P137-00', '0.2279', '0.0792', '0.0002', ''),
            ('2', '2', '', 'SUB PRODUTO', '-', '', '', '', '', '',
             'HEI001M27-00', '1.2970', '0.4034', '', ''),
            ('3', '1', 'TRAVESSA', 'METAL', 'TUBO QUADRADO 20X20X0,9MM',
             '0.9', '', '20', '20', '449', 'HEI001P003-00', '0.2351', '', '', ''),
        ]
        doc, page = drawn_table(headers, rows)
        try:
            parsed = technical_table_bom(page.get_text(), page)
        finally:
            doc.close()
        self.assertEqual(len(parsed), 3)
        pvc, subproduct, tube = parsed
        self.assertEqual(pvc['drawing_id'], 'HEI001P137-00')
        self.assertIn('PVC', pvc['description'])
        self.assertEqual(infer_item_type(pvc['description'], 'Polímero/PSAI', 'METAL',
                                        pvc['drawing_id'], True), 'comprado')
        self.assertEqual(subproduct['drawing_id'], 'HEI001M27-00')
        self.assertEqual(infer_item_type(subproduct['description'], 'Subconjunto',
                                        'SUB PRODUTO', subproduct['drawing_id']),
                         'subconjunto')
        self.assertEqual(infer_item_type(tube['description'], 'Tubo Quadrado/Retangular',
                                        'METAL', tube['drawing_id'], True), 'materia_prima')
        self.assertEqual(resolve_material_group('PEÇA', 'CHAPA DE MDF BRANCO #9MM'),
                         'Outros Comprados')
        self.assertEqual(resolve_material_group('CHAPA BASE', 'CHAPA DE AÇO SAE 1008 2MM'),
                         'Chapa')
        pvc.update(group_name='Polímero/PSAI', thickness=10, width=521,
                   length=589.96, unit_weight=.2279)
        self.assertEqual(calculated_weight(pvc), 0.0)
        self.assertEqual(pvc['unit_weight'], .2279)

    def test_root_table_wins_even_when_child_has_more_rows(self):
        path = Path('projeto.pdf')
        root_rows = [{'drawing_id': 'RISE013M007 - GANCHO'},
                     {'drawing_id': 'RISE013M013 - TESTEIRA'}]
        child_rows = [{'drawing_id': f'RISE013P{i:03d}'} for i in range(1, 8)]
        tables = [(path, 2, root_rows, 'raiz'), (path, 3, child_rows, 'filho')]
        page_codes = {(path, 2): None, (path, 3): 'RISE013M007'}
        selected = select_technical_root(tables, page_codes,
                                          r'RISE\d{3,}M\d{2,3}')
        self.assertEqual(selected[1], 2)
        self.assertEqual(select_technical_root([tables[1]], page_codes,
                                                r'RISE\d{3,}M\d{2,3}')[1], 3)

    def test_current_project_bom_precedes_larger_historical_reference_bom(self):
        reference=Path('pacote')/'REFERENCIA'/'RISE - ILHA CASH - M01.pdf'
        project=Path('pacote')/'PROJETO'/'ILHA CASH RECKITT - 150056.PDF'
        reference_rows=[{'drawing_id':f'PC{i:08d}'} for i in range(66)]
        project_rows=[{'drawing_id':f'PC{i:08d}'} for i in range(22)]
        tables=[(reference,5,reference_rows,'referência',None),
                (project,8,project_rows,'produção',None)]
        page_codes={(p,n,id(rows)):None for p,n,rows,_,_ in tables}

        chosen=select_technical_root(tables,page_codes,
                                     r'RISE\d{3,}M\d{2,3}')
        self.assertEqual((chosen[0],chosen[1]),(project,8))

    def test_rise_item_qty_drawing_last_keeps_pg_and_rise_codes(self):
        headers = ('ITEM', 'QTD', 'DESCRIÇÃO', 'GRUPO', 'MATERIAL',
                   'ESPESSURA', 'Ø', 'LARGURA', 'ALTURA', 'COMPRIMENTO',
                   'DESENHO', 'PESO (kg)', 'ÁREA (m²)', 'VOLUME (m³)', 'OBSERVAÇÃO')
        rows = [
            ('1', '1', 'ESTRUTURA FIXA', 'Sub. Conjunto', 'Sub. Conjunto',
             '', '', '', '', '', 'P&G0180M03-00', '0.7969', '', '', ''),
            ('2', '3', 'ARAME MOLDURA', 'Arame', 'Arame BTC Ø5mm',
             '', '5', '', '', '734', 'RISE013P003', '0.1134', '', '', ''),
            ('3', '2', '', 'ABRACADEIRA', 'Nylon [ACABBC048400]',
             '', '', '', '', '', '.', '', '', '', ''),
        ]
        doc, page = drawn_table(headers, rows)
        try:
            page.draw_line((29, 5), (29, 300))  # sheet border beside the BOM
            parsed = technical_table_bom(page.get_text(), page)
        finally:
            doc.close()
        self.assertEqual([(r['item_num'], r['quantity']) for r in parsed], [(1, 1), (2, 3), (3, 2)])
        self.assertEqual(parsed[0]['drawing_id'], 'P&G0180M03-00')
        self.assertEqual((parsed[1]['diameter'], parsed[1]['length']), (5, 734))
        self.assertIsNotNone(technical_drawing_code('P&G0180M03-00'))
        self.assertIsNotNone(technical_drawing_code('RISE013P003'))
        self.assertEqual((parsed[2]['description'], parsed[2]['group']),
                         ('ABRACADEIRA', 'Acessório'))

    def test_submontagem_child_is_multiplied_and_not_charged_as_bought(self):
        # RDS007M19-01 page 23 names RDS007M24-01 as SUB-MONTAGEM; it has
        # its own component table on page 28, so the parent is never bought.
        self.assertEqual(infer_item_type('CESTO C/ PRECIFICADOR', 'Outros Comprados',
                                         'SUB-MONTAGEM', 'RDS007M24-01'),
                         'subconjunto')

    def test_child_table_with_drawing_after_description(self):
        headers = ('ITEM', 'QTD', 'DESCRIÇÃO', 'DESENHO', 'GRUPO', 'MATERIAL',
                   'ESPESSURA', 'Ø', 'LARGURA', 'ALTURA', 'COMPRIMENTO',
                   'PESO (kg)', 'ÁREA (m²)', 'VOLUME (m³)', 'OBSERVAÇÃO')
        rows = [
            ('1', '1', 'BASE G-01', 'BASE-G01',
             'POLIMERO', 'PP', '18', '', '100', '', '500', '0.1224', '', '', ''),
            ('2', '1', 'CJ HASTE ESQ.', 'RDS007M03-01',
             'Sub. Conjunto', 'Sub. Conjunto', '-', '', '', '', '', '0.8153', '', '', ''),
        ]
        doc, page = drawn_table(headers, rows)
        try:
            parsed = technical_table_bom(page.get_text(), page)
        finally:
            doc.close()
        self.assertEqual([r['item_num'] for r in parsed], [1, 2])
        self.assertEqual(parsed[0]['quantity'], 1)
        self.assertEqual((parsed[0]['thickness'], parsed[0]['width'], parsed[0]['length']),
                         (18, 100, 500))
        self.assertEqual(parsed[1]['drawing_id'], 'RDS007M03-01')
        self.assertEqual(parsed[1]['group'], 'Sub. Conjunto')

    def test_reads_each_physical_row_and_column_without_shifting(self):
        doc, page = drawn_table()
        try:
            rows = technical_table_bom(page.get_text(), page)
        finally:
            doc.close()
        self.assertEqual([row['item_num'] for row in rows], [1, 2, 3])
        self.assertEqual([row['quantity'] for row in rows], [2, 4, 8])
        self.assertEqual(rows[0]['drawing_id'], 'RDS007M02-01')
        self.assertEqual(rows[1]['description'], 'COMUNICACAO FRONTAL DA BASE')
        self.assertEqual((rows[1]['thickness'], rows[1]['width'], rows[1]['length']),
                         (0.9, 370, 95))
        self.assertEqual(rows[2]['group'], 'Acessórios')
        self.assertEqual(rows[2]['drawing_id'], 'COMPRADO: Presilha Canoa Preta')

    def test_old_item_qty_order_still_reads_as_before(self):
        text = '''ITEM QTD
DESCRIÇÃO
GRUPO
MATERIAL
ESPESSURA
Ø
LARGURA
ALTURA
COMPRIMENTO
DESENHO
PESO (kg)
ÁREA (m²)
VOLUME (m³)
OBSERVAÇÃO
1
2
TUBO TRAVESSA LAT. MOVEL PADRAO
Tubo Quadrado
Tubo Quad. Aco 30x30x0,90mm - [MTTQBT303009]
0.9
30
30
440
BUR0001P02
0.3628
0.1011
0.0000
RESERVADO TODOS OS DIREITOS'''
        rows = technical_table_bom(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['quantity'], rows[0]['length'], rows[0]['drawing_id']),
                         (2, 440, 'BUR0001P02'))

    def test_fractional_consumables_survive_the_grid_reader(self):
        # VEJA's 15-column RISE BOM uses fractional quantities for tape and
        # bubble wrap. They are physical purchase lines, not invalid rows.
        headers = ('ITEM', 'QTD', 'DESCRIÇÃO', 'GRUPO', 'MATERIAL',
                   'ESPESSURA', 'Ø', 'LARGURA', 'ALTURA', 'COMPRIMENTO',
                   'DESENHO', 'PESO (kg)', 'ÁREA (m²)', 'VOLUME (m³)', 'OBSERVAÇÃO')
        rows = [
            ('36', '0.03', 'FITA ADESIVA', 'Acessórios', 'Fita adesiva acrílica',
             '', '', '', '', '', '.', '', '', '', ''),
            ('37', '20', 'GRAMPO', 'Acessórios', 'Grampo de ferro',
             '', '', '', '', '', '.', '', '', '', ''),
            ('38', '0.08 4', 'PLÁSTICO BOLHA', 'Acessórios', 'Plástico bolha',
             '', '', '', '', '', '.', '', '', '', ''),
        ]
        doc, page = drawn_table(headers, rows)
        try:
            parsed = technical_table_bom(page.get_text(), page)
        finally:
            doc.close()
        self.assertEqual([(r['item_num'], r['quantity']) for r in parsed],
                         [(36, .03), (37, 20), (38, .08)])
        self.assertEqual(parsed[2]['description'], '4 PLÁSTICO BOLHA')


class RealRiseBomTests(unittest.TestCase):
    def sample(self, name):
        path = REAL_SAMPLES / name / f'{name}.pdf'
        if not path.is_file():
            self.skipTest(f'Amostra PDF local indisponível: {name}')
        return path

    def test_hh_global_12_column_rise_list_keeps_each_item_and_its_quantity(self):
        root=(Path(__file__).resolve().parent/'data'/'uploads'/'proj_104'/
              'da0de1b420c64cc2843b2a5788105886'/'source')
        path=root/'PA00000328 - PONTA DE GC_NDOLA DE AC_O ALIMENTAR RECKITT.pdf'
        if not path.is_file(): self.skipTest('Projeto HH GLOBAL #104 indisponível')
        with pymupdf.open(path) as pdf:
            rows=technical_table_bom(pdf[7].get_text(),pdf[7])
        self.assertEqual(len(rows),68)
        base=next(row for row in rows if row['drawing_id']=='PC00005091')
        self.assertEqual((base['description'],base['quantity'],base['unit'],
                          base['width'],base['length']),
                         ('CV BASE',1,'UN',200,1058))
        arame=next(row for row in rows if row['drawing_id']=='PC00000809')
        self.assertEqual((arame['description'],arame['quantity'],arame['length'],
                          arame['unit']),('APARADOR',2,566.566,'un'))

        project=process_complete_project(root)
        self.assertEqual(len(project['materials']),82)
        self.assertLess(max(row['quantity'] for row in project['materials']),100)
        self.assertAlmostEqual(project['nominal_weight_pdf'],70.15)
        self.assertAlmostEqual(project['nominal_area_pdf'],52.7154)
        repeated=[row for row in project['materials'] if row['drawing_id']=='AC00000211']
        self.assertEqual([(row['item_num'],row['quantity']) for row in repeated],[(58,12),(69,12)])
        repeated_warning=next(row for row in project['pending_decisions']
                              if row['title']=='Conferir linhas repetidas entre páginas')
        self.assertIn('item 58 p.8 (AC00000211)',repeated_warning['description'])
        self.assertIn('item 69 p.9 (AC00000211)',repeated_warning['description'])
        self.assertTrue(any(row['title']=='Conferir massa da capa e do carimbo CAD'
                            for row in project['pending_decisions']))
        self.assertTrue(any(row['title']=='Conferir peso total da capa versus subtotais'
                            for row in project['pending_decisions']))
        by_code={row['drawing_id']:row for row in project['materials']}
        self.assertTrue(by_code['AC00000044']['description'].startswith(
                        'PARAFUSO DE ACO CARBONO BICROMATIZADO CABECA CHATA PHILIPS CHIPBOARD'))
        self.assertIn('#page=9',by_code['AC00000211']['source_page'])
        base_item=next(row for row in project['materials'] if row['drawing_id']=='PC00005091')
        self.assertEqual((base_item['item_type'],base_item['thickness'],base_item['width'],
                          base_item['length'],base_item['printing']),
                         ('comprado',0.9,200,1058,'4x0'))
        tube=next(row for row in project['materials'] if row['drawing_id']=='PC00005015')
        self.assertEqual((tube['group_name'],tube['width'],tube['depth'],tube['thickness'],
                          tube['length']),('Tubo Quadrado/Retangular',40,30,2,2000))
        mdf=next(row for row in project['materials'] if row['drawing_id']=='PC00005114')
        self.assertEqual((mdf['item_type'],mdf['group_name'],mdf['thickness']),
                         ('comprado','Outros Comprados',15))

    def test_hh_global_11_column_list_without_det_uses_full_product_bom(self):
        root=(Path(__file__).resolve().parent/'data'/'uploads'/'proj_111'/
              'fe42bd508e914af69a92da0924871840'/'source')
        path=root/'PA00000334 - ILHA DE AC_O ALIMENTAR RECKITT VANISH BTS.pdf'
        if not path.is_file(): self.skipTest('Projeto HH GLOBAL #111 indisponível')
        with pymupdf.open(path) as pdf:
            first_page=technical_table_bom(pdf[7].get_text(),pdf[7])
            continuation=technical_table_bom(pdf[8].get_text(),pdf[8])
            cover=rise_cover_specifications(pdf[0],'PA00000334')
        self.assertEqual(len(first_page),54)
        self.assertEqual(len(continuation),33)
        first=first_page[0]
        self.assertEqual((first['item_num'],first['drawing_id'],first['description'],
                          first['quantity'],first['unit'],first['width'],first['length']),
                         (1,'PC00005093','CV APLIQUE',3,'UN',100,100))
        self.assertEqual(continuation[0]['item_num'],55)
        self.assertEqual(cover['total_weight'],133.9382)
        self.assertEqual(cover['steel_weight'],123.43)
        self.assertEqual(cover['polymer_weight'],2.49)
        self.assertEqual(cover['mdf_weight'],4.82)
        self.assertEqual(cover['printing_area'],1.95)

        project=process_complete_project(root)
        self.assertEqual(len(project['materials']),87)
        self.assertAlmostEqual(project['nominal_weight_pdf'],133.9382)
        self.assertAlmostEqual(sum(row['total_weight'] for row in project['materials']),
                               128.300998,places=5)
        self.assertTrue(any('#page=8' in row['source_page'] for row in project['materials']))
        self.assertTrue(any('#page=9' in row['source_page'] for row in project['materials']))
        self.assertFalse(any('#page=32' in row['source_page'] for row in project['materials']))
        breakdown=next(row for row in project['pending_decisions']
                       if row['title']=='Conferir peso total da capa versus subtotais')
        self.assertIn('4.82',breakdown['description'])

    def test_heinz_full_project_retains_blank_description_parts_and_stamped_weights(self):
        path = Path(__file__).resolve().parent / 'data' / 'audits' / 'heinz_fixture' / 'KRAFT HEINZ.pdf'
        if not path.is_file():
            self.skipTest('Amostra PDF HEINZ local indisponível')
        with pymupdf.open(path) as pdf:
            root = technical_table_bom(pdf[2].get_text(), pdf[2])
            metal = technical_table_bom(pdf[3].get_text(), pdf[3])
            child = technical_table_bom(pdf[32].get_text(), pdf[32])
            self.assertEqual((len(root), len(metal), len(child)), (13, 13, 3))
            self.assertEqual(root[6]['drawing_id'], 'HEI001M18-00')
            self.assertEqual(child[0]['drawing_id'], 'HEI001P137-00')
            self.assertEqual(child[0]['unit_weight'], .2279)
        project = process_complete_project(path.parent)
        by_code = {item['drawing_id']: item for item in project['materials']}
        self.assertEqual(len(project['materials']), 197)
        self.assertEqual(by_code['HEI001P137-00']['item_type'], 'comprado')
        self.assertAlmostEqual(by_code['HEI001P137-00']['unit_weight'], .2279)
        self.assertAlmostEqual(by_code['HEI001P141-00']['unit_weight'], .3816)
        self.assertAlmostEqual(by_code['HEI001P142-00']['unit_weight'], .6875)
        self.assertIn('SUBPRODUTO HEI001M27-00', by_code['HEI001P137-00']['parent_assembly'])
        self.assertEqual(by_code['HEI001M27-00']['item_type'], 'subconjunto')
        for code, size, weight in (
                ('HEI001P108-00', (15, 50, 418), .1797),
                ('HEI001P115-00', (15, 50, 225), .0967),
                ('HEI001P121-00', (15, 50, 215), .0924)):
            item = by_code[code]
            self.assertEqual((item['thickness'], item['width'], item['length']), size)
            self.assertAlmostEqual(item['unit_weight'], weight)
            self.assertEqual((item['group_name'], item['item_type']),
                             ('Outros Comprados', 'comprado'))
            self.assertTrue(item['description'].startswith('MDF '), item['description'])
        self.assertEqual((by_code['HEI001P094-00']['item_type'],
                          by_code['HEI001P094-00']['group_name']),
                         ('comprado', 'Outros Comprados'))
        self.assertEqual(by_code['HEI001P142-00']['item_type'], 'materia_prima')
        self.assertEqual(by_code['HEI001M06-00']['quantity'], 2)
        for code in ('HEI001P065-00', 'HEI001P066-00'):
            nested = [item for item in project['materials']
                      if item['drawing_id'] == code and '#page=12' in item['source_page']
                      and 'SUBPRODUTO HEI001M06-00' in item['parent_assembly']]
            self.assertEqual(len(nested), 1)
            self.assertEqual(nested[0]['quantity'], 2)
        self.assertAlmostEqual(project['nominal_weight_pdf'], 108.7325)

    def test_docile_root_child_variants_and_title_weight(self):
        path = self.sample('DOCILE_RDS007')
        with pymupdf.open(path) as pdf:
            self.assertEqual(len(technical_table_bom(pdf[2].get_text(), pdf[2])), 21)
            self.assertEqual(len(technical_table_bom(pdf[22].get_text(), pdf[22])), 9)
        project = process_complete_project(path.parent)
        self.assertAlmostEqual(project['nominal_weight_pdf'], 36.1122)
        self.assertAlmostEqual(project['nominal_area_pdf'], 21.4653)
        physical = [x for x in project['materials'] if x['item_type'] != 'subconjunto']
        self.assertTrue(any(x['description'] == 'CESTO C/ PRECIFICADOR'
                            and x['quantity'] == 4 and x['item_type'] == 'subconjunto'
                            for x in project['materials']))
        self.assertTrue(any('PORTA PRE' in x['description'].upper()
                            and x['quantity'] == 4
                            and 'CESTO C/ PRECIFICADOR' in x['parent_assembly']
                            for x in physical))
        # M13 (left, p16) and M14 (right, p17) have the same cuts. The
        # consolidated rows must count both sides in each of two parents.
        basket_wires = [x for x in physical
                        if x['description'] in ('Aramado Cesto 04', 'Aramado Cesto 01/01')
                        and 'CJ ESTRUTUTRA CESTO' in x['parent_assembly']]
        self.assertEqual(sorted(x['quantity'] for x in basket_wires),
                         [8, 8, 56, 56])
        self.assertTrue(all('CJ LATERAL ESQUERDA CESTO' in x['mirrored_assembly']
                            for x in basket_wires))

    def test_pg_root_precedes_longer_detail_bom(self):
        path = self.sample('PG_PG0180')
        with pymupdf.open(path) as pdf:
            self.assertEqual(len(technical_table_bom(pdf[1].get_text(), pdf[1])), 7)
            self.assertEqual(len(technical_table_bom(pdf[4].get_text(), pdf[4])), 8)
        project = process_complete_project(path.parent)
        self.assertEqual(len(project['materials']), 54)
        self.assertEqual(project['materials'][0]['source_page'].split('#')[-1], 'page=2')
        self.assertEqual(sum(x['description'].startswith('Estrutura da Comunica')
                             for x in project['materials']), 2)

    def test_rise_three_digit_codes_and_accessory_without_description(self):
        path = self.sample('RISE_RISE013')
        with pymupdf.open(path) as pdf:
            rows = technical_table_bom(pdf[1].get_text(), pdf[1])
            self.assertEqual(len(technical_table_bom(pdf[4].get_text(), pdf[4])), 2)
            self.assertEqual(len(technical_table_bom(pdf[10].get_text(), pdf[10])), 2)
            self.assertEqual(technical_title_dimensions(pdf[12])['width'], 55)
        self.assertEqual(len(rows), 8)
        self.assertEqual((rows[-1]['description'], rows[-1]['quantity']),
                         ('ABRACADEIRA', 2))
        project = process_complete_project(path.parent)
        self.assertEqual(len(project['materials']), 25)
        self.assertTrue(any(x['description'] == 'ABRACADEIRA'
                            and x['quantity'] == 2 and x['item_type'] == 'comprado'
                            for x in project['materials']))
        self.assertTrue(any('PORTA PRE' in x['description'].upper()
                            and x['quantity'] == 3 for x in project['materials']))
        sheet = next(x for x in project['materials']
                     if x['description'] == 'Chapa Presilha para Anti Giro')
        bar = next(x for x in project['materials']
                   if x['description'] == 'RISE013P019 - Sarjento')
        self.assertEqual((sheet['item_type'], sheet['group_name'], sheet['quantity']),
                         ('materia_prima', 'Chapa', 1))
        self.assertEqual((bar['item_type'], bar['group_name'], bar['quantity']),
                         ('materia_prima', 'Chapa', 1))
        canal = next(x for x in project['materials']
                     if x['description'] == 'Canaleta Testeira')
        self.assertEqual((canal['quantity'], canal['length'], canal['width'],
                          canal['thickness']), (2, 18, 55, .75))
        self.assertFalse(canal['pending_issue'])
        self.assertTrue(any(x['description'] == 'Gancho' and x['quantity'] == 3
                            and x['radius_diam'] == 4 and x['drawing_length'] == 142.57
                            and x['length'] == 162.57 for x in project['materials']))
        self.assertTrue(any(x['title'] == 'Vínculo de submontagem pelo nome'
                            and 'SARJENTO' in x['description'].upper()
                            for x in project['pending_decisions']))

    def test_six_hook_variant_keeps_two_grids_under_separate_parents(self):
        path = self.sample('RISE_RISE013_6')
        project = process_complete_project(path.parent)
        self.assertEqual(len(project['materials']), 28)
        ports = [x for x in project['materials']
                 if 'PORTA PRE' in x['description'].upper()]
        self.assertEqual(sorted(x['quantity'] for x in ports), [2, 4])
        self.assertEqual(len({x['parent_assembly'] for x in ports}), 2)
        self.assertTrue(any(x['description'] == 'ABRACADEIRA'
                            and x['quantity'] == 2 for x in project['materials']))

    def test_old_ilha_cash_rise_uses_later_scanned_bom_without_double_counting_details(self):
        root=(Path(__file__).resolve().parent/'data'/'uploads'/'proj_112'/
              '1836c9fcf5264e098a0254b185d92885'/'source')
        path=root/'RISE - ILHA CASH - M01.pdf'
        if not path.is_file(): self.skipTest('Projeto RISE antigo #112 indisponível')

        project=process_complete_project(root)
        materials=project['materials']
        self.assertEqual(len(materials),66)
        self.assertEqual(sorted({int(row['source_page'].rsplit('page=',1)[1])
                                 for row in materials}),[5,6])
        self.assertGreater(sum(row['total_weight'] for row in materials),100)
        # A wheel's 80 kg capacity on the same page is not the product weight.
        self.assertNotAlmostEqual(project['nominal_weight_pdf'],80.0)

        by_number={row['item_num']:row for row in materials}
        tube=by_number[48]
        self.assertEqual((tube['quantity'],tube['width'],tube['depth'],
                          tube['thickness'],round(tube['length'])),
                         (4,20,20,.9,1490))
        wire_a,wire_b=by_number[49],by_number[50]
        self.assertEqual((wire_a['quantity'],wire_b['quantity']),(4,10))
        self.assertNotEqual(wire_a['drawing_length'],wire_b['drawing_length'])
        self.assertAlmostEqual(wire_a['length']-wire_a['drawing_length'],20)
        sheet=by_number[51]
        self.assertEqual((sheet['quantity'],sheet['thickness'],
                          round(sheet['width']),round(sheet['length'])),
                         (20,.75,134,600))

        # The page 8 assembly list and pages 13/15 child drawings overlap the
        # main 66-line manufacturing list. Keep those candidates visible for
        # review, but do not silently add a second charge without a proven link.
        self.assertFalse(any('#page=8' in row['source_page'] or
                             '#page=13' in row['source_page'] or
                             '#page=15' in row['source_page']
                             for row in materials))
        unlinked=next(issue for issue in project['pending_decisions']
                      if issue['title']=='Lista escaneada sem vínculo confirmado')
        for page in ('8','13','15'):
            self.assertIn(page,unlinked['description'])
        self.assertIn('Conferir OCR',
                      {issue['title'] for issue in project['pending_decisions']})


if __name__ == '__main__':
    unittest.main()
