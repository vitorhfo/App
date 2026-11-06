"""Drawn N° ITEM / N° DA PEÇA / DESCRIÇÃO / QTD grids in SolidWorks exports."""
import re

from .common import norm, num


def _merged(values, tolerance=.6):
    result = []
    for value in sorted(values):
        if not result or value-result[-1] > tolerance:
            result.append(value)
    return result


def cad_part_number_bom(page, text=None):
    text = page.get_text() if text is None else text
    if not re.search(r'\b(?:N|NO|NUMERO) DA PECA\b', norm(text)):
        return []
    words = page.get_text('words')
    headers = []
    for part in words:
        if norm(part[4]) != 'PECA':
            continue
        line = sorted((w for w in words if abs(w[1]-part[1])<3),key=lambda w:w[0])
        preceding = [norm(w[4]) for w in line if w[0]<part[0]]
        if len(preceding)<2 or preceding[-2] not in {'N','NO','NUMERO'} or preceding[-1]!='DA':
            continue
        description = next((w for w in line if w[0]>part[2] and norm(w[4])=='DESCRICAO'),None)
        quantity = next((w for w in line if description and w[0]>description[2]
                         and norm(w[4]) in {'QTD','QTDE','QUANTIDADE'}),None)
        item = max((w for w in words if w[0]<part[0] and abs(w[1]-part[1])<22
                    and norm(w[4])=='ITEM'),key=lambda w:w[0],default=None)
        if item and description and quantity:
            headers.append((item,part,description,quantity))
    if not headers:
        return []
    lines = []
    for drawing in page.get_drawings():
        for element in drawing['items']:
            if element[0]=='l':
                a,b=element[1:3];lines.append((a.x,a.y,b.x,b.y))
            elif element[0]=='re':
                rect=element[1]
                lines.extend([(rect.x0,rect.y0,rect.x1,rect.y0),
                              (rect.x0,rect.y1,rect.x1,rect.y1),
                              (rect.x0,rect.y0,rect.x0,rect.y1),
                              (rect.x1,rect.y0,rect.x1,rect.y1)])
    result = []
    for item,part,description,quantity in headers:
        y=(part[1]+part[3])/2
        vertical=_merged([x0 for x0,y0,x1,y1 in lines if abs(x1-x0)<.25
                          and min(y0,y1)<=y<=max(y0,y1) and abs(y1-y0)>8])
        left=max((x for x in vertical if x<item[0]),default=None)
        right=min((x for x in vertical if x>quantity[2]),default=None)
        if left is None or right is None:
            continue
        edges=[x for x in vertical if left<=x<=right]
        if len(edges)!=5:
            continue
        # Check the column owners as well as their order. Empty descriptions
        # must stay empty rather than shifting the part name into that cell.
        if not all(edges[i]<(word[0]+word[2])/2<edges[i+1]
                   for i,word in enumerate((item,part,description,quantity))):
            continue
        boundaries=_merged([y0 for x0,y0,x1,y1 in lines if abs(y1-y0)<.25 and y0>y
                            and min(x0,x1)<=edges[0]+.6 and max(x0,x1)>=edges[1]-.6])
        rows=[]
        for top,bottom in zip(boundaries,boundaries[1:]):
            if not 4<bottom-top<130:
                break
            cells=[]
            for a,b in zip(edges,edges[1:]):
                contents=[w for w in words if a<(w[0]+w[2])/2<b
                          and top+.1<(w[1]+w[3])/2<bottom-.1]
                cells.append(' '.join(w[4] for w in sorted(contents,
                             key=lambda w:(round(w[1]/2)*2,w[0]))).strip())
            if not re.fullmatch(r'\d{1,3}',cells[0]):
                if rows:break
                continue
            if not cells[1]:
                return []
            # A quantity cell that is blank/uncertain invalidates this reading;
            # never silently assume one physical component.
            qty=num(cells[3])
            if not re.fullmatch(r'\d+(?:[,.]\d+)?',cells[3]) or qty!=int(qty) or not 0<qty<=10000:
                return []
            part_number,printed_description=cells[1:3]
            is_code=bool(re.fullmatch(r'[A-Z0-9_.\-/]{2,40}',part_number,re.I)
                         and re.search(r'\d',part_number))
            name=(printed_description or f'PEÇA {part_number}') if is_code else part_number
            material=(printed_description if not is_code and re.match(
                r'^(?:ARAME|CHAPA|TUBO|ACO|ALUMINIO|PSAI|PVC|MDF|INOX|ACRILICO|PETG)\b',
                norm(printed_description)) else '')
            rows.append(dict(item_num=int(cells[0]),description=name,quantity=int(qty),
                             raw_code=part_number if is_code else '',part_number=part_number,
                             part_description=printed_description,material=material,
                             cad_layout='part_number_grid'))
        result.extend(rows)
    return result


def is_part_only_bom(boms, stem):
    """A part's one self-reference is metadata, not another assembly level."""
    rows=[row for _,section in boms for row in section]
    if len(rows)!=1 or not rows[0].get('cad_layout') or rows[0]['quantity']!=1:
        return False
    row=rows[0]
    if norm(row['description'])==norm(stem):
        return True
    code=norm(row.get('raw_code',''))
    return bool(code and norm(stem).split()[-1:]==[code])


def cad_row_details(row, drawing_details):
    """Use explicit list measures only to fill absent part-drawing measures."""
    result=dict(drawing_details)
    if row.get('material') and not result.get('material'):
        result['material']=row['material']
    for key,target in [('row_length','length'),('row_width','width'),('row_depth','depth'),
                       ('row_thickness','thickness'),('row_diameter','diameter')]:
        if row.get(key) and not result.get(target):result[target]=row[key]
    if row.get('row_weight_kg'):
        result['unit_weight']=max(result.get('unit_weight',0),row['row_weight_kg'])
    return result


def primary_cad_tables(boms):
    """Do not add newly recognized detail-page lists to a file's root quantities.

    Old CAD pages retain their established behavior. A new multi-page format
    needs explicit page-owner links before additional assembly tables can be
    expanded. Even a repeated one-row detail stays visible for owner review.
    """
    if len(boms)<2:return boms,[]
    legacy=[entry for entry in boms if any(not row.get('cad_layout') for row in entry[1])]
    kept=legacy or boms[:1]
    unresolved=[]
    for page,rows in boms:
        if any(page==kept_page for kept_page,_ in kept):continue
        unresolved.append(page)
    return kept,unresolved
