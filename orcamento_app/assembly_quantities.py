"""Propagate an edited assembly count to its physical descendants."""

from mass_math import ceil_kg


def assembly_path(item):
    return ' / '.join(part.strip() for part in
                      (item.get('parent_assembly') or '', item.get('description') or '')
                      if part.strip())


def _within(path, parent):
    path = (path or '').strip().casefold()
    parent = parent.casefold()
    return path == parent or path.startswith(parent + ' / ')


def scaled_descendants(materials, assembly, new_quantity):
    """Return changed rows; stored child quantities are already effective counts.

    A consolidated right/left part contributes to two assembly paths. When just
    one side changes, scale only that side's share of its combined quantity.
    """
    old_quantity = float(assembly['quantity'])
    new_quantity = float(new_quantity)
    if old_quantity <= 0 or new_quantity <= 0:
        raise ValueError('A quantidade do subconjunto deve ser positiva.')
    if abs(new_quantity - old_quantity) < 1e-9:
        return []
    path = assembly_path(assembly)
    factor = new_quantity / old_quantity
    assemblies = {assembly_path(item).casefold(): item for item in materials
                  if item.get('item_type') == 'subconjunto'}
    changes = []
    for item in materials:
        if item.get('id') == assembly.get('id'):
            continue
        own = _within(item.get('parent_assembly'), path)
        mirror_path = item.get('mirrored_assembly') or ''
        mirrored = _within(mirror_path, path) if mirror_path else False
        if not own and not mirrored:
            continue
        item_factor = factor
        if mirror_path and own != mirrored:
            own_parent = assemblies.get((item.get('parent_assembly') or '').casefold())
            mirror_parent = assemblies.get(mirror_path.casefold())
            if own_parent and mirror_parent:
                own_count = float(own_parent['quantity'])
                mirror_count = float(mirror_parent['quantity'])
                combined = own_count + mirror_count
                if combined > 0:
                    changed_count = own_count if own else mirror_count
                    item_factor = (combined + changed_count * (factor - 1)) / combined
        updated = dict(item)
        updated['quantity'] = round(float(item['quantity']) * item_factor, 6)
        if updated['quantity'] <= 0:
            raise ValueError('A quantidade calculada da peça deve ser positiva.')
        updated['total_weight'] = ceil_kg(float(item.get('unit_weight') or 0) * updated['quantity'])
        updated['finished_total_weight'] = ceil_kg(
            float(item.get('finished_unit_weight') or 0) * updated['quantity'])
        updated['total_area'] = round(float(item.get('unit_area') or 0) * updated['quantity'], 4)
        price = item.get('unit_price')
        updated['total_price'] = round(float(price) * updated['quantity'], 2) if price is not None else None
        changes.append((item, updated))
    return changes
