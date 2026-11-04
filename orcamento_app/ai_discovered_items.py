"""Stage physical parts found only by completed AI reviews, outside the quote."""

import hashlib
import json
from difflib import SequenceMatcher

from ai_apply_dimensions import (DIMENSIONS, FIELDS_BY_GROUP, _allowed_fields,
                                 _evidence_supports, _same_pdf)
from ai_pdf_review import (_name, _part_identity, cross_page_matches,
                           is_polymer_material, load_review, resolve_pdf)
from database import get_connection


def _group(ai):
    material = _name(ai.get('material') or ai.get('description'))
    families = sum(bool(token in material) for token in ('ARAME', 'TUBO', 'CHAPA'))
    if is_polymer_material(material):
        return 'Polímero/PSAI', 'comprado'
    if families > 1:
        return None, None
    if 'ARAME' in material:
        return 'Arame', 'materia_prima'
    if 'TUBO' in material:
        return ('Tubo Redondo' if (any(word in material for word in ('REDONDO', 'RED.', 'CIRCULAR'))
                                  or (ai.get('radius_diam') and not ai.get('width') and not ai.get('depth')))
                else 'Tubo Quadrado/Retangular'), 'materia_prima'
    if 'CHAPA' in material:
        return 'Chapa', 'materia_prima'
    return None, None


def _key(path, ai, group):
    shape = [round(float(ai.get(field) or 0), 3) for field in FIELDS_BY_GROUP[group]]
    raw = json.dumps([path.replace('\\', '/').casefold(),
                      _part_identity(ai.get('description')), group, shape],
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def discovered_candidates(project_id, materials=None):
    """Only measured, identifiable physical parts absent from this PDF's BOM."""
    conn = get_connection()
    try:
        project = conn.execute('SELECT folder_path FROM projects WHERE id=?',
                               (project_id,)).fetchone()
        if not project:
            raise ValueError('Projeto não encontrado')
        if materials is None:
            materials = [dict(row) for row in conn.execute(
                'SELECT * FROM materials WHERE project_id=? AND item_type!=?',
                (project_id, 'subconjunto'))]
        jobs = [dict(row) for row in conn.execute('''SELECT path,page,model
            FROM ai_review_jobs WHERE project_id=? AND state='done'
            ORDER BY path,page,model''', (project_id,))]
        saved = {row['identity_key'] for row in conn.execute(
            'SELECT identity_key FROM ai_discovered_items WHERE project_id=?',
            (project_id,))}
    finally:
        conn.close()
    found = {}
    for job in jobs:
        path = job['path']
        try:
            pdf = resolve_pdf(project['folder_path'] or '', path)
            review = load_review(project_id, path, job['page'], pdf, job['model'])
        except (OSError, ValueError):
            continue
        if not review:
            continue
        same_pdf = [item for item in materials
                    if _same_pdf(item.get('source_page'), path)]
        for ai in review['result'].get('items') or []:
            group, item_type = _group(ai)
            if (not group or ai.get('item_type') == 'subconjunto'
                    or not _part_identity(ai.get('description'))
                    or not (ai.get('evidence') or '').strip()):
                continue
            identity = _part_identity(ai['description'])
            # A saved part with the same name but conflicting measurements is
            # a discrepancy to inspect, not permission to add a second charge.
            if any(item.get('group_name') == group and
                   SequenceMatcher(None, identity,
                       _part_identity(item.get('description'))).ratio() >= .82
                   for item in materials):
                continue
            if cross_page_matches(ai, same_pdf):
                continue
            dims = {field: float(ai[field]) for field in DIMENSIONS
                    if isinstance(ai.get(field), (int, float)) and ai[field] > 0}
            if not dims:
                continue
            key = _key(path, ai, group)
            if key in saved or key in found:
                continue
            prototype = {'group_name': group, 'unit_area': 0}
            required = FIELDS_BY_GROUP[group]
            ready = (group != 'Polímero/PSAI'
                     and set(required).issubset(dims)
                     and set(required).issubset(_allowed_fields(prototype, ai))
                     and all(_evidence_supports(field, dims[field], ai['evidence'])
                             for field in required))
            found[key] = {
                'identity_key': key, 'source_page': f"{path}#page={job['page']}",
                'description': ai['description'].strip(), 'group_name': group,
                'item_type': item_type, 'material': (ai.get('material') or '').strip(),
                'dimensions_json': json.dumps(dims, ensure_ascii=False),
                'evidence': ai['evidence'].strip(),
                'dimension_basis': ai.get('dimension_basis') or '',
                'ready': int(bool(ready)),
            }
    return list(found.values())


def save_discovered_candidates(project_id, candidates):
    if not candidates:
        return 0
    conn = get_connection()
    try:
        count = 0
        for row in candidates:
            cur = conn.execute('''INSERT OR IGNORE INTO ai_discovered_items
                (project_id,identity_key,source_page,description,group_name,
                 item_type,material,dimensions_json,evidence,dimension_basis,ready)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                (project_id, *(row[field] for field in (
                    'identity_key', 'source_page', 'description', 'group_name',
                    'item_type', 'material', 'dimensions_json', 'evidence',
                    'dimension_basis', 'ready'))))
            count += cur.rowcount
        conn.commit()
        return count
    finally:
        conn.close()
