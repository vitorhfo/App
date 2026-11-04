"""Import missing dimensions from completed, still-valid AI PDF reviews."""

from collections import defaultdict

from ai_apply_dimensions import DIMENSIONS, apply_review
from ai_pdf_review import compare_review, load_review, resolve_pdf
from ai_discovered_items import (_group, _key, discovered_candidates,
                                 save_discovered_candidates)
from ai_coded_wire_import import (coded_wire_candidates,
                                  apply_coded_wire_candidates)
from backfill_cached_ai_dimensions import completed_review_candidates
from database import get_connection
from source_inventory import _missing_dimensions
from wire_variants import insert_wire_variants, saved_ai_wire_variants


def _project_rows(project_id):
    conn = get_connection()
    try:
        if not conn.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
            raise ValueError('Projeto não encontrado')
        return [dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=? AND item_type!=?',
            (project_id, 'subconjunto'))]
    finally:
        conn.close()


def _pending_count(rows):
    return sum(_missing_dimensions(item) for item in rows)


def _unlinked_ai_items(project_id, rows):
    """Count measured AI variants on pages with no registered physical part."""
    linked_pages = {(item.get('source_page') or '').replace('\\', '/').casefold()
                    for item in rows}
    conn = get_connection()
    try:
        jobs = [dict(row) for row in conn.execute('''
            SELECT j.path,j.page,j.model,p.folder_path FROM ai_review_jobs j
            JOIN projects p ON p.id=j.project_id
            WHERE j.project_id=? AND j.state='done' ''', (project_id,))]
        variant_keys = {(row['source_page'].replace('\\', '/').casefold(), row['code'])
                        for row in conn.execute('''SELECT source_page,code FROM wire_variants
                            WHERE project_id=?''', (project_id,))}
        discovered_keys = {row['identity_key'] for row in conn.execute('''
            SELECT identity_key FROM ai_discovered_items WHERE project_id=?''',
            (project_id,))}
    finally:
        conn.close()
    seen = set()
    for job in jobs:
        source = f"{job['path'].replace(chr(92), '/')}#page={job['page']}".casefold()
        if source in linked_pages:
            continue
        try:
            pdf = resolve_pdf(job['folder_path'] or '', job['path'])
            review = load_review(project_id, job['path'], job['page'], pdf, job['model'])
        except (OSError, ValueError):
            continue
        if not review:
            continue
        same_pdf = [item for item in rows
                    if (item.get('source_page') or '').replace('\\', '/').split(
                        '#page=', 1)[0].casefold() == job['path'].replace('\\', '/').casefold()]
        comparisons = compare_review({'result': review['result']}, [], same_pdf)
        linked_ai = {id(row['ai_item']) for row in comparisons['comparisons']
                     if row['script_item_id'] is not None}
        for index, item in enumerate(review['result'].get('items') or []):
            if id(item) in linked_ai:
                continue
            if (source, str(item.get('item_number') or '')) in variant_keys:
                continue
            group, _ = _group(item)
            if group and _key(job['path'], item, group) in discovered_keys:
                continue
            if any(isinstance(item.get(field), (int, float)) and item[field] > 0
                   for field in DIMENSIONS):
                seen.add((source, str(item.get('item_number') or ''),
                          str(item.get('description') or ''), index))
    return len(seen)


def _plan(project_id):
    rows = _project_rows(project_id)
    candidates = list(completed_review_candidates(project_id))
    proposed = defaultdict(lambda: defaultdict(list))
    for _, _, proposals in candidates:
        for item, _, changes in proposals:
            for field, value in changes.items():
                proposed[item['id']][field].append(float(value))
    conflicts = {item_id for item_id, fields in proposed.items()
                 if any(any(abs(value - values[0]) > max(.05, values[0] * .001)
                            for value in values[1:])
                        for values in fields.values())}
    eligible = {item_id: fields for item_id, fields in proposed.items()
                if item_id not in conflicts}
    conn = get_connection()
    try:
        variants = saved_ai_wire_variants(project_id, conn)
        existing = {(row['source_page'].casefold(), row['code']): row['ai_agreement_count']
                    for row in conn.execute('''SELECT source_page,code,ai_agreement_count
                        FROM wire_variants WHERE project_id=?''', (project_id,))}
    finally:
        conn.close()
    new_variants = [variant for variant in variants
                    if (variant['source_page'].casefold(), variant['code']) not in existing]
    stronger_variants = [variant for variant in variants
                         if variant['ai_agreement_count'] > existing.get(
                             (variant['source_page'].casefold(), variant['code']), -1)]
    new_items = discovered_candidates(project_id, rows)
    coded_wires = coded_wire_candidates(project_id, rows)
    return (rows, candidates, eligible, conflicts, _unlinked_ai_items(project_id, rows),
            new_variants, stronger_variants, new_items, coded_wires)


