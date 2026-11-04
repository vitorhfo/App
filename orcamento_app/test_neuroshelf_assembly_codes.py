"""The RISE PA/CJ/RI drawing-code family must expand as one assembly tree."""

from pathlib import Path
import unittest

from reader_v3 import process_complete_project


SOURCE=Path(__file__).resolve().parent/'data'/'uploads'/'proj_116' /\
       '2f5fde13ea6d4d54bb5f5aa0a53d4362'/'source'
PDF=SOURCE/'PA00000352_NEUROSHELF VENUS - 2627 - REV.0.pdf'


@unittest.skipUnless(PDF.is_file(),'PDF real Neuroshelf Venus indisponível')
class NeuroShelfAssemblyCodeTests(unittest.TestCase):
    def test_pa_cj_ri_codes_expand_nested_boms_without_losing_cover_weight(self):
        project=process_complete_project(SOURCE)
        rows=project['materials']
        by_drawing={row['drawing_id']:row for row in rows}

        self.assertEqual(project['nominal_weight_pdf'],94.9)
        self.assertEqual(len(rows),126)
        self.assertIn('Tubo Quadrado/Retangular',
                      {row['group_name'] for row in rows})
        self.assertIn('Chapa',{row['group_name'] for row in rows})
        self.assertIn('Arame',{row['group_name'] for row in rows})
        self.assertEqual(by_drawing['RI00000309']['quantity'],2)
        self.assertEqual(by_drawing['CJ00001842']['quantity'],80)
        self.assertTrue(any(row['drawing_id']=='CJ00000109' and
                            'BARRA DE CARGA' in row['parent_assembly']
                            for row in rows))
        self.assertFalse(any(
            row['item_type']=='subconjunto' and
            'Subconjunto sem lista detalhada correspondente' in
            (row.get('pending_issue') or '') for row in rows))
        self.assertAlmostEqual(
            sum(float(row.get('total_weight') or 0) for row in rows
                if row['item_type']!='subconjunto'),
            86.041852,places=3)
        right_bar=next(row for row in rows if row['drawing_id']=='PC00000197')
        self.assertEqual(right_bar['length'],795.5)
        self.assertEqual(right_bar['unit_weight'],0.5452)
        self.assertEqual(right_bar['quantity'],10)
        self.assertEqual(right_bar['thickness'],0.9)
        self.assertIn('divergentes',right_bar['pending_issue'])
        left_bar=next(row for row in rows if row['drawing_id']=='PC00000198')
        self.assertEqual(left_bar['length'],795.5)
        self.assertEqual(left_bar['unit_weight'],0.6576)
        self.assertTrue(any(item['title']=='Conferir tabela técnica'
                            for item in project['pending_decisions']))


if __name__=='__main__':
    unittest.main()
