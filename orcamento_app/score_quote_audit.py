"""Compare physical cuts in a completed CÁLCULO with a SCORE PDF import.

Every source row retains its workbook and cell. Geometry is grouped only to
calculate quantity differences; identical geometry is never called a duplicate.
"""

from collections import defaultdict
from pathlib import Path

import xlrd


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _key(row):
    if row['kind'] == 'sheet':
        # Rotation of a flat blank is the same cut, but its source row remains.
        row = {**row, 'length': max(_number(row.get('length')), _number(row.get('width'))),
               'width': min(_number(row.get('length')), _number(row.get('width')))}
    dimensions = [round(_number(row.get(field)), 4)
                  for field in ('length', 'width', 'depth', 'thickness', 'diameter')]
    if row['kind'] == 'sheet':
        # The hand-entered CÁLCULO uses whole millimetres; a PDF cut of
        # 1250.4 x 1170.4 is the same nominal blank for reconciliation.
        dimensions[:2] = [round(value) for value in dimensions[:2]]
    return (row['kind'], *dimensions)


def read_calculo_total(paths):
    """Read only filled cut rows from the untouched company Total layout."""
    records = []
    sections = (
        ('wire', range(16, 24), (0, 1, 2), ('diameter', 'length', 'quantity')),
        ('tube', range(16, 24), (8, 9, 10, 11, 12),
         ('width', 'depth', 'thickness', 'length', 'quantity')),
        ('sheet', range(28, 36), (0, 1, 2, 3),
         ('length', 'width', 'thickness', 'quantity')),
        ('round', range(28, 36), (9, 10, 11, 12),
         ('diameter', 'thickness', 'length', 'quantity')),
    )
    for path in map(Path, paths):
        book = xlrd.open_workbook(str(path), on_demand=True)
        sheet = book.sheet_by_name('Total')
        for kind, indexes, columns, fields in sections:
            for index in indexes:
                if index >= sheet.nrows:
                    continue
                record = {field: _number(sheet.cell_value(index, col))
                          for field, col in zip(fields, columns)}
                if record.get('quantity', 0) <= 0 or record.get('length', 0) <= 0:
                    continue
                if kind == 'sheet' and record['thickness'] > 10 and record['width'] <= 10:
                    record['width'], record['thickness'] = record['thickness'], record['width']
                record.update(kind=kind, source=f'{path.name}:Total!{index + 1}',
                              workbook=str(path))
                records.append(record)
        book.release_resources()
    return records


def compare_cuts(manual_rows, materials):
    """Return grouped differences with all distinct source rows attached."""
    manual = defaultdict(list)
    scripted = defaultdict(list)
    for row in manual_rows:
        manual[_key(row)].append(row)
    groups = {'Arame': 'wire', 'Chapa': 'sheet',
              'Tubo Quadrado/Retangular': 'tube', 'Tubo Redondo': 'round'}
    for item in materials:
        if item.get('item_type') != 'materia_prima':
            continue
        kind = groups.get(item.get('group_name'))
        if not kind:
            continue
        row = dict(kind=kind, length=item.get('drawing_length') or item.get('length'),
                   width=item.get('width'), depth=item.get('depth'),
                   thickness=item.get('thickness'), diameter=item.get('radius_diam'))
        if row['length']:
            scripted[_key(row)].append(item)
    differences = []
    for key in sorted(manual.keys() | scripted.keys()):
        sources, items = manual[key], scripted[key]
        mq = sum(row['quantity'] for row in sources)
        sq = sum(item['quantity'] for item in items)
        if abs(mq - sq) < 1e-6:
            continue
        kind, length, width, depth, thickness, diameter = key
        differences.append(dict(kind=kind, length=length, width=width, depth=depth,
                                thickness=thickness, diameter=diameter,
                                manual_quantity=mq, script_quantity=sq,
                                delta=mq-sq,
                                manual_sources=[r['source'] for r in sources],
                                script_items=[f'{x.get("drawing_id")}: {x.get("description")}'
                                              for x in items]))
    return differences
