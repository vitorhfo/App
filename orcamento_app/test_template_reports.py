"""Regressões para os dois modelos originais e a paginação sem mudar layout."""

import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import xlrd

from template_reports import (_aggregate_cost_items, _calc_pages, _cost_item,
                              _split_items, export_template_reports, CALC_TEMPLATE)


class CompanyTemplateTest(unittest.TestCase):
    def test_wire_cut_lengths_share_stock_but_keep_cuts_and_different_grades(self):
        def wire(name,material,length,quantity,weight):
            return dict(description=name,material=material,group_name='Arame',item_type='materia_prima',
                        radius_diam=6,length=length,quantity=quantity,unit='un',unit_weight=weight,
                        total_weight=weight*quantity,unit_price=None,total_price=None)
        materials=[wire('CORTE A','ARAME Ø6 x 200',200,2,.1),
                   wire('CORTE B','ARAME Ø6 x 400',400,1,.2),
                   wire('INOX','ARAME INOX Ø6',300,1,.3)]
        groups=_split_items(materials)
        self.assertEqual(len(groups['wire']),3)
        aggregated=_aggregate_cost_items(groups['wire'],'wire')
        self.assertEqual(len(aggregated),2)
        ordinary=next(item for item in aggregated if 'INOX' not in item['material'])
        self.assertAlmostEqual(ordinary['total_weight'],.4)
        self.assertEqual(ordinary['aggregate_count'],2)
        pages=_calc_pages(groups)
        self.assertEqual([pages[0][f'C{row}'] for row in (17,18,19)],[2,1,1])

    def test_cost_mp_uses_material_names_and_aggregated_kg(self):
        def mp(description, material, group_name, weight, **dimensions):
            return {"description": description, "material": material,
                    "group_name": group_name, "item_type": "materia_prima",
                    "quantity": 1, "total_weight": weight,
                    "unit_weight": weight, **dimensions}

        tubes = [
            mp("TUBO QUADRADO 20x20x0,9mm - HEI001P001-00",
               "TUBO AÇO SAE 1006 20x20x0,9mm", "Tubo Quadrado/Retangular", .5,
               width=20, depth=20, thickness=.9, length=500),
            mp("TUBO QUADRADO 20x20x0,9mm - HEI001P002-00",
               "TUBO AÇO SAE 1006 20x20x0,9mm", "Tubo Quadrado/Retangular", .75,
               width=20, depth=20, thickness=.9, length=750),
            mp("TUBO RETANGULAR 35x15x1,2mm",
               "TUBO AÇO SAE 1006 35x15x1,2mm", "Tubo Quadrado/Retangular", 1.775,
               width=35, depth=15, thickness=1.2, length=300),
        ]
        wires = [
            mp("ARAME BTC Ø5,0MM - HEI001P003-00", "ARAME BTC Ø5,0MM", "Arame", 2.0,
               radius_diam=5, length=300),
            mp("ARAME BTC Ø5,0MM - HEI001P004-00", "ARAME BTC Ø5,0MM", "Arame", 3.977,
               radius_diam=5, length=450),
        ]
        sheets = [
            mp("SUPORTE FIXAÇÃO", "CHAPA DE ACO CARBONO FF SAE 1006 E: 0,75 MM X L: 1200 MM X C: 2000 MM - [MTCHBT201222] - {MP00000032} - (2636)", "Chapa", 1.2,
               thickness=.75, length=400, width=300),
            mp("BASE", "CHAPA DE ACO CARBONO FF SAE 1006 E: 0,75 MM X L: 1200 MM X C: 3000 MM - [MTCHBT101022] - {MP00000030} - (2)", "Chapa", 2.3,
               thickness=.75, length=500, width=300),
            mp("SUPORTE FIXAÇÃO", "CHAPA DE ACO CARBONO FF SAE 1006 E: 1,20 MM X L: 1200 MM X C: 3000 MM - [MTCHBT101018] - {MP00000039} - (84)", "Chapa", .133,
               thickness=1.2, length=500, width=300),
        ]

        cost_tubes = _aggregate_cost_items(tubes, "tube")
        cost_wires = _aggregate_cost_items(wires, "wire")
        cost_sheets = _aggregate_cost_items(sheets, "sheet")
        square = next(item for item in cost_tubes if "QUADRADO" in item["description"])
        wire = cost_wires[0]
        thin_sheet = next(item for item in cost_sheets if item["thickness"] == .75)

        self.assertEqual(square["description"], "TUBO QUADRADO 20x20x0,9mm")
        self.assertEqual(square["total_weight"], 1.25)
        self.assertEqual(wire["description"], "ARAME Ø5,0MM")
        self.assertEqual(wire["total_weight"], 5.977)
        self.assertEqual(thin_sheet["description"], "CHAPA DE AÇO CARBONO #0,75MM")
        self.assertEqual(thin_sheet["total_weight"], 3.5)

    def test_cost_groups_identical_stock_and_sums_weight_but_calc_keeps_cuts(self):
        tubes = [
            {"description": f"TUBO QUADRADO 20X20X0.9MM - HEI001P00{i}-00",
             "material": "TUBO ACO SAE 1006 20X20X0.9MM C6000 [SKU20]",
             "group_name": "Tubo Quadrado/Retangular", "item_type": "materia_prima",
             "width": 20, "depth": 20, "thickness": .9, "length": length,
             "quantity": qty, "unit_weight": weight, "total_weight": weight * qty,
             "unit_price": price, "total_price": round(price * qty, 2),
             "price_basis": {"weight": weight, "rate": 7.74, "factor": .7875, "ipi_pct": 3.25}}
            for i, length, qty, weight, price in ((1, 500, 2, .3, .6), (2, 750, 1, .45, .9))
        ]
        different_profile = {**tubes[0], "description": "TUBO QUADRADO 25X25X0.9MM - HEI001P003-00",
                             "material": "TUBO ACO SAE 1006 25X25X0.9MM C6000 [SKU25]",
                             "width": 25, "depth": 25}
        sheets = [
            {"description": f"CHAPA ACO 0.75MM {length}X{width} - P{i}",
             "material": "CHAPA ACO SAE 1008 0.75MM 1200X2000 [SHEET075]",
             "group_name": "Chapa", "item_type": "materia_prima",
             "length": length, "width": width, "thickness": .75,
             "quantity": 1, "unit_weight": weight, "total_weight": weight,
             "unit_price": cost, "total_price": cost,
             "price_basis": {"weight": weight, "rate": 7.02, "factor": 1, "ipi_pct": 0}}
            for i, length, width, weight, cost in ((1, 300, 200, .42, .42), (2, 450, 100, .18, .18))
        ]
        different_gauge = {**sheets[0], "description": "CHAPA ACO 1MM 300X200 - P4",
                           "material": "CHAPA ACO SAE 1008 1MM 1200X2000 [SHEET1]",
                           "thickness": 1}
        materials = [*tubes, different_profile, *sheets, different_gauge]
        cost_tubes = _aggregate_cost_items(materials[:3], "tube")
        cost_sheets = _aggregate_cost_items([*sheets, different_gauge], "sheet")
        self.assertEqual(len(cost_tubes), 2)
        tube20 = next(x for x in cost_tubes if "SKU20" in x["material"])
        self.assertEqual(tube20["description"], "TUBO QUADRADO 20X20X0.9MM")
        self.assertAlmostEqual(tube20["total_weight"], 1.05)
        self.assertAlmostEqual(tube20["cost_weight"], 1.05)
        self.assertAlmostEqual(tube20["aggregate_total_price"], 2.1)
        self.assertEqual(tube20["quantity"], 1)
        self.assertEqual(len(cost_sheets), 2)
        sheet075 = next(x for x in cost_sheets if x["thickness"] == .75)
        self.assertAlmostEqual(sheet075["total_weight"], .6)
        self.assertEqual(sheet075["description"], "CHAPA ACO 0.75MM")
        calc_groups = _split_items(materials)
        self.assertEqual(len(calc_groups["tube"]), 3)
        self.assertEqual(len(calc_groups["sheet"]), 3)
        self.assertEqual(sum(x["quantity"] for x in calc_groups["tube"]), 5)
        calc_cells = _calc_pages(calc_groups)[0]
        self.assertEqual([calc_cells[f"I{row}"] for row in range(17, 20)], [20, 20, 25])

    def test_cost_aggregates_only_identical_bought_materials_and_adds_quantity(self):
        items = [
            {"description": "DOBRADICA 30MM", "material": "DOBRADICA 30MM [SKU-A]",
             "group_name": "Ferragens", "item_type": "comprado", "unit": "un",
             "quantity": quantity, "unit_weight": .02, "total_weight": .02 * quantity,
             "unit_price": 1.5, "total_price": 1.5 * quantity}
            for quantity in (2, 3)
        ]
        distinct = {**items[0], "description": "DOBRADICA 40MM",
                    "material": "DOBRADICA 40MM [SKU-B]", "unit_price": 2.0, "total_price": 2.0}
        result = _aggregate_cost_items([*items, distinct], "bought")
        self.assertEqual(len(result), 2)
        same = next(x for x in result if "SKU-A" in x["material"])
        self.assertEqual(same["quantity"], 5)
        self.assertAlmostEqual(same["total_weight"], .1)
        self.assertEqual(same["aggregate_total_price"], 7.5)

    def test_failed_excel_export_removes_incomplete_template_copies(self):
        full = {"project": {"name": "Falha COM", "client": "Cliente",
                            "date": "2026-10-27"}, "materials": []}
        with patch("template_reports.EXPORTS_DIR", Path("C:/virtual/orcamento-exports")), \
                patch.object(Path, "mkdir"), patch.object(Path, "write_text"), \
                patch("template_reports.shutil.copy2"), \
                patch("template_reports.shutil.rmtree") as cleanup, \
                patch("template_reports._run_excel",
                      side_effect=RuntimeError("Excel COM indisponível")):
            with self.assertRaisesRegex(RuntimeError, "Excel COM indisponível"):
                export_template_reports(full, 1001, "planilhas")
        self.assertTrue(cleanup.called)
        self.assertTrue(cleanup.call_args.args[0].name.startswith("modelos_1001_"))
        self.assertTrue(cleanup.call_args.kwargs["ignore_errors"])

    def test_cost_export_preserves_unit_weight_precision_before_quantity(self):
        # CH. POSTE TROPERO #11: 0,011027 kg × 2 custa R$ 0,15.
        # Usar o total exibido de 0,0221 kg produziria R$ 0,16.
        plate = {"description": "CH. POSTE", "quantity": 2,
                 "total_weight": 0.0221, "unit_price": 0.0774,
                 "total_price": 0.15,
                 "price_basis": {"weight": 0.011027, "rate": 7.02, "factor": 1}}
        row = _cost_item(plate)
        self.assertAlmostEqual(row["cost_weight"], 0.022054)
        self.assertAlmostEqual(row["cost_weight"] * row["rate"], 0.15481908)
        self.assertNotEqual(round(row["total_weight"] * row["rate"], 2),
                            row["total_price"])
        no_basis = _cost_item({"description": "item manual", "quantity": 2,
                               "total_weight": 0.0221, "unit_price": 0.075,
                               "total_price": 0.15})
        self.assertIsNone(no_basis["cost_weight"])

    def test_paint_keeps_approved_kg_rate_in_cost_model(self):
        paint={'description':'Pintura a pó','group_name':'Pintura a Pó',
               'unit':'kg','quantity':0.08272,'total_weight':0.08272,
               'unit_price':25.03,'total_price':2.07}
        row=_cost_item(paint)
        self.assertEqual((row['rate'],row['factor']),(25.03,1.0))

    def test_psai_is_bought_and_never_written_in_calc(self):
        materials = [
            {"description": "PSAI lateral", "group_name": "Polímero/PSAI", "item_type": "materia_prima",
             "length": 500, "width": 250, "thickness": 1, "quantity": 2, "unit_price": 20},
            {"description": "Chapa aço", "group_name": "Chapa", "item_type": "materia_prima",
             "length": 100, "width": 50, "thickness": 1, "quantity": 3},
            {"description": "Corpo", "group_name": "Subconjunto", "item_type": "subconjunto"},
        ]
        groups = _split_items(materials)
        self.assertEqual([x["description"] for x in groups["bought"]], ["PSAI lateral"])
        self.assertEqual([x["description"] for x in groups["sheet"]], ["Chapa aço"])
        self.assertEqual(_calc_pages(groups)[0], {"A29": 100, "B29": 50, "C29": 1, "D29": 3})

    def test_more_than_eight_materials_produces_numbered_original_calcs(self):
        materials = [
            {"description": f"Chapa {i}", "group_name": "Chapa", "item_type": "materia_prima",
             "length": 100 + i, "width": 50, "thickness": 1, "quantity": 1,
             "unit_weight": 0.1, "total_weight": 0.1, "unit_price": 0.7, "total_price": 0.7}
            for i in range(10)
        ]
        materials += [
            {"description": f"Comprado {i}", "group_name": "Ferragens", "item_type": "comprado",
             "quantity": 1, "unit_price": 2, "total_price": 2}
            for i in range(25)
        ]
        full = {"project": {"name": "Paginação", "client": "Cliente", "date": "2026-10-15"},
                "materials": materials}
        with patch("template_reports._run_excel"):
            archive = export_template_reports(full, 999, "planilhas")
        with ZipFile(archive) as bundle:
            names = bundle.namelist()
        self.assertEqual(len(names), 3)
        self.assertEqual(sum(name.endswith(".xls") for name in names), 2)
        self.assertEqual(sum(name.endswith(".xlsx") for name in names), 1)
        self.assertTrue(all("MARKUP" not in name.upper() for name in names))
        self.assertEqual(xlrd.open_workbook(CALC_TEMPLATE).sheet_names(),
                         xlrd.open_workbook(next(archive.parent.glob("*.xls"))).sheet_names())
        payload = json.loads((archive.parent / "preenchimento.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["calculations"]), 2)
        self.assertEqual(payload["calculations"][0]["cells"]["A29"], 100)
        self.assertEqual(payload["calculations"][1]["cells"]["A29"], 108)
        self.assertEqual(len(payload["sections"]["sheet"]), 10)
        self.assertEqual(len(payload["sections"]["bought"]), 25)

    def test_photo_quote_keeps_wire_cuts_and_each_sheet_separate(self):
        wires = [
            {"description": name, "group_name": "Arame", "item_type": "materia_prima",
             "radius_diam": 4, "length": cut, "quantity": qty,
             "total_weight": .08 * qty, "unit_price": .4, "total_price": .4 * qty}
            for name, cut, qty in (("Contorno superior", 820, 1),
                                   ("Contorno frontal", 720, 1),
                                   ("Contorno inferior", 820, 1),
                                   ("Uniões laterais", 220, 2))
        ]
        sheets = [
            {"description": name, "group_name": "Chapa", "item_type": "materia_prima",
             "length": length, "width": width, "thickness": .75, "quantity": 1,
             "total_weight": .1, "unit_price": .7, "total_price": .7}
            for name, length, width in (("Lateral direita", 200, 150),
                                        ("Lateral esquerda", 200, 150),
                                        ("Tampa superior", 250, 75),
                                        ("Fundo traseiro", 250, 150),
                                        ("Base inferior", 250, 150),
                                        ("Divisória esquerda", 150, 100),
                                        ("Divisória direita", 150, 100))
        ]
        paint = {"description": "Pintura", "group_name": "Pintura a Pó",
                 "item_type": "materia_prima", "unit": "kg", "quantity": .09,
                 "total_weight": .09, "unit_price": 25.03, "total_price": 2.25}
        bought = [
            {"description": label, "group_name": "Outros Comprados",
             "item_type": "comprado", "quantity": qty, "unit_price": price,
             "total_price": qty * price}
            for label, qty, price in (("Ventosa", 2, 6.86), ("Adesivo", 1, .2))
        ]
        materials = [{"description": "Corpo", "item_type": "subconjunto"},
                     *wires, *sheets, paint, *bought]
        full = {"project": {"name": "Display de foto", "client": "Cliente",
                            "date": "2026-10-16"}, "materials": materials}
        with patch("template_reports._run_excel"):
            archive = export_template_reports(full, 998, "planilhas")
        payload = json.loads((archive.parent / "preenchimento.json").read_text(encoding="utf-8"))
        self.assertEqual(len(payload["calculations"]), 1)
        cells = payload["calculations"][0]["cells"]
        self.assertEqual([(cells[f"A{r}"], cells[f"B{r}"], cells[f"C{r}"])
                          for r in range(17, 21)],
                         [(4, 820, 1), (4, 720, 1), (4, 820, 1), (4, 220, 2)])
        self.assertEqual([cells[f"D{r}"] for r in range(29, 36)], [1] * 7)
        self.assertEqual([row["description"] for row in payload["sections"]["sheet"]],
                         [row["description"] for row in sheets])
        self.assertEqual([len(payload["sections"][key])
                          for key in ("wire", "sheet", "paint", "bought")],
                         [4, 7, 1, 2])
        with ZipFile(archive) as bundle:
            self.assertEqual(len(bundle.namelist()), 2)


if __name__ == "__main__":
    unittest.main()
