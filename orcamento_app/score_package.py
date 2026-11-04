"""Material lists and cut tables from SCORE GROUP drawing packages.

These packages place a continued, twelve-column BOM at the end of one PDF.
Rows without an ITEM number inherit the last numbered assembly, even when
the continuation starts on the next page. Six-column cut tables elsewhere in
the PDF describe the actual stock cuts of selected welded parts.
"""

import re


CODE = re.compile(r'\bAMB[ _]+\d+[ _]+\d+[ _]+\d+[ _]+(?:ASM|PRT)[ _]+\d+[A-Z]?\b', re.I)


def drawing_code(value):
    match = CODE.search(str(value or '').replace('\n', ' '))
    return '_'.join(match.group().split()).upper() if match else ''


def _number(value):
    try:
        return float(str(value or '').strip().replace(',', '.'))
    except ValueError:
        return 0.0


def split_sheet_flat_bar(body):
    """Read a SCORE detail that explicitly names a sheet plus a flat bar.

    The third isolated drawing dimension is accepted as the bar cut only
    when it immediately follows the sheet's two overall dimensions. Other
    dimensions and generic welded details must remain unresolved.
    """
    match = re.search(
        r'(\d+(?:[,.]\d+)?)\s*[xX]\s*(\d+(?:[,.]\d+)?)\s*[xX]\s*'
        r'\d+(?:[,.]\d+)?\s*\(\s*Chapa\s*(\d+(?:[,.]\d+)?)\s*\+\s*'
        r'ferro\s+chato\s*(\d+(?:[,.]\d+)?)\s*[xX]\s*(\d+(?:[,.]\d+)?)\s*\)',
        body, re.I)
    if not match:
        return None
    sheet_width, sheet_length, sheet_gauge, bar_gauge, bar_width = map(_number, match.groups())
    lead = re.search(
        rf'\n\s*{sheet_width:g}\s*\n\s*{sheet_length:g}\s*\n\s*(\d+(?:[,.]\d+)?)\s*\n',
        body)
    bar_length = _number(lead.group(1)) if lead else 0
    if not (0 < sheet_gauge <= 10 and 0 < bar_gauge <= 10 and
            0 < bar_width < sheet_width and 0 < bar_length <= sheet_width):
        return None
    return {'sheet_length': sheet_length, 'sheet_width': sheet_width,
            'sheet_gauge': sheet_gauge, 'bar_length': bar_length,
            'bar_width': bar_width, 'bar_gauge': bar_gauge}


def _distinct_bom_pages(rows):
    """Keep the most complete copy of a repeated drawing's whole BOM.

    A later SCORE appendix may repeat the opening list with extra fasteners.
    Detail lists with another first drawing remain independent. Conflicting
    revisions are not silently collapsed: only a strict subset/equal copy is.
    """
    pages = {}
    for row in rows:
        pages.setdefault(row['page'], []).append(row)
    page_order = list(pages)
    removed = set()
    for index, first_page in enumerate(page_order):
        if first_page in removed:
            continue
        first_rows = pages[first_page]
        if len(first_rows) < 5 or first_rows[0]['item_num'] != '1':
            continue
        first_code = first_rows[0]['drawing_id']
        if not first_code:
            continue
        for later_page in page_order[index + 1:]:
            if later_page in removed:
                continue
            later_rows = pages[later_page]
            if (len(later_rows) < 5 or later_rows[0]['item_num'] != '1' or
                    later_rows[0]['drawing_id'] != first_code):
                continue
            signature = lambda item: tuple((key, str(value)) for key, value in item.items()
                                           if key not in ('page', 'revision'))
            earlier = {signature(item) for item in first_rows}
            later = {signature(item) for item in later_rows}
            if earlier <= later or later <= earlier:
                first_rev = max((item.get('revision', 0) for item in first_rows), default=0)
                later_rev = max((item.get('revision', 0) for item in later_rows), default=0)
                if later_rev > first_rev or (later_rev == first_rev and len(later) > len(earlier)):
                    pages[first_page] = later_rows
                    first_rows = later_rows
                removed.add(later_page)
    return [row for page in page_order if page not in removed for row in pages[page]]