def preview_pending_ai_dimensions(project_id):
    rows, candidates, eligible, conflicts, unlinked, new_variants, _, new_items, coded_wires = _plan(project_id)
    conn = get_connection()
    try:
        pending_wire_quantities = conn.execute('''SELECT COUNT(*) FROM wire_variants
            WHERE project_id=? AND quantity IS NULL''', (project_id,)).fetchone()[0]
        pending_ai_items = conn.execute('''SELECT COUNT(*) FROM ai_discovered_items
            WHERE project_id=? AND material_id IS NULL''', (project_id,)).fetchone()[0]
    finally:
        conn.close()
    return {'eligible_items': len(eligible) + len(coded_wires),
            'eligible_fields': sum(len(fields) for fields in eligible.values()) + 2 * len(coded_wires),
            'coded_wire_items': len(coded_wires),
            'conflict_items': len(conflicts),
            'unlinked_ai_items': unlinked,
            'new_wire_variants': len(new_variants),
            'pending_wire_quantities': pending_wire_quantities,
            'new_ai_items': len(new_items),
            'pending_ai_items': pending_ai_items,
            'pending_items': _pending_count(rows),
            'review_pages_with_candidates': len(candidates)}


def apply_pending_ai_dimensions(project_id):
    rows, candidates, eligible, conflicts, unlinked, new_variants, stronger_variants, new_items, coded_wires = _plan(project_id)
    applied_coded_wires = apply_coded_wire_candidates(project_id, coded_wires)
    if new_items:
        from ai_apply_dimensions import _backup_database

        _backup_database(project_id)
        saved_items = save_discovered_candidates(project_id, new_items)
    else:
        saved_items = 0
    if stronger_variants:
        from ai_apply_dimensions import _backup_database
        _backup_database(project_id)
        conn = get_connection()
        try:
            insert_wire_variants(conn, project_id, stronger_variants)
            conn.commit()
        finally:
            conn.close()
    before = {item['id']: item for item in rows if item['id'] in eligible}
    allowed = set(eligible)
    for job, result, proposals in candidates:
        matching = allowed.intersection(item['id'] for item, _, _ in proposals)
        if matching:
            apply_review(project_id, job['path'], job['page'], result,
                         job['model'], allowed_item_ids=matching)
    after = {item['id']: item for item in _project_rows(project_id)}
    conn = get_connection()
    try:
        pending_wire_quantities = conn.execute('''SELECT COUNT(*) FROM wire_variants
            WHERE project_id=? AND quantity IS NULL''', (project_id,)).fetchone()[0]
        pending_ai_items = conn.execute('''SELECT COUNT(*) FROM ai_discovered_items
            WHERE project_id=? AND material_id IS NULL''', (project_id,)).fetchone()[0]
    finally:
        conn.close()
    changed = {item_id: [field for field in fields
                         if (not (before[item_id].get(field) or 0)
                             and (after[item_id].get(field) or 0) > 0)]
               for item_id, fields in eligible.items()}
    return {'applied_items': sum(bool(fields) for fields in changed.values()) + applied_coded_wires,
            'applied_fields': sum(len(fields) for fields in changed.values()) + 2 * applied_coded_wires,
            'applied_coded_wire_items': applied_coded_wires,
            'conflict_items': len(conflicts),
            'unlinked_ai_items': _unlinked_ai_items(project_id, list(after.values())),
            'new_wire_variants': len(new_variants),
            'pending_wire_quantities': pending_wire_quantities,
            'new_ai_items': saved_items,
            'pending_ai_items': pending_ai_items,
            'pending_items': _pending_count(list(after.values())),
            'review_pages_with_candidates': len(candidates)}
