"""Validate manually edited dimensions against material profiles and PDFs."""

from pathlib import Path
import re

import pymupdf

from reader_v3 import (cut_table_materials, cut_table_rows, details, norm,
                       parameterized_details)


RECT_PROFILE=re.compile(r'(?<!\d)(\d+(?:[,.]\d+)?)\s*[xX]\s*'
                        r'(\d+(?:[,.]\d+)?)\s*[xX]\s*'
                        r'(\d+(?:[,.]\d+)?)\s*(?:mm)?\b',re.I)
ROUND_PROFILE=re.compile(r'[Øø�]\s*(\d+(?:[,.]\d+)?)\s*'
                         r'(?:[xX]\s*(\d+(?:[,.]\d+)?))?\s*(?:mm)?\b',re.I)
ROUND_BARE_PROFILE=re.compile(r'(?<!\d)(\d+(?:[,.]\d+)?)\s*[xX]\s*'
                              r'(\d+(?:[,.]\d+)?)\s*(?:mm)?\b',re.I)


def _num(value):
    return float(value.replace(',','.'))


def rect_profile(material):
    match=RECT_PROFILE.search(material or '')
    return tuple(_num(x) for x in match.groups()) if match else None


def round_profile(material):
    match=ROUND_PROFILE.search(material or '')
    if (not match or match.group(2) is None) and 'RED' in norm(material):
        match=ROUND_BARE_PROFILE.search(material or '')
    if not match or match.group(2) is None: return None
    return (_num(match.group(1)),_num(match.group(2)))


def _fmt(value):
    return f'{float(value):g}'


def synchronize_tube_profile(item,before):
    """Keep edited profile text and numeric fields consistent.

    Returns an error message for conflicting simultaneous changes.
    """
    group=item.get('group_name')
    if group=='Tubo Quadrado/Retangular':
        keys=('width','depth','thickness')
        parser=rect_profile
        pattern=RECT_PROFILE
        formatter=lambda values: 'x'.join(_fmt(x) for x in values)+'mm'
    elif group=='Tubo Redondo':
        keys=('radius_diam','thickness')
        parser=round_profile
        pattern=(ROUND_PROFILE if ROUND_PROFILE.search(item.get('material') or '')
                 else ROUND_BARE_PROFILE)
        formatter=lambda values: 'Ø'+_fmt(values[0])+'x'+_fmt(values[1])+'mm'
    else:
        return None
    current=tuple(float(item.get(key) or 0) for key in keys)
    previous=tuple(float(before.get(key) or 0) for key in keys)
    text_changed=(item.get('material') or '')!=(before.get('material') or '')
    dimensions_changed=any(abs(a-b)>1e-9 for a,b in zip(current,previous))
    typed=parser(item.get('material'))
    if text_changed and typed:
        if dimensions_changed and any(abs(a-b)>1e-6 for a,b in zip(current,typed)):
            return 'O perfil escrito no material difere das medidas informadas. Corrija um dos dois.'
        for key,value in zip(keys,typed): item[key]=value
    elif dimensions_changed or text_changed:
        if all(value>0 for value in current):
            value=formatter(current)
            material=item.get('material') or ''
            item['material']=(pattern.sub(value,material,count=1) if typed
                              else (material.rstrip()+' '+value).strip())
    values=tuple(float(item.get(key) or 0) for key in keys)
    if all(value>0 for value in values):
        if group=='Tubo Quadrado/Retangular' and 2*values[2]>=min(values[:2]):
            return 'A espessura do tubo deve ser menor que a metade do menor lado.'
        if group=='Tubo Redondo' and 2*values[1]>=values[0]:
            return 'A espessura do tubo redondo deve ser menor que a metade do diâmetro.'
    return None


def linked_drawing(conn,item):
    """Return the exact part's PDF details, never a parent assembly's mass."""
    source=item.get('source_page') or ''
    if '#page=' not in source: return None
    project=conn.execute('SELECT folder_path FROM projects WHERE id=?',
                         (item['project_id'],)).fetchone()
    if not project or not project['folder_path']: return None
    root=Path(project['folder_path']).resolve()
    relative,page_text=source.rsplit('#page=',1)
    try: page=int(page_text)-1
    except ValueError: return None
    pdf=(root/relative).resolve()
    drawing_id=item.get('drawing_id') or ''
    cut_match=re.search(r': corte (\d+)$',drawing_id,re.I)
    drawing_stem=drawing_id[:cut_match.start()] if cut_match else drawing_id
    if (not pdf.is_relative_to(root) or not pdf.is_file() or
            pdf.suffix.lower()!='.pdf' or
            norm(pdf.stem)!=norm(drawing_stem)):
        return None
    try:
        with pymupdf.open(pdf) as document:
            if not 0<=page<len(document): return None
            current=document[page]
            text=current.get_text()
            cuts=cut_table_rows(text,current)
            if cut_match:
                drawing=details(text,cuts,page=current)
                parts=cut_table_materials(pdf.stem,1,source,'',pdf.stem,drawing)
                match=next((part for part in parts
                            if part['drawing_id'].endswith(
                                f': corte {cut_match.group(1)}')),None)
                if match is None: return None
                return dict(material=match['material'],length=match['length'],
                            width=match['width'],depth=match['depth'],
                            thickness=match['thickness'],
                            diameter=match['radius_diam'],
                            unit_weight=match['unit_weight'])
            return (parameterized_details(text,item.get('description') or '') or
                    details(text,page=current))
    except (OSError,ValueError):
        return None


def drawing_difference(item,drawing):
    if not drawing: return ''
    fields=(('length','comprimento'),('width','largura'),('depth','altura'),
            ('thickness','espessura'),('radius_diam','diâmetro'))
    changed=[]
    for key,label in fields:
        original=drawing.get('diameter' if key=='radius_diam' else key) or 0
        entered=(item.get('drawing_length') if key=='length' and
                 item.get('group_name')=='Arame' and item.get('wire_allowance_mm')
                 else item.get(key)) or 0
        if original>0 and abs(float(original)-float(entered))>0.001:
            changed.append(f'{label} {original:g}→{entered:g} mm')
    return '; '.join(changed)
