"""Company drawings that exposed missing CAD columns and false art exclusions."""
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import pymupdf

from reader_v3 import cad_bom, process_complete_project
from reader_profiles.cad_part_number import is_part_only_bom
from reader_profiles.cad_grids import cad_named_grid_bom

AUDIT = Path(__file__).resolve().parent / 'data/audits/company_coverage_20261106'
REAL = AUDIT / 'copies/56ca5f78a8eb5129/WV/CONJ. APOIO CENTRAL AL. e F.F..PDF'


def part_table(rows=None, headers=('Nº ITEM', 'Nº DA PEÇA', 'DESCRIÇÃO', 'QTD.')):
    doc = pymupdf.open()
    page = doc.new_page(width=650,height=400)
    xs=(30,85,365,555,615);ys=(45,75,115,155)
    for x in xs:page.draw_line((x,ys[0]),(x,ys[-1]))
    for y in ys:page.draw_line((xs[0],y),(xs[-1],y))
    values=[headers,*(rows or [('1','APOIO F.F. # 1,2 mm Cesto Transporte','','1'),
                              ('2','APOIO ALUMINIO # 1,8 mm Cesto Transporte','','1')])]
    for row,columns in enumerate(values):
        for col,text in enumerate(columns):
            if text:page.insert_text((xs[col]+3,ys[row]+18),text,fontsize=8)
    return doc,page


