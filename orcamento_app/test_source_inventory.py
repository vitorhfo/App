"""Every project PDF remains accessible even when no item or dimension matched."""

from pathlib import Path
import unittest

from source_inventory import list_project_pdfs

DURACELL=(Path(__file__).resolve().parent.parent.parent/'DADOS'/'JOSÉ VITOR'/
          'TESTES DE ORÇAMENTO'/'FLAVIO PAPILE'/'Display Balcão DURACELL'/'PROJETO')


class SourceInventoryTest(unittest.TestCase):
    @unittest.skipUnless(DURACELL.is_dir(), 'Desenhos DURACELL indisponíveis')
    def test_lists_parent_child_and_unmatched_pdf_with_dimension_status(self):
        child='PSAI Display Balcão DURACELL/PSAI LAT. Display Balcão DURACELL.PDF'
        materials=[
            {'source_page':'Display Balcão DURACELL.PDF#page=1',
             'group_name':'Polímero/PSAI','item_type':'comprado',
             'length':0,'width':0,'thickness':0},
            {'source_page':f'{child}#page=1','group_name':'Polímero/PSAI',
             'item_type':'comprado','length':250,'width':150,'thickness':1},
        ]
        files=list_project_pdfs(DURACELL,materials)
        by_path={entry['path']:entry for entry in files}
        self.assertGreaterEqual(len(files),14)
        self.assertEqual(by_path['Display Balcão DURACELL.PDF']['missing_dimensions_count'],1)
        self.assertEqual(by_path[child]['linked_items_count'],1)
        self.assertEqual(by_path[child]['missing_dimensions_count'],0)
        unmatched='PSAI Display Balcão DURACELL/PSAI GAVETA Display Balcão DURACELL.PDF'
        self.assertEqual(by_path[unmatched]['linked_items_count'],0)
        self.assertEqual(by_path[unmatched]['source_ref'],f'{unmatched}#page=1')


if __name__=='__main__':
    unittest.main()
