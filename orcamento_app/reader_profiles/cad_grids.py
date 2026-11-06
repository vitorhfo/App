"""Additional company CAD tables, selected by exact drawn-column layouts."""
import re

from .common import norm, num, material_cell_spec
from .cad_part_number import _merged

ALIASES={
    'item':{'ITEM','NO','N','NO ITEM','N ITEM'}, 'position':{'POS','POSICAO'},
    'quantity':{'QTD','QTDE','QUANTIDADE'}, 'description':{'DESCRICAO','DESCRICAO DA PECA'},
    'code':{'CODIGO','COD'}, 'material':{'MATERIAL'}, 'weight':{'PESO','PESO KG','PESO G'},
}
SCHEMAS=(
    ('item_qty_description',('item','quantity','description')),
    ('legacy_drawn_grid',('item','description','code','quantity')),
    ('position_material_weight',('position','quantity','code','material','weight')),
)


def cad_named_grid_bom(page,text=None):
    text=page.get_text() if text is None else text
    if not any(token in norm(text).split() for token in ('QTD','QTDE','QUANTIDADE')):
        return []
    words=page.get_text('words')
    anchors=[w for w in words if norm(w[4]) in {'ITEM','N','NO','POS','POSICAO'}]
    if not anchors:return []
    lines=[]
    for drawing in page.get_drawings():
        for element in drawing['items']:
            if element[0]=='l':
                a,b=element[1:3];lines.append((a.x,a.y,b.x,b.y))
            elif element[0]=='re':
                r=element[1]
                lines.extend([(r.x0,r.y0,r.x1,r.y0),(r.x0,r.y1,r.x1,r.y1),
                              (r.x0,r.y0,r.x0,r.y1),(r.x1,r.y0,r.x1,r.y1)])
    def cell(left,right,top,bottom):
        content=[w for w in words if left<(w[0]+w[2])/2<right and top+.1<(w[1]+w[3])/2<bottom-.1]
        return ' '.join(w[4] for w in sorted(content,key=lambda w:(round(w[1]/2)*2,w[0]))).strip()
    readings=[];seen=set()
    for anchor in anchors:
        cy=(anchor[1]+anchor[3])/2
        vertical=_merged([x0 for x0,y0,x1,y1 in lines if abs(x1-x0)<.25 and abs(y1-y0)>6
                          and min(y0,y1)<=cy<=max(y0,y1)])
        left=max((x for x in vertical if x<anchor[0]),default=None)
        if left is None:continue
        available=[x for x in vertical if x>=left]
        if len(available)<4:continue
        horizontal=_merged([y0 for x0,y0,x1,y1 in lines if abs(y1-y0)<.25
                            and min(x0,x1)<=available[0]+.6 and max(x0,x1)>=available[1]-.6])
        top=max((y for y in horizontal if y<cy),default=None)
        bottom=min((y for y in horizontal if y>cy),default=None)
        if top is None or bottom is None or bottom-top>65:continue
        for profile,columns in SCHEMAS:
            if len(available)<len(columns)+1:continue
            edges=available[:len(columns)+1]
            trailing=[norm(cell(a,b,top,bottom)) for a,b in zip(available[len(columns):],available[len(columns)+1:])]
            if any(label and not re.fullmatch(r'[A-Z0-9]',label) for label in trailing):
                continue  # A wider named table is a different layout; page-frame labels are not columns.
            headings=[norm(cell(a,b,top,bottom)) for a,b in zip(edges,edges[1:])]
            if not all(label in ALIASES[field] for label,field in zip(headings,columns)):
                continue
            signature=(round(left,1),round(top,1),profile)
            if signature in seen:continue
            seen.add(signature)
            endpoints={}
            for x0,y0,x1,y1 in lines:
                if abs(x1-x0)<.25 and any(abs(x0-edge)<.6 for edge in edges[1:-1]):
                    for endpoint in (y0,y1):
                        endpoints.setdefault(round(endpoint,1),set()).add(round(x0,1))
            row_horizontal=_merged([*horizontal,*(y for y,owners in endpoints.items() if len(owners)>=2)])
            directions=([y for y in row_horizontal if y>=bottom-.3],
                        list(reversed([y for y in row_horizontal if y<=top+.3])))
            for boundaries in directions:
                rows=[]
                for row_top,row_bottom in zip(boundaries,boundaries[1:]):
                    row_top,row_bottom=sorted((row_top,row_bottom))
                    if not 3<row_bottom-row_top<135:break
                    cells=[cell(a,b,row_top,row_bottom) for a,b in zip(edges,edges[1:])]
                    if not re.fullmatch(r'\d{1,3}',cells[0]):break
                    values=dict(zip(columns,cells))
                    quantity=values['quantity'];qty=num(quantity)
                    if not re.fullmatch(r'\d+(?:[,.]\d+)?',quantity) or qty!=int(qty) or not 0<qty<=10000:
                        return []
                    description=values.get('description') or values.get('code','')
                    if not description:return []
                    code=values.get('code','')
                    material=values.get('material','')
                    if profile=='item_qty_description' and norm(description).startswith(('ARAME ','CHAPA ','TUBO ')):
                        material=description
                    spec=material_cell_spec(material)
                    wire=re.fullmatch(r'ARAME\s*[Øø]\s*(\d+(?:[,.]\d+)?)\s*[xX×]\s*(\d+(?:[,.]\d+)?)\s*(?:mm)?',
                                      description.strip(),re.I)
                    length=0
                    if wire:
                        spec['diameter']=num(wire.group(1));length=num(wire.group(2))
                    if not spec['diameter'] and 'ARAME' in norm(material):
                        diameter=re.search(r'\bDIAM(?:ETRO)?\.?\s*(\d+(?:[,.]\d+)?)\s*MM\b',material,re.I)
                        if diameter:spec['diameter']=num(diameter.group(1))
                    raw=code if re.fullmatch(r'[A-Z0-9_.\-/]{2,40}',code,re.I) and re.search(r'\d',code) else ''
                    weight_raw=values.get('weight','');weight=0
                    if 'weight' in columns:
                        label=headings[columns.index('weight')]
                        if label=='PESO KG':weight=num(weight_raw)
                        elif label=='PESO G':weight=num(weight_raw)/1000
                    rows.append(dict(item_num=int(cells[0]),description=description,quantity=int(qty),
                        raw_code=raw,part_number=raw,material=material,cad_layout=profile,
                        assembly_hint=bool(re.match(r'^(?:MTG|CJ|CONJ|CONJUNTO|MONTAGEM)\b',norm(description))),
                        row_thickness=spec['thickness'],row_diameter=spec['diameter'],
                        row_width=spec['width'],row_depth=spec['depth'],row_length=length,
                        row_weight_kg=weight,row_weight_raw=weight_raw,
                        weight_unit_explicit=('weight' in columns and headings[columns.index('weight')] in {'PESO KG','PESO G'})))
                if rows:
                    readings.extend(rows)
                    break
    return readings