class CompanyCadFormatTests(unittest.TestCase):
    def test_adding_an_unrelated_new_format_does_not_replace_legacy_variant(self):
        import uuid
        folder=Path(__file__).resolve().parent/'data/test_runs'/('variants_'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        try:
            doc=pymupdf.open();page=doc.new_page()
            page.insert_text((30,40),'Nº\nDESCRIÇÃO\nCODIGO\nQTD\n1\nPECA ORIGINAL\n123456\n3\nPESO LIQ',fontsize=10)
            doc.save(folder/'ORIGINAL.pdf');doc.close()
            doc,_=part_table(rows=[('1','654321','PECA NOVA A','4'),('2','654322','PECA NOVA B','2')])
            doc.save(folder/'NOVA.pdf');doc.close()
            data=process_complete_project(folder)
            self.assertEqual([(m['description'],m['quantity']) for m in data['materials']],
                             [('PECA ORIGINAL',3)])
            self.assertTrue(any(p['title']=='Escolher variante do produto' for p in data['pending_decisions']))
        finally:
            if folder.resolve().is_relative_to(Path(__file__).resolve().parent/'data/test_runs'):
                shutil.rmtree(folder)

    def test_detail_self_lists_are_not_added_to_multipage_root_quantities(self):
        import uuid
        folder=Path(__file__).resolve().parent/'data/test_runs'/('multipage_'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        try:
            document=pymupdf.open()
            for rows in [[('1','142335','CHAPA LATERAL','2'),('2','142334','TUBO HORIZONTAL','1')],
                         [('1','142335','CHAPA LATERAL','1')],[('1','142334','TUBO HORIZONTAL','1')]]:
                doc,_=part_table(rows=rows);document.insert_pdf(doc);doc.close()
            document.save(folder/'MONTAGEM.pdf');document.close()
            data=process_complete_project(folder)
            self.assertEqual([(m['raw_code'],m['quantity']) for m in data['materials']],
                             [('142335',2),('142334',1)])
            self.assertTrue(any(p['title']=='Vincular listas CAD de detalhe' for p in data['pending_decisions']))
        finally:
            if folder.resolve().is_relative_to(Path(__file__).resolve().parent/'data/test_runs'):
                shutil.rmtree(folder)
    def test_numeric_links_preserve_parent_quantities_without_descending_into_self_lists(self):
        import uuid
        folder=Path(__file__).resolve().parent/'data/test_runs'/('cad_package_'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        try:
            tables=[('MONTAGEM.pdf',[('1','142335','CHAPA LATERAL','2'),('2','142334','TUBO HORIZONTAL','1')]),
                    ('PECA - 142335.pdf',[('1','142335','CHAPA LATERAL','1')]),
                    ('PECA - 142334.pdf',[('1','142334','TUBO HORIZONTAL','1')])]
            for name,rows in tables:
                doc,_=part_table(rows=rows);doc.save(folder/name);doc.close()
            data=process_complete_project(folder)
            self.assertEqual([(m['raw_code'],m['quantity']) for m in data['materials']],
                             [('142335',2),('142334',1)])
            self.assertEqual({m['parent_assembly'] for m in data['materials']},{'MONTAGEM'})
            self.assertTrue(all(m['source_page'].startswith('PECA - ') for m in data['materials']))
        finally:
            if folder.resolve().is_relative_to(Path(__file__).resolve().parent/'data/test_runs'):
                shutil.rmtree(folder)

    def test_a_part_self_reference_does_not_become_an_extra_assembly(self):
        part={'cad_layout':'part_number_grid','quantity':1,'description':'TUBO HORIZONTAL',
              'raw_code':'142334'}
        self.assertTrue(is_part_only_bom([(1,[part])],'TUBO HORIZONTAL - 142334'))
        self.assertFalse(is_part_only_bom([(1,[{**part,'description':'ARAME','raw_code':''}])],
                                        'CONJUNTO SOLDADO'))
    def test_part_number_column_preserves_names_blank_description_and_quantity(self):
        doc,page=part_table()
        try:rows=cad_bom(page.get_text(),page)
        finally:doc.close()
        self.assertEqual([(r['description'],r['quantity']) for r in rows],
            [('APOIO F.F. # 1,2 mm Cesto Transporte',1),
             ('APOIO ALUMINIO # 1,8 mm Cesto Transporte',1)])

    def test_numeric_part_number_keeps_description_and_explicit_code(self):
        doc,page=part_table(rows=[('1','142335','CHAPA LATERAL','2'),
                                 ('2','142334','TUBO HORIZONTAL','1')])
        try:rows=cad_bom(page.get_text(),page)
        finally:doc.close()
        self.assertEqual([(r['description'],r['raw_code'],r['quantity']) for r in rows],
                         [('CHAPA LATERAL','142335',2),('TUBO HORIZONTAL','142334',1)])

    def test_wrong_header_and_missing_quantity_do_not_invent_a_component(self):
        for kwargs in ({'headers':('ITEM','MATERIAL','DESCRIÇÃO','QTD.')},
                       {'rows':[('1','APOIO','','?'),('2','TUBO','','1')]}):
            with self.subTest(kwargs=kwargs):
                doc,page=part_table(**kwargs)
                try:self.assertEqual(cad_bom(page.get_text(),page),[])
                finally:doc.close()

    @unittest.skipUnless(REAL.is_file(),'Amostra real da auditoria indisponível')
    def test_real_wv_assembly_lists_both_parts_once(self):
        with pymupdf.open(REAL) as doc:
            rows=cad_bom(doc[0].get_text(),doc[0])
        self.assertEqual([(r['description'],r['quantity']) for r in rows],
            [('APOIO F.F. # 1,2 mm Cesto Transporte',1),
             ('APOIO ALUMINIO # 1,8 mm Cesto Transporte',1)])


class CompanyPdfSelectionTests(unittest.TestCase):
    def test_parts_in_filename_are_read_while_real_art_and_obsolete_are_excluded(self):
        import uuid
        folder=Path(__file__).resolve().parent/'data/test_runs'/('selection_'+uuid.uuid4().hex)
        folder.mkdir(parents=True)
        try:
            names=['MODULO 7 PARTES.pdf','MARTELLO.pdf','ARTE/corpo.pdf',
                   'ARTES/testeira.pdf','!OBSOLETO/antigo.pdf',
                   'APRESENTAÇÃO/proposta.pdf','ARTE CORPO.pdf']
            for name in names:
                path=folder/name;path.parent.mkdir(parents=True,exist_ok=True)
                doc=pymupdf.open();page=doc.new_page()
                page.insert_text((30,40),'DESENHO TECNICO SEM LISTA DE COMPONENTES',fontsize=10)
                doc.save(path);doc.close()
            with patch('reader_v3.windows_ocr_lines',return_value=[]):
                data=process_complete_project(folder)
            self.assertEqual({d['path'] for d in data['reading_report']['documents']},
                             {'MODULO 7 PARTES.pdf','MARTELLO.pdf'})
        finally:
            if folder.resolve().is_relative_to(Path(__file__).resolve().parent/'data/test_runs'):
                shutil.rmtree(folder)


class AdditionalCompanyGridTests(unittest.TestCase):
    def real_page(self,client):
        evidence=AUDIT/'still_unrecognized_headers.json'
        if not evidence.is_file():self.skipTest('Amostras complementares indisponíveis')
        import json
        data=next(r for r in json.loads(evidence.read_text(encoding='utf8')) if r['client']==client)
        return data

    def test_polar_wire_components_keep_all_twelve_cuts_and_decimal_diameter(self):
        source=self.real_page('POLAR REFRIGERAÇÃO')
        with pymupdf.open(source['pdf']) as doc:
            rows=cad_bom(doc[source['page']-1].get_text(),doc[source['page']-1])
        self.assertEqual(len(rows),12)
        by_number={r['item_num']:r for r in rows}
        self.assertEqual((by_number[2]['quantity'],by_number[2]['row_diameter'],by_number[2]['row_length']),
                         (82,2.7,401))
        self.assertEqual((by_number[7]['quantity'],by_number[7]['row_length']),(2,103.1))
        self.assertEqual(sum(r['quantity'] for r in rows),104)
        project=process_complete_project(Path(source['pdf']).parent)
        wire=next(m for m in project['materials'] if '2,7' in m['description'])
        self.assertEqual((wire['quantity'],wire['radius_diam'],wire['drawing_length'],wire['length']),
                         (82,2.7,401,421))
        self.assertEqual(project['nominal_weight_pdf'],.4)

    def test_wrapped_legacy_description_with_blank_code_preserves_both_items(self):
        source=self.real_page('FABRÃO')
        with pymupdf.open(source['pdf']) as doc:
            rows=cad_bom(doc[0].get_text(),doc[0])
        self.assertEqual(len(rows),2)
        self.assertEqual([r['quantity'] for r in rows],[1,1])
        self.assertTrue(rows[0]['description'].startswith('ARAME GANCHO 124 x 98mm'))
        self.assertIn('EXPOSITOR DE BICICLETA',rows[0]['description'])
        self.assertTrue(all(r['raw_code']=='' for r in rows))

    def test_pos_material_grid_preserves_assembly_and_stock_length_is_not_a_cut(self):
        source=self.real_page('NICOLAS')
        with pymupdf.open(source['pdf']) as doc:
            rows=cad_bom(doc[0].get_text(),doc[0])
        self.assertEqual(len(rows),6)
        self.assertTrue(rows[1]['assembly_hint'])
        self.assertEqual((rows[0]['row_width'],rows[0]['row_depth'],rows[0]['row_thickness'],
                          rows[0]['row_length']),(15,15,.9,0))
        self.assertEqual(rows[2]['row_diameter'],5)
        self.assertEqual(rows[2]['row_weight_kg'],0)
        self.assertEqual(rows[2]['row_weight_raw'],'0.04')


if __name__=='__main__':unittest.main()
