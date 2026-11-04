"""Read-only validation of the Hellmann's company-template export."""

from pathlib import Path
import math
import sys

from openpyxl import load_workbook
import xlrd


folder = Path(sys.argv[1])
calc_path = next(folder.glob("*.xls"))
cost_path = next(folder.glob("*.xlsx"))

calc = xlrd.open_workbook(calc_path)
total = calc.sheet_by_name("Total")
wire = [(total.cell_value(r, 0), total.cell_value(r, 1), total.cell_value(r, 2))
        for r in range(16, 24) if isinstance(total.cell_value(r, 0), (int, float))
        and total.cell_value(r, 0) > 0]
sheet = [(total.cell_value(r, 0), total.cell_value(r, 1), total.cell_value(r, 2), total.cell_value(r, 3))
         for r in range(28, 36) if isinstance(total.cell_value(r, 0), (int, float))
         and total.cell_value(r, 0) > 0]
assert len(wire) == 4, wire
assert sum(row[2] for row in wire) == 5, wire
assert all(row[0] == 4 for row in wire), wire
assert len(sheet) == 7, sheet
assert all(row[2] == .75 and row[3] == 1 for row in sheet), sheet

book = load_workbook(cost_path, read_only=True, data_only=True)
mp, bought = book.worksheets[:2]
rows = list(mp.iter_rows(min_col=2, max_col=7, values_only=True))
bought_rows = list(bought.iter_rows(min_col=2, max_col=7, values_only=True))
required = ("Contorno superior", "Contorno frontal", "Contorno inferior",
            "União lateral do contorno", "Lateral direita", "Lateral esquerda",
            "Tampa superior", "Fundo traseiro", "Base inferior",
            "Divisória interna esquerda", "Divisória interna direita",
            "Pintura a pó azul escuro")
for label in required:
    hits = [(i + 1, row) for i, row in enumerate(rows) if row[0] == label]
    assert len(hits) == 1, (label, hits)
    i, row = hits[0]
    assert row[1] is not None and row[5] is not None, (label, i, row)
    print("MP", i, label, "kg", row[1], "R$", row[5])
for label in ("Ventosa 55 mm com botão", "Adesivo vinil impresso HELLMANN’S 130 × 55 mm"):
    hits = [(i + 1, row) for i, row in enumerate(bought_rows) if row[0] == label]
    assert len(hits) == 1, (label, hits)
    i, row = hits[0]
    assert row[1] and row[5] is not None, (label, i, row)
    print("MC", i, label, "qty", row[1], "R$", row[5])

for ws in book.worksheets:
    errors = [(c.coordinate, c.value) for row in ws for c in row if c.data_type == "e"]
    assert not errors, (ws.title, errors[:10])
print("CÁLCULO", calc_path.name, "sheets", calc.sheet_names(), "wire", wire, "sheet", sheet)
print("CUSTO", cost_path.name, "sheets", book.sheetnames)
book.close()
