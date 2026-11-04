"""Read-only index of every technical PDF in an imported project folder."""

from collections import defaultdict
from pathlib import Path


def _missing_dimensions(item):
    if item.get('item_type') == 'subconjunto':
        return False
    group=item.get('group_name') or ''
    length=float(item.get('length') or 0)
    width=float(item.get('width') or 0)
    depth=float(item.get('depth') or 0)
    thickness=float(item.get('thickness') or 0)
    diameter=float(item.get('radius_diam') or 0)
    if group in ('Chapa','Polímero/PSAI'):
        return not (length>0 and width>0 and thickness>0)
    if group == 'Arame':
        return not (length>0 and diameter>0)
    if group == 'Tubo Redondo':
        return not (length>0 and diameter>0 and thickness>0)
    if group == 'Tubo Quadrado/Retangular':
        return not (length>0 and width>0 and depth>0 and thickness>0)
    return 'dimens' in (item.get('pending_issue') or '').lower()


def list_project_pdfs(folder_path, materials):
    """List PDFs regardless of whether OCR, BOM matching or cotas succeeded."""
    if not folder_path:
        return []
    root=Path(folder_path).resolve()
    if not root.is_dir():
        return []
    linked=defaultdict(list)
    for item in materials:
        source=(item.get('source_page') or '').split('#page=',1)[0]
        if source:
            linked[source.replace('\\','/')].append(item)
    files=[]
    for path in root.rglob('*'):
        if not path.is_file() or path.suffix.lower()!='.pdf' or path.name.startswith('._'):
            continue
        if not path.resolve().is_relative_to(root):
            continue
        relative=path.relative_to(root).as_posix()
        items=linked.get(relative,[])
        files.append({
            'path':relative,
            'source_ref':f'{relative}#page=1',
            'linked_items_count':len(items),
            'missing_dimensions_count':sum(_missing_dimensions(item) for item in items),
        })
    return sorted(files,key=lambda item:item['path'].casefold())
