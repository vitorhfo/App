"""Complete saved BOM wires from a code-matched child PDF and its AI review.

The parent list supplies the quantity and code. A child variant table supplies
the developed cut. Its A/B dimensions describe the bend and are never charged.
"""

import re
from pathlib import Path

import pymupdf

from ai_apply_dimensions import _backup_database, _has_prior_change
from ai_pdf_review import _name, load_review, resolve_pdf
from database import get_connection


def parse_coded_wire_table(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start = None
    for i in range(len(lines) - 3):
        if not (re.fullmatch(r'C.DIGO', lines[i], re.I)
                and lines[i + 1].upper() == 'NOMINAL'):
            continue
        if (re.fullmatch(r'MEDIDA\s*["“]?A["”]?\s+MEDIDA\s*["“]?B["”]?',
                         lines[i + 2], re.I)
                and lines[i + 3].upper() == 'COMPRIMENTO'):
            start = i + 4
            break
        if (i + 4 < len(lines)
                and re.fullmatch(r'MEDIDA\s*["“]?A["”]?', lines[i + 2], re.I)
                and re.fullmatch(r'MEDIDA\s*["“]?B["”]?', lines[i + 3], re.I)
                and lines[i + 4].upper() == 'COMPRIMENTO'):
            start = i + 5
            break
    if start is None:
        return {}
    material = next((line.replace('�', 'Ø') for line in lines[start:]
                     if re.search(r'\bARAME\b', line, re.I)), '')
    diameter = re.search(r'[Øø]\s*(\d+(?:[,.]\d+)?)\s*mm\b', material, re.I)
    if not diameter:
        return {}
    rows = {}
    for i in range(start, len(lines) - 4, 5):
        code, nominal, measure_a, measure_b, cut_length = lines[i:i + 5]
        if not re.fullmatch(r'\d{3,12}', code):
            break
        if not all(re.fullmatch(r'\d+(?:[,.]\d+)?', value)
                   for value in (measure_a, measure_b, cut_length)):
            return {}
        cut = float(cut_length.replace(',', '.'))
        if not nominal or cut <= 0 or code in rows:
            return {}
        rows[code] = {'nominal': nominal, 'cut_length': cut,
                      'diameter': float(diameter.group(1).replace(',', '.')),
                      'material': material}
    return rows


def coded_wire_candidates(project_id, materials=None):
    """Require exact BOM code, child drawing title, PDF row and AI agreement."""
    conn = get_connection()
    try:
        project = conn.execute('SELECT folder_path FROM projects WHERE id=?',
                               (project_id,)).fetchone()
        if project is None:
            raise ValueError('Projeto não encontrado')
        if materials is None:
            materials = [dict(row) for row in conn.execute(
                'SELECT * FROM materials WHERE project_id=?', (project_id,))]
        blocked = {row['id'] for row in materials
                   if (row.get('item_type') == 'subconjunto'
                       or row.get('group_name') not in ('Outros Comprados', 'Arame')
                       or not str(row.get('raw_code') or '').isdigit()
                       or (row.get('price_source') or '').startswith('Ajuste manual')
                       or any((row.get(field) or 0) > 0
                              for field in ('length', 'radius_diam'))
                       or any(_has_prior_change(conn, row['id'], field)
                              for field in ('group_name', 'item_type', 'material',
                                            'length', 'radius_diam')))}
        jobs = [dict(row) for row in conn.execute('''SELECT path,page,model
            FROM ai_review_jobs WHERE project_id=? AND state='done'
            ORDER BY path,page,model''', (project_id,))]
    finally:
        conn.close()
    found = {}
    for job in jobs:
        try:
            pdf = resolve_pdf(project['folder_path'] or '', job['path'])
            review = load_review(project_id, job['path'], job['page'], pdf, job['model'])
            if not review:
                continue
            with pymupdf.open(pdf) as document:
                table = parse_coded_wire_table(document[job['page'] - 1].get_text())
        except (OSError, ValueError, IndexError):
            continue
        if not table:
            continue
        title = _name(Path(job['path']).stem)
        for item in materials:
            if item['id'] in blocked or item['raw_code'] not in table:
                continue
            parent_name = _name(item['description'].split(' - ', 1)[0])
            if len(title.split()) < 2 or parent_name != title:
                continue
            row = table[item['raw_code']]
            agreed = [ai for ai in review['result'].get('items') or []
                      if str(ai.get('item_number') or '') == item['raw_code']
                      and abs(float(ai.get('length') or 0) - row['cut_length']) < .01
                      and abs(float(ai.get('radius_diam') or 0) - row['diameter']) < .01]
            if len(agreed) != 1:
                continue
            candidate = {'item': item, **row,
                         'source_page': f"{job['path']}#page={job['page']}",
                         'model': job['model'], 'evidence': agreed[0].get('evidence') or ''}
            previous = found.get(item['id'])
            if previous and (previous['cut_length'], previous['diameter']) != (
                    candidate['cut_length'], candidate['diameter']):
                blocked.add(item['id'])
                found.pop(item['id'], None)
            elif item['id'] not in blocked:
                found[item['id']] = candidate
    return [candidate for item_id, candidate in found.items() if item_id not in blocked]


def apply_coded_wire_candidates(project_id, candidates):
    if not candidates:
        return 0
    from app import MaterialUpdate, update_material

    _backup_database(project_id)
    for candidate in candidates:
        item = candidate['item']
        old_issue = item.get('pending_issue') or ''
        issue = old_issue.replace(
            'Desenho da peça não localizado; conferir dimensões e peso.', '').strip()
        # Some older saved records contain replacement characters; the new
        # evidence is explicit even when their old warning cannot be removed.
        if 'n�o localizado' in issue:
            issue = ''
        note = (f"Corte da variante código {item['raw_code']} confirmado no PDF "
                f"{candidate['source_page']} e pela IA {candidate['model']}: "
                f"{candidate['cut_length']:g} mm, Ø{candidate['diameter']:g}. "
                f"Medidas A/B são apenas da dobra. Evidência: {candidate['evidence'][:300]}")
        update_material(project_id, item['id'], MaterialUpdate(
            group_name='Arame', item_type='materia_prima',
            material=candidate['material'], length=candidate['cut_length'],
            radius_diam=candidate['diameter'], pending_issue=issue,
            observation=' '.join(x for x in (item.get('observation') or '', note) if x)))
    return len(candidates)
