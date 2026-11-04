"""Extra de corte do arame, separado do peso da peça pronta do desenho."""

import math
import re

from calc_engine import DENSIDADE_ACO_CARBONO
from mass_math import ceil_kg


ALLOWANCE_MM = 20.0


def mass_per_mm(diameter_mm):
    if not diameter_mm or diameter_mm <= 0:
        return 0.0
    return math.pi * (diameter_mm / 2.0) ** 2 * DENSIDADE_ACO_CARBONO / 1_000_000.0


def apply_wire_allowance(item):
    """Use the PDF mass for the finished part and add 20 mm to material use.

    Where the drawing omits a cut length, infer one only for a single wire
    piece with known diameter and CAD mass. A welded grade is not one wire.
    """
    if item.get('item_type') == 'subconjunto' or item.get('group_name') != 'Arame':
        return False
    if item.get('wire_allowance_mm'):
        return False
    rate=mass_per_mm(float(item.get('radius_diam') or 0))
    if rate <= 0:
        return False
    nominal=float(item.get('length') or 0)
    finished=float(item.get('unit_weight') or 0)
    if nominal <= 0:
        if 'SEM COMPRIMENTO DESENVOLVIDO; NAO INFERIR DO PESO' in (
                str(item.get('observation') or '').upper()
                .replace('Ã', 'A').replace('Ç', 'C')):
            return False
        description=str(item.get('description') or '').upper()
        if finished <= 0 or re.search(r'\b(?:GRADE|CONJUNTO|MONTAGEM)\b', description):
            return False
        nominal=round(finished/rate,3)
        source='Comprimento nominal estimado pelo peso e diâmetro do desenho.'
        item['confidence']=min(float(item.get('confidence') or 1),0.75)
        issue='Comprimento de corte estimado pelo peso; confirmar no desenho.'
        if issue not in (item.get('pending_issue') or ''):
            item['pending_issue']=' '.join(x for x in (item.get('pending_issue') or '',issue) if x)
    else:
        source='Comprimento nominal lido do desenho.'
    if finished <= 0:
        finished=ceil_kg(nominal*rate)
    quantity=float(item.get('quantity') or 0)
    cut=nominal+ALLOWANCE_MM
    cut_weight=ceil_kg(finished+ALLOWANCE_MM*rate)
    item.update(drawing_length=nominal,length=round(cut,3),
                finished_unit_weight=finished,
                finished_total_weight=ceil_kg(finished*quantity),
                wire_allowance_mm=ALLOWANCE_MM,
                unit_weight=cut_weight,total_weight=ceil_kg(cut_weight*quantity),
                unit_area=round(math.pi*float(item['radius_diam'])*cut/1_000_000,6),
                total_area=round(math.pi*float(item['radius_diam'])*cut*quantity/1_000_000,6))
    note=f'{source} Corte: {nominal:g} + {ALLOWANCE_MM:g} = {cut:g} mm por peça.'
    item['observation']=' '.join(x for x in (item.get('observation') or '',note) if x)
    return True
