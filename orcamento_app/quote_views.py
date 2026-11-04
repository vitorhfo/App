"""Read-only script, AI and independent-agreement views of one budget."""

import json
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pymupdf

from ai_apply_dimensions import (FIELDS_BY_GROUP, _allowed_fields,
                                 _evidence_supports, _same_pdf, _source_matches)
from ai_coded_wire_import import parse_coded_wire_table
from ai_pdf_review import (AUTO_MODELS, FIELDS, MODEL, _comparison_row, _name,
                           _side_base, compare_review, load_review, resolve_pdf)
from database import get_connection


AI_NOTES = ('Cotas sugeridas pela IA', 'Corte da variante código')
SCRIPT_FIELDS = ('group_name', 'item_type', 'material', 'length', 'width', 'depth',
                 'thickness', 'radius_diam', 'quantity', 'unit_weight',
                 'total_weight', 'unit_area', 'total_area', 'unit_price',
                 'total_price', 'price_source', 'drawing_length',
                 'wire_allowance_mm', 'finished_unit_weight',
                 'finished_total_weight', 'pending_issue')
DISPLAY_FIELDS = ('length', 'width', 'depth', 'thickness', 'radius_diam',
                  'quantity', 'unit_weight_g')


def _ai_event(before, after):
    previous = str(before.get('observation') or '')
    current = str(after.get('observation') or '')
    return any(current.count(marker) > previous.count(marker) for marker in AI_NOTES)


def _script_baselines(conn, materials):
    baselines = {item['id']: dict(item) for item in materials}
    imported = defaultdict(dict)
    for row in conn.execute('''SELECT material_id,before_json,after_json
        FROM material_changes WHERE project_id=? ORDER BY id''',
        (materials[0]['project_id'],)) if materials else ():
        item_id = row['material_id']
        if item_id not in baselines:
            continue
        try:
            before, after = json.loads(row['before_json']), json.loads(row['after_json'])
        except (TypeError, ValueError):
            continue
        ai_event = _ai_event(before, after)
        for field in SCRIPT_FIELDS:
            if before.get(field) == after.get(field):
                continue
            if ai_event:
                imported[item_id].setdefault(field, before.get(field))
            else:
                # A later human correction supersedes this AI-derived value.
                imported[item_id].pop(field, None)
    for item_id, values in imported.items():
        baselines[item_id].update(values)
        baselines[item_id]['ai_imported_fields'] = sorted(values)
    return baselines


def _code_link(ai, path, pdf, materials, code_tables):
    """A child wire table can identify an already listed part by exact code."""
    code = str(ai.get('item_number') or '')
    if not code.isdigit():
        return None
    if pdf not in code_tables:
        with pymupdf.open(pdf) as document:
            code_tables[pdf] = [parse_coded_wire_table(page.get_text())
                                for page in document]
    tables = code_tables[pdf]
    row = next((table[code] for table in tables if code in table), None)
    if not row or abs(float(ai.get('length') or 0) - row['cut_length']) > .01 or (
            abs(float(ai.get('radius_diam') or 0) - row['diameter']) > .01):
        return None
    title = _name(Path(path).stem)
    candidates = [item for item in materials
                  if item.get('raw_code') == code
                  and _name(item['description'].split(' - ', 1)[0]) == title]
    return candidates[0] if len(candidates) == 1 else None


def _reasonable_match(ai, item):
    if not item or ai.get('item_type') == 'subconjunto':
        return False
    left, right = _side_base(ai.get('description')), _side_base(item['description'])
    return bool(left and right and (left in right or right in left or
                SequenceMatcher(None, left, right).ratio() >= .72))


def _supported_fields(ai, item, code_link=False):
    if code_link:
        return {'length', 'radius_diam'}
    return set(_allowed_fields(item, ai))


def _comparison(project_id, path, page, pdf, review, materials, baselines,
                code_tables):
    same_pdf = [baselines[item['id']] for item in materials
                if _same_pdf(item.get('source_page'), path)
                and item['item_type'] != 'subconjunto']
    on_page = [item for item in same_pdf
               if _source_matches(item.get('source_page'), path, page)]
    siblings = [item for item in same_pdf if item not in on_page]
    rows = compare_review(review, on_page, siblings)['comparisons']
    result = []
    for row in rows:
        ai = row['ai_item']
        script = baselines.get(row['script_item_id']) if row['script_item_id'] else None
        code_link = False
        if not _reasonable_match(ai, script):
            script = _code_link(ai, path, pdf, list(baselines.values()),
                                code_tables)
            code_link = script is not None
        if script is None:
            row = _comparison_row(ai, None)
        elif code_link:
            row = _comparison_row(ai, script, cross_page=True)
        result.append((row, script, code_link))
    return result


