"""Lados direito/esquerdo em BOM com apenas um desenho detalhado."""

from pathlib import Path
import unittest

from reader_v3 import (empty_item, finish_materials, mirror_instruction,
                       process_complete_project, side_and_base)
from side_quantities import annotate_side_totals
from item_types import has_detail_children


ALPA_PDF = (Path(__file__).parent / "data" / "uploads" / "proj_4" /
            "fd419a853dd84ad182965f7d130b6728" / "source")


class MirroredPartsTest(unittest.TestCase):
    def test_side_names_and_explicit_instruction(self):
        self.assertEqual(side_and_base("SM LATERAL DIREITA"), ("direita", "SM LATERAL"))
        self.assertEqual(side_and_base("SM LATERAL ESQUERDA"), ("esquerda", "SM LATERAL"))
        self.assertFalse(mirror_instruction("SM LATERAL DIREITA"))
        self.assertTrue(mirror_instruction("FAZER MONTAGEM ESPELHO DESSA SUBMONTAGEM"))

    def test_same_drawing_does_not_merge_opposite_sides(self):
        right = empty_item("SUPORTE DIREITO", 1, "p.pdf#page=1", "Chapa",
                           "Corpo", drawing_id="P01", material="Aço")
        left = empty_item("SUPORTE ESQUERDO", 1, "p.pdf#page=1", "Chapa",
                          "Corpo", drawing_id="P01", material="Aço")
        data = finish_materials({"materials": [right, left]})
        self.assertEqual(len(data["materials"]), 2)

    def test_verified_pair_is_stored_in_one_quantity(self):
        right=empty_item('TUBO PEZINHOS',1,'p.pdf#page=1','Tubo Quadrado/Retangular',
                         'Corpo / SM LATERAL DIREITA',drawing_id='P01',material='AÇO')
        left=empty_item('TUBO PEZINHOS',1,'p.pdf#page=1','Tubo Quadrado/Retangular',
                        'Corpo / SM LATERAL ESQUERDA',drawing_id='P01',material='AÇO')
        right['unit_weight']=left['unit_weight']=0.28
        right['total_weight']=left['total_weight']=0.28
        left['is_inferred']=1
        merged=finish_materials({'materials':[right,left]})['materials']
        self.assertEqual(len(merged),1)
        self.assertEqual((merged[0]['quantity'],merged[0]['total_weight']),(2,0.56))
        self.assertEqual(merged[0]['mirrored_assembly'],'Corpo / SM LATERAL ESQUERDA')

    @unittest.skipUnless(ALPA_PDF.is_dir(), "PDF do projeto ALPA não está neste computador")
    def test_alpa_mirror_quantity_includes_both_sides(self):
        data = process_complete_project(ALPA_PDF)
        side_items = {side: [m for m in data["materials"]
                             if m["parent_assembly"].endswith("SM LATERAL " + side)]
                      for side in ("DIREITA", "ESQUERDA")}
        self.assertEqual(len(side_items["DIREITA"]), 6)
        self.assertEqual(len(side_items["ESQUERDA"]), 0)
        self.assertTrue(all(not m["is_inferred"] for m in side_items["DIREITA"]))
        pezinhos=[m for m in data['materials'] if m['description']=='TUBO PEZINHOS']
        self.assertEqual([m['quantity'] for m in pezinhos],[2])
        self.assertTrue(pezinhos[0]['mirrored_assembly'].endswith('SM LATERAL ESQUERDA'))
        parents = {m["description"]: m for m in data["materials"]
                   if m["item_type"] == "subconjunto" and "LATERAL" in m["description"]}
        self.assertEqual(set(parents), {"SM LATERAL DIREITA", "SM LATERAL ESQUERDA"})
        self.assertIn("espelhada", parents["SM LATERAL ESQUERDA"]["observation"])
        self.assertTrue(has_detail_children(parents['SM LATERAL ESQUERDA'],data['materials']))


if __name__ == "__main__":
    unittest.main()
