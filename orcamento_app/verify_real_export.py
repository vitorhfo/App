"""Inspect a filled company-template export against its source templates and app totals."""

import json
from pathlib import Path
import sys

import openpyxl
import xlrd

from app import get_project_full_data
from template_reports import CALC_TEMPLATE


def verify(folder: Path, project_id: int) -> None:
    payload = json.loads((folder / 'preenchimento.json').read_text(encoding='utf-8'))
    calc_paths = sorted(folder.glob('*.xls'))
    cost_paths = list(folder.glob('*.xlsx'))
    assert len(calc_paths) == len(payload['calculations']) > 0
    assert len(cost_paths) == 1

    original = xlrd.open_workbook(CALC_TEMPLATE)
    original_total = original.sheet_by_name('Total')
    original_errors = sum(cell.ctype == xlrd.XL_CELL_ERROR
                          for sheet in original.sheets() for row in sheet.get_rows()
                          for cell in row)
    changed_total = []
    for path in calc_paths:
        book = xlrd.open_workbook(path)
        assert book.sheet_names() == original.sheet_names(), path
        errors = sum(cell.ctype == xlrd.XL_CELL_ERROR
                     for sheet in book.sheets() for row in sheet.get_rows()
                     for cell in row)
        assert errors == original_errors, (path, errors, original_errors)
        for name in original.sheet_names():
            if name == 'Total':
                continue
            source, filled = original.sheet_by_name(name), book.sheet_by_name(name)
            assert (source.nrows, source.ncols) == (filled.nrows, filled.ncols), (path, name)
            assert all(source.cell_value(row, col) == filled.cell_value(row, col)
                       for row in range(source.nrows) for col in range(source.ncols)), (path, name)
        total = book.sheet_by_name('Total')
        changed_total.append(sum(total.cell_value(row, col) != original_total.cell_value(row, col)
                                 for row in range(original_total.nrows)
                                 for col in range(original_total.ncols)))
        assert changed_total[-1] > 0, path

    formulas = openpyxl.load_workbook(cost_paths[0], data_only=False)
    values = openpyxl.load_workbook(cost_paths[0], data_only=True)
    assert len(formulas.sheetnames) == len(values.sheetnames) == 2
    assert all(sheet.print_area and f'${sheet.max_row}' in str(sheet.print_area)
               for sheet in formulas), 'Área de impressão não cobre as linhas ampliadas'
    assert all(sum(cell.data_type == 'f' for row in sheet for cell in row) > 0
               for sheet in formulas), 'Fórmulas da planilha de custo ausentes'
    assert not [(sheet.title, cell.coordinate, cell.value)
                for sheet in values for row in sheet for cell in row if cell.data_type == 'e']

    expected = get_project_full_data(project_id)['markup_result']
    actual_mp = values.worksheets[0].cell(values.worksheets[0].max_row, 7).value
    actual_mc = values.worksheets[1].cell(values.worksheets[1].max_row, 7).value
    assert abs(actual_mp - expected['cost_mp']) < 0.005, (actual_mp, expected['cost_mp'])
    assert abs(actual_mc - expected['cost_mc']) < 0.005, (actual_mc, expected['cost_mc'])
    bought = payload['sections']['bought']
    bought_sheet = values.worksheets[1]
    populated_bought = sum(bool(bought_sheet.cell(row, 2).value)
                           for row in range(9, bought_sheet.max_row))
    assert len(bought) == populated_bought, (len(bought), populated_bought)
    print(f'{len(calc_paths)} CÁLCULO, abas originais, somente Total alterada: {changed_total}')
    print(f'CUSTO: MP {values.worksheets[0].max_row} linhas / R$ {actual_mp:.2f}; '
          f'comprados {values.worksheets[1].max_row} linhas / R$ {actual_mc:.2f}; '
          f'{len(bought)} comprados, fórmulas, impressão e sem erro de célula')


if __name__ == '__main__':
    verify(Path(sys.argv[1]), int(sys.argv[2]))