def build_quote_views(project_id):
    """Never writes to materials and never charges an AI-only/local-qty row."""
    conn = get_connection()
    try:
        project = conn.execute('SELECT id,name,folder_path FROM projects WHERE id=?',
                               (project_id,)).fetchone()
        if project is None:
            raise ValueError('Projeto não encontrado')
        ai_created = {row[0] for row in conn.execute('''SELECT material_id
            FROM ai_discovered_items WHERE project_id=? AND material_id IS NOT NULL''',
            (project_id,))}
        materials = [dict(row) for row in conn.execute('''SELECT * FROM materials
            WHERE project_id=? AND item_type!='subconjunto' ORDER BY item_num,id''',
            (project_id,)) if row['id'] not in ai_created]
        baselines = _script_baselines(conn, materials)
        jobs = [dict(row) for row in conn.execute('''SELECT path,page,model,state
            FROM ai_review_jobs WHERE project_id=? ORDER BY path,page,model''',
            (project_id,))]
    finally:
        conn.close()

    script_items = list(baselines.values())
    script_cost = round(sum(float(item.get('total_price') or 0)
                            for item in script_items), 2)
    script_missing = sum(item.get('unit_price') is None for item in script_items)
    preferred = {name: rank for rank, name in enumerate((*AUTO_MODELS, MODEL))}
    primary = {}
    observations = defaultdict(lambda: defaultdict(list))
    code_tables = {}
    ai_items = []
    reviewed_pages = set()
    for job in jobs:
        if job['state'] != 'done':
            continue
        try:
            pdf = resolve_pdf(project['folder_path'] or '', job['path'])
            review = load_review(project_id, job['path'], job['page'], pdf,
                                 job['model'])
        except (OSError, ValueError):
            continue
        if not review:
            continue
        reviewed_pages.add((job['path'].casefold(), job['page']))
        page_key = (job['path'].casefold(), job['page'])
        if page_key not in primary or preferred.get(job['model'], 99) < preferred.get(
                primary[page_key], 99):
            primary[page_key] = job['model']
        for comparison, script, code_link in _comparison(
                project_id, job['path'], job['page'], pdf, review, materials,
                baselines, code_tables):
            ai = comparison['ai_item']
            if ai.get('item_type') == 'subconjunto' and script is None:
                continue
            source = f"{job['path']}#page={job['page']}"
            row = {'description': ai.get('description') or '',
                   'item_number': ai.get('item_number') or '',
                   'material': ai.get('material') or '',
                   'item_type': ai.get('item_type') or '',
                   'quantity_scope': ai.get('quantity_scope') or 'unknown',
                   'dimension_basis': ai.get('dimension_basis') or '',
                   'evidence': ai.get('evidence') or '',
                   'source_page': source, 'model': job['model'],
                   'script_item_id': script['id'] if script else None,
                   **{field: ai.get(field) for field in DISPLAY_FIELDS}}
            ai_items.append((page_key, row))
            if script is None:
                continue
            supported = _supported_fields(ai, script, code_link)
            for field in comparison['fields']:
                name = field['field']
                if field['ai'] is None:
                    continue
                if name not in supported and name != 'quantity':
                    continue
                if name == 'quantity' and (
                        ai.get('quantity_scope') != 'project_total'
                        or not _evidence_supports('quantity', ai.get('quantity'),
                                                  ai.get('evidence'))):
                    continue
                if name != 'quantity' and not code_link and not _evidence_supports(
                        name, ai.get(name), ai.get('evidence')):
                    continue
                observations[script['id']][name].append(field)

    visible_ai = [row for page_key, row in ai_items
                  if row['model'] == primary.get(page_key)]
    agreement_items = []
    confirmed_cost = 0.0
    fully_confirmed = 0
    for item in script_items:
        confirmed = {}
        differing = []
        for field, readings in observations[item['id']].items():
            if any(reading['state'] == 'different' for reading in readings):
                differing.append(field)
            elif readings and all(reading['state'] == 'agree' for reading in readings):
                confirmed[field] = readings[0]['script']
        if not confirmed:
            continue
        required = FIELDS_BY_GROUP.get(item['group_name'], ())
        complete = bool(required and set(required).issubset(confirmed)
                        and 'quantity' in confirmed)
        price = item.get('total_price') if complete and item.get('unit_price') is not None else None
        if complete:
            fully_confirmed += 1
        if price is not None:
            confirmed_cost += float(price)
        agreement_items.append({
            'material_id': item['id'], 'description': item['description'],
            'group_name': item['group_name'], 'confirmed_fields': confirmed,
            'differing_fields': sorted(differing),
            'complete': complete, 'total_price': price,
            'source_page': item.get('source_page') or ''})
    return {
        'project_id': project_id,
        'script': {'items': script_items, 'known_cost': script_cost,
                   'missing_prices': script_missing},
        'ai': {'items': visible_ai, 'reviewed_pages': len(reviewed_pages),
               'total_pages': len({(j['path'].casefold(), j['page']) for j in jobs})},
        'agreement': {'items': agreement_items,
                      'known_cost': round(confirmed_cost, 2),
                      'fully_confirmed_items': fully_confirmed,
                      'total_script_items': len(script_items)},
    }
