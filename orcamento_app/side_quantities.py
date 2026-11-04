"""Show combined quantities for verified right/left BOM counterparts."""
from collections import defaultdict

from reader_v3 import norm, side_and_base


def annotate_side_totals(materials):
    """Add a display-only pair total; stored per-side quantities drive costs."""
    pairs=defaultdict(lambda: defaultdict(list))
    for item in materials:
        if item.get('mirrored_assembly'):
            item['sides_total_quantity']=item.get('quantity')
            continue
        parent=item.get('parent_assembly') or ''
        prefix,_,last=parent.rpartition(' / ')
        parent_side,parent_base=side_and_base(last)
        item_side,item_base=side_and_base(item.get('description'))
        if parent_side and item_side and parent_side!=item_side:
            continue
        side=parent_side or item_side
        if not side:
            continue
        assembly_base=(norm(prefix),parent_base) if parent_side else (norm(parent),'')
        key=(assembly_base,item_base,item.get('item_type'),item.get('group_name'),
             norm(item.get('material')),
             *(round(float(item.get(field) or 0),4) for field in
               ('thickness','radius_diam','width','depth','length','unit_weight')),
             item.get('unit'))
        pairs[key][side].append(item)
    for sides in pairs.values():
        if set(sides)!={'direita','esquerda'}:
            continue
        total=sum(float(item.get('quantity') or 0)
                  for side_items in sides.values() for item in side_items)
        for side_items in sides.values():
            for item in side_items:
                item['sides_total_quantity']=total
    return materials
