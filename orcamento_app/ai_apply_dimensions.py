"""Complete missing part dimensions from a linked, auditable AI PDF reading."""

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import database
from ai_pdf_review import _name, _side_base, cross_page_matches
from mass_math import calculated_weight


DIMENSIONS = ('length', 'width', 'depth', 'thickness', 'radius_diam')
FIELDS_BY_GROUP = {
    'Chapa': ('length', 'width', 'thickness'),
    'Polímero/PSAI': ('length', 'width', 'thickness'),
    'Arame': ('length', 'radius_diam'),
    'Tubo Quadrado/Retangular': ('length', 'width', 'depth', 'thickness'),
    'Tubo Redondo': ('length', 'radius_diam', 'thickness'),
}
DIMENSION_PENDING = 'Conferir cotas/peso no desenho; extração parcial.'


def _source_matches(source, path, page):
    source = (source or '').replace('\\', '/')
    expected = f"{path.replace(chr(92), '/')}#page={page}"
    return source.casefold() == expected.casefold()


def _same_pdf(source, path):
    return (source or '').replace('\\', '/').split('#page=', 1)[0].casefold() == (
        path.replace('\\', '/').casefold())


def _has_prior_change(conn, item_id, field):
    """Old audit rows have no actor label; conservatively treat them as manual."""
    for row in conn.execute('SELECT before_json,after_json FROM material_changes '
                            'WHERE material_id=?', (item_id,)):
        try:
            before, after = json.loads(row[0]), json.loads(row[1])
        except (TypeError, ValueError):
            return True
        if before.get(field) != after.get(field):
            return True
    return False


def _item_matches(ai_item, material, all_materials, all_ai):
    description = _side_base(ai_item.get('description'))
    target = _side_base(material['description'])
    if not description or not target:
        return False
    similarity = SequenceMatcher(None, description, target).ratio()
    if similarity < .72 and description not in target and target not in description:
        return False
    # A cut table can repeat the same profile. The row number must identify a
    # distinct cut; a fuzzy match cannot assign its length safely.
    if len(all_ai) > 1:
        number = _name(ai_item.get('item_number'))
        cut = re.search(r'\bCORTE\s+(\d+)\b', _name(material['description']))
        if cut:
            return number == cut.group(1)
        competitors = [other for other in all_materials if other['id'] != material['id']
                       and SequenceMatcher(None, description,
                                           _side_base(other['description'])).ratio() >= .72]
        if competitors:
            return False
    return True


def _allowed_fields(item, ai_item):
    group = item['group_name']
    fields = FIELDS_BY_GROUP.get(group, ())
    basis = (ai_item.get('dimension_basis') or '').lower()
    if not fields or not (ai_item.get('evidence') or '').strip():
        return ()
    warnings = ' '.join(ai_item.get('warnings') or []).upper()
    if group == 'Chapa' and re.search(r'DOBR|EXTERN|DESENVOLVIMENTO', warnings):
        # A model may label a folded part "corte" while admitting that it
        # extracted outside dimensions. Its blank size remains unresolved.
        return ()
    if group == 'Chapa' and basis not in ('corte', 'planificacao'):
        return ()
    if group == 'Polímero/PSAI' and basis not in ('corte', 'planificacao', 'externa'):
        return ()
    if group == 'Polímero/PSAI' and basis == 'externa' and not (item.get('unit_area') or 0):
        # An outside envelope is not a billable CONTROLV cut area.
        return ()
    if group == 'Arame' and basis != 'corte':
        return ()
    if group.startswith('Tubo') and basis not in ('corte', 'perfil_comercial'):
        return ()
    return fields


def _evidence_supports(field, value, evidence):
    text = str(evidence or '')
    if field == 'radius_diam' and not re.search(r'Ø|\b(?:DIAM|DIÂM)', text, re.I):
        return False
    values = [float(number.replace(',', '.')) for number in
              re.findall(r'(?<!\d)\d+(?:[,.]\d+)?', text)]
    return any(abs(number - value) <= max(.05, value * .001) for number in values)


