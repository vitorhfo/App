"""Carry explicit user edits across a folder reimport when the drawing still matches."""
import json

from reader_v3 import norm


EDITABLE_FIELDS = {
    'description', 'group_name', 'item_type', 'parent_assembly', 'material',
    'thickness', 'radius_diam', 'width', 'depth', 'length', 'quantity',
    'printing', 'observation', 'unit', 'pending_issue',
}
PHYSICAL_FIELDS = {
    'group_name', 'material', 'thickness', 'radius_diam', 'width', 'depth', 'length',
}


def _parent_compatible(old_parent, new_parent):
    old_parent = ' / '.join(norm(part) for part in (old_parent or '').split(' / '))
    new_parent = ' / '.join(norm(part) for part in (new_parent or '').split(' / '))
    return not old_parent or new_parent == old_parent or new_parent.endswith(' / ' + old_parent)


def preserve_manual_values(parsed_items, history_rows):
    """Patch parsed BOM entries with net user edits; return old-id/index links and misses.

    History rows are ordered by id and contain material_id, before_json and
    after_json. Calculated totals/prices are deliberately recalculated by the
    import flow. A unit-weight value is carried over when its edit belongs to
    the same final physical geometry; a weight from older geometry is not reused.
    """
    histories = {}
    for row in history_rows:
        entry = histories.setdefault(row['material_id'], {
            'baseline': json.loads(row['before_json']),
            'latest': json.loads(row['after_json']),
            'events': [],
        })
        entry['latest'] = json.loads(row['after_json'])
        entry['events'].append((json.loads(row['before_json']),
                                json.loads(row['after_json'])))

    matched_old_ids = {}
    unmatched = []
    claimed = set()
    for old_id, entry in histories.items():
        before, after = entry['baseline'], entry['latest']
        overrides = {field: after.get(field) for field in EDITABLE_FIELDS
                     if before.get(field) != after.get(field)}
        for event_before, event_after in entry['events']:
            if event_before.get('unit_weight') == event_after.get('unit_weight'):
                continue
            event_geometry = tuple(event_after.get(field)
                                   for field in sorted(PHYSICAL_FIELDS))
            latest_geometry = tuple(after.get(field)
                                    for field in sorted(PHYSICAL_FIELDS))
            if event_geometry == latest_geometry:
                overrides['unit_weight'] = event_after.get('unit_weight')
        if str(after.get('price_source') or '').startswith('Ajuste manual aprovado'):
            overrides['unit_price'] = after.get('unit_price')
            overrides['price_source'] = after.get('price_source')
        if not overrides:
            continue

        source_page = before.get('source_page') or ''
        drawing_id = norm(before.get('drawing_id') or '')
        description = norm(before.get('description') or '')
        raw_code = before.get('raw_code') or ''
        matches = [index for index, item in enumerate(parsed_items)
                   if (item.get('source_page') or '') == source_page
                   and norm(item.get('drawing_id') or '') == drawing_id
                   and norm(item.get('description') or '') == description
                   and (item.get('raw_code') or '') == raw_code
                   and _parent_compatible(before.get('parent_assembly'),
                                          item.get('parent_assembly'))]
        if len(matches) != 1 or matches[0] in claimed:
            unmatched.append({'old_material_id': old_id,
                              'description': before.get('description') or '',
                              'match_count': len(matches)})
            continue

        index = matches[0]
        claimed.add(index)
        parsed_items[index].update(overrides)
        matched_old_ids[old_id] = index

    return matched_old_ids, unmatched