def _reconcile_detail_weight_units(pdf, rows):
    """Convert a detail table's grams only when it matches its kg parent.

    Some SCORE tables print WEIGHT (Kg) but contain gram figures. A large
    number alone is insufficient evidence: compare the weighted child sum to
    the unit weight of the assembly named in that page's own title block.
    """
    parents = {row['drawing_id']: row['unit_weight'] for row in rows
               if row['item_num'] and '_ASM_' in row['drawing_id']
               and row['unit_weight'] > 0}
    by_page = {}
    for row in rows:
        if row.get('owner_assembly'):
            by_page.setdefault(row['owner_assembly'], []).append(row)
    for parent_code, page_rows in by_page.items():
        parent_weight = parents.get(parent_code, 0)
        if parent_weight <= 0:
            continue
        subtotal = sum(row['quantity'] * row['unit_weight'] for row in page_rows
                       if row['item_num'] and row['unit_weight'] > 0)
        if (subtotal > 100 * parent_weight and
                abs(subtotal / 1000 - parent_weight) <= max(.1, parent_weight * .02)):
            for row in page_rows:
                if row['unit_weight'] > 0:
                    row['unit_weight'] /= 1000
                    row['weight_note'] = (
                        f'Peso em gramas convertido para kg: soma da lista '
                        f'{subtotal / 1000:.3f} kg confere com o conjunto '
                        f'{parent_code} ({parent_weight:.3f} kg).')
    return rows


def read_score_package(pdf):
    """Return (BOM rows, cut tables) only for a verified SCORE table layout."""
    bom = []
    cuts = {}
    for page_number, page in enumerate(pdf, 1):
        body = page.get_text()
        if 'DIMENS' in body.upper() and 'WEIGHT' in body.upper() and 'FINISHING' in body.upper():
            heading = body.split('ITEM', 1)[0]
            owner = drawing_code(heading)
            owner = owner if '_ASM_' in owner else ''
            revision_match = re.search(r'DESCRI[^\n]*\n[^\n]+\n(\d{1,3})\nPACOTE', heading, re.I)
            revision = int(revision_match.group(1)) if revision_match else 0
            clip = (page.rect.width * .03, page.rect.height * .25,
                    page.rect.width * .98, page.rect.height * .95)
            for table in page.find_tables(clip=clip, strategy='lines').tables:
                if table.col_count != 12:
                    continue
                cells = table.extract()
                head = cells[0]
                if not (head[0] == 'ITEM' and
                        re.sub(r'\s+', '', str(head[1])).upper() == 'QTD.' and
                        'DRW' in str(head[2]) and 'WEIGHT' in str(head[8])):
                    continue
                for row in cells[1:]:
                    quantity = _number(row[1])
                    description = ' '.join(str(row[4] or '').split())
                    if (description.upper().startswith('VER FOLHA DE INFORMA') or
                            description.upper().startswith('ACESS')):
                        description = ' '.join(str(row[2] or '').split())
                    if not quantity or not description:
                        continue
                    bom.append(dict(item_num=str(row[0] or '').strip(),
                                    quantity=quantity, drawing_id=drawing_code(row[2]),
                                    description=description,
                                    material=' '.join(str(row[5] or '').split()),
                                    dimensions=' '.join(str(row[6] or '').split()),
                                    complementary=' '.join(str(row[7] or '').split()),
                                    unit_weight=_number(row[8]),
                                    finishing=' '.join(str(row[11] or '').split()),
                                    page=page_number, owner_assembly=owner,
                                    revision=revision))
        if 'LENGTH' not in body or 'DESCRIPTION' not in body or not CODE.search(body):
            continue
        clip = (page.rect.width * .437, page.rect.height * .297,
                page.rect.width * .974, page.rect.height * .742)
        for table in page.find_tables(clip=clip, strategy='lines').tables:
            if table.col_count != 6:
                continue
            cells = table.extract()
            if not any(row[0] == 'ITEM' and row[1] == 'QTD.' and row[5] == 'LENGTH'
                       for row in cells):
                continue
            rows = []
            for row in cells:
                quantity = _number(row[1])
                material = ' '.join(str(row[3] or '').split())
                if not quantity or not material:
                    continue
                rows.append(dict(item_num=str(row[0] or '').strip(),
                                 quantity=quantity, material=material,
                                 length=_number(row[5])))
            if not rows:
                continue
            # A thin grid line can erase the ITEM cell in this table. Recover
            # only a complete, descending n..1 sequence anchored at both ends.
            total = len(rows)
            if all(not row['item_num'] or row['item_num'] == str(total - index)
                   for index, row in enumerate(rows)) and rows[0]['item_num'] == str(total) \
                    and rows[-1]['item_num'] == '1':
                for index, row in enumerate(rows):
                    row['item_num'] = str(total - index)
            elif any(not row['item_num'] for row in rows):
                continue
            codes = {drawing_code(match.group()) for match in CODE.finditer(body)}
            if len(codes) == 1:
                cuts[next(iter(codes))] = dict(page=page_number, rows=rows)
    bom = _distinct_bom_pages(bom)
    return _reconcile_detail_weight_units(pdf, bom), cuts