def _backup_database(project_id):
    db = Path(database.DB_PATH)
    backup = db.parent / 'backups' / (
        f'before_ai_dimensions_p{project_id}_{datetime.now():%Y%m%d_%H%M%S_%f}.db')
    backup.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db)) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    return backup


def review_proposals(project_id, path, page, result):
    """Inspect eligible missing fields without modifying the project."""
    conn = database.get_connection()
    try:
        same_pdf = [dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=?', (project_id,))
            if _same_pdf(row['source_page'], path)
            and row['item_type'] != 'subconjunto']
        materials = [item for item in same_pdf
                     if _source_matches(item['source_page'], path, page)]
        siblings = [item for item in same_pdf if item not in materials]
        proposals = []
        ai_items = result.get('items') or []

        def propose(item, ai):
            changes = {}
            for field in _allowed_fields(item, ai):
                value = ai.get(field)
                if (isinstance(value, (int, float)) and value > 0
                        and _evidence_supports(field, value, ai.get('evidence'))
                        and not (item.get(field) or 0)
                        and not _has_prior_change(conn, item['id'], field)):
                    changes[field] = value
            if changes:
                candidate = {**item, **changes}
                if item['group_name'] == 'Chapa':
                    gross = calculated_weight(candidate)
                    reference = float(item.get('unit_weight') or 0)
                    if gross > 0 and reference > 0 and not (reference <= gross <= reference * 1.10):
                        # Outside dimensions of a formed part can masquerade
                        # as a flat blank; require the established mass check.
                        return
                proposals.append((item, ai, changes))

        for item in materials:
            matches = [ai for ai in ai_items if _item_matches(ai, item, materials, ai_items)]
            if len(matches) == 1:
                propose(item, matches[0])

        # A parts list and the detail drawing may occupy different pages of
        # the same PDF. Page-local item numbers are not global part IDs.
        cross = {}
        for index, ai in enumerate(ai_items):
            if any(_item_matches(ai, item, materials, ai_items) for item in materials):
                continue
            cross[index] = cross_page_matches(ai, siblings)
        claims = {}
        for matches in cross.values():
            for item in matches:
                claims[item['id']] = claims.get(item['id'], 0) + 1
        for index, matches in cross.items():
            if matches and all(claims[item['id']] == 1 for item in matches):
                for item in matches:
                    propose(item, ai_items[index])
    finally:
        conn.close()
    return proposals


def apply_review(project_id, path, page, result, model, allowed_item_ids=None):
    """Fill only empty fields of confidently associated physical parts.

    Quantities, existing measurements and prices are never taken from the AI.
    The normal material editor recalculates mass and price from approved rules.
    """
    proposals = review_proposals(project_id, path, page, result)
    if allowed_item_ids is not None:
        proposals = [proposal for proposal in proposals
                     if proposal[0]['id'] in allowed_item_ids]
    if not proposals:
        return 0
    _backup_database(project_id)
    # Import here to use the same weight, price and manual-audit path as the UI.
    from app import MaterialUpdate, update_material
    updated = 0
    for item, ai, changes in proposals:
        source = f"Gemini {model}, {path} página {page}"
        note = (f'Cotas sugeridas pela IA ({source}; base '
                f"{ai.get('dimension_basis') or 'não indicada'}): "
                f"{', '.join(f'{key}={value:g} mm' for key, value in changes.items())}. "
                f"Evidência: {(ai.get('evidence') or '')[:300]}")
        observation = ' '.join(x for x in (item.get('observation') or '', note) if x)
        issue = item.get('pending_issue') or ''
        completed = {**item, **changes}
        required = FIELDS_BY_GROUP[item['group_name']]
        if all((completed.get(field) or 0) > 0 for field in required):
            issue = issue.replace(DIMENSION_PENDING, '').strip()
        update_material(project_id, item['id'], MaterialUpdate(
            **changes, observation=observation, pending_issue=issue))
        updated += 1
    return updated
