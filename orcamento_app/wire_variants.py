"""Read parameterized wire drawings without inventing a project quantity.

The column MEDIDA A is the formed nominal size. COMPRIMENTO is the raw
developed length. These alternatives are kept outside the priced BOM until
the project specifies which code and quantity are required.
"""

import re
from collections import defaultdict

import pymupdf


def parse_parameterized_wire_table(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start = next((i + 4 for i in range(len(lines) - 3)
                  if re.fullmatch(r'C.DIGO', lines[i], re.I)
                  and lines[i + 1].upper() == 'NOMINAL'
                  and re.fullmatch(r'MEDIDA\s*["“]?A["”]?', lines[i + 2], re.I)
                  and lines[i + 3].upper() == 'COMPRIMENTO'), None)
    if start is None:
        return []
    material_line = next((line for line in lines[start:] if re.search(r'\bARAME\b', line, re.I)), '')
    diameter = re.search(r'[Øø�]\s*(\d+(?:[,.]\d+)?)\s*mm\b', material_line, re.I)
    if not diameter:
        return []
    result = []
    for i in range(start, len(lines) - 3, 4):
        code, nominal, measure_a, cut_length = lines[i:i + 4]
        if not re.fullmatch(r'\d{3,12}', code):
            break
        if not re.fullmatch(r'\d+(?:[,.]\d+)?\s*[xX×]\s*\d+(?:[,.]\d+)?\s*h?', nominal, re.I):
            return []
        if not re.fullmatch(r'\d+(?:[,.]\d+)?', measure_a):
            return []
        if not re.fullmatch(r'\d+(?:[,.]\d+)?', cut_length):
            return []
        a = float(measure_a.replace(',', '.'))
        cut = float(cut_length.replace(',', '.'))
        if a <= 0 or cut <= 0:
            return []
        result.append({'code': code, 'nominal': nominal, 'measure_a': a,
                       'cut_length': cut, 'diameter': float(diameter.group(1).replace(',', '.')),
                       'material': material_line.replace('�', 'Ø'), 'quantity': None})
    if not result or len({row['code'] for row in result}) != len(result):
        return []
    return result


def insert_wire_variants(conn, project_id, variants):
    """Store cut alternatives separately from charged physical BOM items."""
    inserted = 0
    for variant in variants:
        existing = conn.execute('''SELECT measure_a,cut_length,diameter FROM wire_variants
            WHERE project_id=? AND source_page=? AND code=?''',
            (project_id, variant['source_page'], variant['code'])).fetchone()
        if existing and any(abs(float(existing[field]) - float(variant[field])) > .01
                            for field in ('measure_a', 'cut_length', 'diameter')):
            # The source changed after registration. Keep the saved variant and
            # its quantity until a person reconciles the revised drawing.
            continue
        cur = conn.execute('''INSERT OR IGNORE INTO wire_variants
            (project_id,source_page,code,description,nominal,measure_a,
             cut_length,diameter,material,quantity,ai_agreement_count)
            VALUES (?,?,?,?,?,?,?,?,?,NULL,?)''',
            (project_id, variant['source_page'], variant['code'], variant['description'],
             variant['nominal'], variant['measure_a'], variant['cut_length'],
             variant['diameter'], variant['material'], variant.get('ai_agreement_count', 0)))
        inserted += cur.rowcount
        # A later AI agreement may strengthen the reading, but never changes
        # an earlier manual quantity or the original PDF dimensions.
        conn.execute('''UPDATE wire_variants SET ai_agreement_count=MAX(ai_agreement_count,?)
            WHERE project_id=? AND source_page=? AND code=?''',
            (variant.get('ai_agreement_count', 0), project_id,
             variant['source_page'], variant['code']))
    return inserted


def saved_ai_wire_variants(project_id, conn, path=None, page=None):
    """Re-read only completed AI pages and require agreement with PDF text."""
    from ai_pdf_review import load_review, resolve_pdf

    project = conn.execute('SELECT folder_path FROM projects WHERE id=?', (project_id,)).fetchone()
    if not project or not project['folder_path']:
        return []
    if path is None:
        rows = conn.execute('''SELECT path,page,model FROM ai_review_jobs
            WHERE project_id=? AND state='done' ORDER BY path,page,model''',
            (project_id,)).fetchall()
    else:
        rows = conn.execute('''SELECT path,page,model FROM ai_review_jobs
            WHERE project_id=? AND path=? AND page=? AND state IN ('done','running')
            ORDER BY model''', (project_id, path, page)).fetchall()
    collected = {}
    agreeing = defaultdict(set)
    for job in rows:
        try:
            pdf = resolve_pdf(project['folder_path'], job['path'])
            review = load_review(project_id, job['path'], job['page'], pdf, job['model'])
            if not review:
                continue
            with pymupdf.open(pdf) as doc:
                text = doc[job['page'] - 1].get_text()
        except (OSError, ValueError, IndexError):
            continue
        source_page = f"{job['path'].replace(chr(92), '/')}#page={job['page']}"
        variants = parse_parameterized_wire_table(text)
        ai_items = review['result'].get('items') or []
        for variant in variants:
            key = (source_page.casefold(), variant['code'])
            candidate = {**variant, 'source_page': source_page, 'description': pdf.stem}
            if key in collected and any(candidate[field] != collected[key][field]
                                        for field in ('cut_length', 'diameter', 'measure_a')):
                continue
            collected[key] = candidate
            if any(str(item.get('item_number') or '') == variant['code']
                   and abs(float(item.get('length') or 0) - variant['cut_length']) < .01
                   and abs(float(item.get('radius_diam') or 0) - variant['diameter']) < .01
                   for item in ai_items):
                agreeing[key].add(job['model'])
    return [{**variant, 'ai_agreement_count': len(agreeing[key])}
            for key, variant in collected.items()]


def sync_ai_wire_page(project_id, path, page):
    """Strengthen an imported table as each automatic AI review completes."""
    from ai_apply_dimensions import _backup_database
    from database import get_connection

    conn = get_connection()
    try:
        variants = saved_ai_wire_variants(project_id, conn, path, page)
        existing = {(row['source_page'].casefold(), row['code']): row['ai_agreement_count']
                    for row in conn.execute('''SELECT source_page,code,ai_agreement_count
                        FROM wire_variants WHERE project_id=?''', (project_id,))}
        changed = [variant for variant in variants
                   if variant['ai_agreement_count'] > existing.get(
                       (variant['source_page'].casefold(), variant['code']), -1)]
        if changed:
            _backup_database(project_id)
            insert_wire_variants(conn, project_id, changed)
            conn.commit()
        return len(changed)
    finally:
        conn.close()
