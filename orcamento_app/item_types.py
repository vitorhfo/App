"""Classificação estrutural independente da família de material."""
import re
import unicodedata

RAW_GROUPS = {'Chapa', 'Tubo Quadrado/Retangular', 'Tubo Redondo', 'Arame', 'Pintura a Pó'}
VALID_TYPES = {'materia_prima', 'comprado', 'subconjunto'}


def has_detail_children(item, materials):
    """An assembly row is structural once its component path has children."""
    path = ' / '.join(x.strip().casefold() for x in
        (item.get('parent_assembly') or '', item.get('description') or '') if x.strip())
    return any(((child.get('parent_assembly') or '').casefold() == path or
                (child.get('parent_assembly') or '').casefold().startswith(path + ' / ') or
                (child.get('mirrored_assembly') or '').casefold() == path or
                (child.get('mirrored_assembly') or '').casefold().startswith(path + ' / '))
               for child in materials if child is not item)


def normalize(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    return ''.join(c for c in value if not unicodedata.combining(c)).upper()


def infer_item_type(description='', group_name='', source_group='', drawing_id='',
                    has_dimensions=False, pending_issue=''):
    """Use BOM role first; missing dimensions alone never means purchased."""
    role = normalize(source_group)
    description = normalize(description)
    issue = normalize(pending_issue)
    if ('SUB CONJUNTO' in role or 'SUBCONJUNTO' in role or 'SUB PRODUTO' in role or
            re.search(r'\bSUB[\s.\-]*MONTAGEM\b', role) or
            normalize(group_name) == 'SUBCONJUNTO' or
            'SUBCONJUNTO SEM LISTA' in issue):
        return 'subconjunto'
    if role in ('COMPRADOS', 'ACESSORIOS', 'ACESSORIO', 'EMBALAGEM'):
        return 'comprado'
    if (re.search(r'\b(SUBCONJUNTO|CONJUNTO|MONTAGEM|CONJ\.?|CORPO)\b', description)
            and not has_dimensions):
        return 'subconjunto'
    # Explicit polymer-sheet material classes remain purchased even when a
    # CAD BOM labels every row in the table as METAL.
    if normalize(group_name) in ('POLIMERO/PSAI', 'POLIMEROS'):
        return 'comprado'
    if role in ('METAL', 'CHAPA DE ACO', 'TUBO QUADRADO', 'TUBO REDONDO', 'ARAME'):
        return 'materia_prima'
    if role in ('COMPRADOS', 'ACESSORIOS', 'ACESSORIO', 'EMBALAGEM', 'POLIMEROS', 'MADEIRA'):
        return 'comprado'
    return 'materia_prima' if group_name in RAW_GROUPS else 'comprado'
