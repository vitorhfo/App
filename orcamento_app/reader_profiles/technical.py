"""Extraction rules for technical layouts; no project selection or persistence."""
from .common import norm, num, table_measure, table_diameter, material_cell_spec
import re


def technical_grid_bom(page):
    """Read CAD material tables by their drawn cells, including empty columns.

    Text order omits blank cells, so a flat number sequence cannot distinguish
    width from depth or preserve the MP code and observation reliably.
    """
    words=page.get_text('words')
    if not words: return []
    lines=[]
    for drawing in page.get_drawings():
        for element in drawing['items']:
            if element[0]=='l': lines.append(element[1:3])
    headers=[]
    for word in words:
        if norm(word[4])!='ITEM': continue
        y=word[1]
        headings={norm(other[4]) for other in words if abs(other[1]-y)<2}
        if {'QTD','DESCRICAO','GRUPO','MATERIAL','DESENHO','PESO'}<=headings:
            headers.append(y)
    result=[]
    for y in headers:
        vertical=[]
        for p1,p2 in lines:
            if abs(p1.x-p2.x)>0.25: continue
            low,high=sorted((p1.y,p2.y))
            if low<=y<=high and 8<high-low<60:
                vertical.append(round(p1.x,1))
        edges=sorted(set(vertical))
        if len(edges)!=15: continue  # 14 named columns, 15 cell borders.
        horizontal=[]
        first,second=edges[:2]
        for p1,p2 in lines:
            if abs(p1.y-p2.y)>0.25: continue
            left,right=sorted((p1.x,p2.x))
            if abs(left-first)<0.5 and abs(right-second)<0.5 and p1.y>y:
                horizontal.append(round(p1.y,1))
        rows=sorted(set(horizontal))
        if len(rows)<2: continue
        for top,bottom in zip(rows,rows[1:]):
            if bottom-top<4 or bottom-top>90: continue
            cells=[[] for _ in range(14)]
            for word in words:
                mid_y=(word[1]+word[3])/2
                if not top+0.1<mid_y<bottom-0.1: continue
                mid_x=(word[0]+word[2])/2
                column=next((i for i in range(14)
                             if edges[i]<=mid_x<edges[i+1]),None)
                if column is not None:
                    cells[column].append(word)
            values=[' '.join(w[4] for w in sorted(cell,key=lambda x:(round(x[1],1),x[0]))).strip()
                    for cell in cells]
            if not re.fullmatch(r'\d{1,3}',values[0]) or not re.fullmatch(r'\d{1,4}',values[1]):
                continue
            if not values[3]: continue
            description=values[2]
            if not description and norm(values[3])=='ACESSORIO' and values[4]:
                # RISE accessory rows put the physical item only in MATERIAL.
                description=values[4]
            if not description: continue
            observation='' if values[13]=='.' else values[13].lstrip('.').strip()
            diameter,is_radius=table_diameter(values[6])
            if is_radius:
                observation=' '.join(x for x in (observation,
                    f'Raio {values[6]} convertido para diâmetro {diameter:g} mm.') if x)
            printing_hint=''
            if norm(values[3]) in ('PS','PSAI','PETG','PET','ACRILICO') and 'IMPRESS' in norm(observation):
                printing_hint=('frente e verso' if re.search(r'FRENTE\s+E?\s*VERSO|DOIS\s+LADOS',
                               norm(observation)) else 'frente')
            result.append({'item_num':int(values[0]),'quantity':int(values[1]),
                           'description':description,'group':values[3],
                           'material':values[4], 'thickness':table_measure(values[5]),
                           'diameter':diameter,'width':table_measure(values[7]),
                           'depth':table_measure(values[8]),'length':table_measure(values[9]),
                           'drawing_id':values[10],
                           'unit_weight':num(values[11]),
                           'raw_code':'' if values[12]=='.' else values[12],
                           'observation':observation,'printing_hint':printing_hint})
    return result



def ordered_rise_grid_bom(page, separate=False):
    """RISE grids with varying DESENHO/QTD positions (DOCILE, P&G, RISE).

    Use cell coordinates because PDF text order loses empty cells and wrapped
    descriptions; the older ITEM/QTD/DESCRIÇÃO layout is handled separately.
    """
    words = page.get_text('words')
    headers = []
    for item in words:
        if norm(item[4]) != 'ITEM':
            continue
        same_line = [word for word in words if abs(word[1] - item[1]) < 2]
        ordered = [norm(word[4]) for word in sorted(same_line, key=lambda word: word[0])]
        variants = (
            # RISE part drawings also use a 14-column grid with a separate
            # item number and quantity, then drawing code, description, and
            # the table-stamped mass/area. Match by cell coordinates before
            # falling back to line-order parsing, which loses empty cells.
            (('ITEM','QTD','DESENHO','DESCRI','GRUPO','MATERIAL','ESPESSURA',
              'LARGURA','ALTURA','COMPRIMENTO','PESO','AREA','OBSERVA'),
             {'quantity':1,'drawing':2,'description':3,'group':4,'material':5,
              'thickness':6,'diameter':7,'width':8,'depth':9,'length':10,
              'unit_weight':11,'unit_area':12,'observation':13},15),
            (('ITEM', 'DESENHO', 'DESCRI', 'GRUPO', 'MATERIAL', 'QTD',
              'ESPESSURA', 'COMPRIMENTO', 'PESO', 'OBSERVA'),
             {'drawing': 1, 'description': 2, 'group': 3, 'material': 4, 'quantity': 5,
              'thickness': 6, 'diameter': 7, 'width': 8, 'depth': 9, 'length': 10,
              'unit_weight':11,'unit_area':12,'observation':15},16),
            (('ITEM', 'QTD', 'DESCRI', 'DESENHO', 'GRUPO', 'MATERIAL',
              'ESPESSURA', 'COMPRIMENTO', 'PESO', 'OBSERVA'),
             {'drawing': 3, 'description': 2, 'group': 4, 'material': 5, 'quantity': 1,
              'thickness': 6, 'diameter': 7, 'width': 8, 'depth': 9, 'length': 10,
              'unit_weight':11,'unit_area':12,'observation':15},16),
            (('ITEM', 'QTD', 'DESCRI', 'GRUPO', 'MATERIAL', 'ESPESSURA',
              'COMPRIMENTO', 'DESENHO', 'PESO', 'OBSERVA'),
             {'drawing': 10, 'description': 2, 'group': 3, 'material': 4, 'quantity': 1,
              'thickness': 5, 'diameter': 6, 'width': 7, 'depth': 8, 'length': 9,
              'unit_weight':11,'unit_area':12,'observation':15},16),
            # Newer HH GLOBAL/RISE exports use a 12-column list with the drawing
            # code before its description and no weight/area columns. Preserve
            # the explicit unit, width and cut length from the table cells.
            (('ITEM','DESENHO','DESCRI','DET','GRUPO','MATERIAL','QTD','UNID',
              'LARGURA','COMPRIMENTO','TRATAMENTO','OBSERVA'),
             {'drawing':1,'description':2,'group':4,'material':5,'quantity':6,
              'unit':7,'width':8,'length':9,'finish':10,'observation':11},13),
            # Related HH GLOBAL/RISE exports omit the DET column. Keep this
            # distinct header shape so the project BOM is still recognized;
            # drawing code, unit, and dimensions remain in their own cells.
            (('ITEM','DESENHO','DESCRI','GRUPO','MATERIAL','QTD','UNID',
              'LARGURA','COMPRIMENTO','TRATAMENTO','OBSERVA'),
             {'drawing':1,'description':2,'group':3,'material':4,'quantity':5,
              'unit':6,'width':7,'length':8,'finish':9,'observation':10},12),
        )
        for required, columns, edge_count in variants:
            positions = [next((i for i, value in enumerate(ordered)
                               if value.startswith(name)), -1) for name in required]
            if all(pos >= 0 for pos in positions) and positions == sorted(positions):
                headers.append((item, columns, edge_count))
                break
    if not headers:
        return []
    lines = [element[1:3] for drawing in page.get_drawings()
             for element in drawing['items'] if element[0] == 'l']
    result = []
    sections = []
    for header, columns, edge_count in headers:
        y = (header[1] + header[3]) / 2
        vertical = sorted({round(a.x, 1) for a, b in lines
                           if abs(a.x-b.x) < .25 and min(a.y,b.y) <= y <= max(a.y,b.y)
                           and a.x >= header[0]-5})
        left_edges = [x for x in vertical if x <= header[0] and header[0]-x < 5]
        if not left_edges:
            continue
        first = max(left_edges)  # Exclude a nearby page border.
        edges = [x for x in vertical if x >= first]
        if edge_count == 13:
            same_line=[word for word in words if abs(word[1]-header[1])<2]
            right_limit=max(word[2] for word in same_line)+30
            filtered=[]
            for x in (value for value in edges if value<=right_limit):
                if filtered and x-filtered[-1]<5:
                    filtered[-1]=x
                else:
                    filtered.append(x)
            edges=filtered
        else:
            edges=edges[:edge_count]
        if len(edges) != edge_count:
            continue
        if not all(edges[i+1]-edges[i] > 10 for i in range(edge_count-1)):
            continue
        horizontal = sorted({round(a.y, 1) for a, b in lines
                             if abs(a.y-b.y) < .25 and abs(a.x-edges[0]) < .35
                             and abs(b.x-edges[1]) < .35 and a.y >= header[1]-10})
        if len(horizontal) < 3:
            continue
        section = []
        last_bottom = y
        for top, bottom in zip(horizontal[1:], horizontal[2:]):
            cells = []
            for left, right in zip(edges, edges[1:]):
                contents = [word for word in words
                            if left < (word[0]+word[2])/2 < right
                            and top < (word[1]+word[3])/2 < bottom]
                cells.append(' '.join(word[4] for word in sorted(contents,
                                   key=lambda word: (round(word[1], 1), word[0]))).strip())
            if not re.fullmatch(r'\d{1,3}', cells[0]):
                if section:
                    break
                continue
            # Some RISE tables let the first word of DESCRIÇÃO overhang the
            # narrow QTD cell (VEJA: "0.08 4 PLASTICO BOLHA"). Parse the
            # first numeric token instead of concatenating every digit.
            quantity_cell = cells[columns['quantity']]
            quantity_token = re.match(r'^\s*\d+(?:[,.]\d+)?', quantity_cell)
            quantity = (table_measure(quantity_token.group())
                        if quantity_token else 0)
            if quantity <= 0:
                continue
            description = cells[columns['description']]
            if quantity_token:
                overflow = quantity_cell[quantity_token.end():].strip()
                if overflow:
                    description = f'{overflow} {description}'.strip()
            def cell(name):
                index=columns.get(name)
                return cells[index] if index is not None and index<len(cells) else ''
            group = cell('group')
            material = cell('material')
            # In some RISE 12-column exports the simplified description cell
            # contains only the final wrapped words, while MATERIAL retains
            # the complete catalog description. Recover only when the short
            # cell is a suffix of the material text, avoiding broad merging.
            if (description and material and len(norm(description).split()) <= 6 and
                    norm(material).startswith(norm(description)) is False and
                    norm(description) in norm(material)):
                material_label = re.split(r'\s+-\s+\[(?:[A-Z0-9]+)\]', material, maxsplit=1)[0].strip()
                if len(norm(material_label).split()) > len(norm(description).split()):
                    description = material_label
            row_dimensions = normalize_mdf_grid_dimensions(material, {
                'thickness': table_measure(cell('thickness')),
                'diameter': table_measure(cell('diameter')),
                'width': table_measure(cell('width')),
                'depth': table_measure(cell('depth')),
                'length': table_measure(cell('length')),
            })
            if not description and group and re.search(r'\[(?:AC|EM)[A-Z0-9]+\]', material, re.I):
                # RISE013 has an accessory name in GRUPO while DESCRIÇÃO is
                # empty.  Keep the physical line instead of dropping it.
                description, group = group, 'Acessório'
            drawing = cell('drawing')
            if not description and group and drawing:
                # HEINZ/NEXXIA tables sometimes omit DESCRIÇÃO on every
                # structural row; the physical drawing code remains present.
                # Retain the row with a transparent code-based label so its
                # material, cut dimensions, quantity and hierarchy are kept.
                description = fallback_technical_description(group, material, drawing,
                                                             **row_dimensions)
            if not description:
                continue
            if not group and 'CAIXA' in norm(description):
                group = 'Embalagem'
            if not drawing or drawing == '.':
                drawing = 'COMPRADO: ' + description
            code = re.search(r'\[([A-Z0-9]+)\]', material, re.I)
            treatment=cell('finish')
            printing_match=re.search(r'\b([014]x[014])\b',treatment,re.I)
            printing_hint=(printing_match.group(1).lower() if printing_match and
                           norm(group) in ('PS','PSAI','PETG','PET','POLIMEROS') else '')
            section.append({
                'item_num': int(cells[0]), 'quantity': quantity,
                'description': description, 'group': group, 'material': material,
                **row_dimensions,
                'drawing_id': drawing, 'raw_code': code.group(1) if code else '',
                'unit':cell('unit') or 'un','finish':treatment,
                'printing':printing_match.group(1).lower() if printing_match else '0x0',
                'unit_weight': table_measure(cell('unit_weight')),
                'unit_area': table_measure(cell('unit_area')),
                'observation': cell('observation'), 'printing_hint': printing_hint,
            })
            last_bottom = bottom
        if section:
            result.extend(section)
            sections.append((section, y, last_bottom))
    return sections if separate else result



def compact_rise_cut_bom(page):
    """Seven-column subassembly cut lists: ITEM/QTD/DESCRIÇÃO/MATERIAL/Ø/COMP/DESENHO."""
    words=page.get_text('words')
    lines=[element[1:3] for drawing in page.get_drawings()
           for element in drawing['items'] if element[0]=='l']
    for header in words:
        if norm(header[4])!='ITEM':
            continue
        same=[word for word in words if abs(word[1]-header[1])<2]
        labels=[norm(word[4]) for word in sorted(same,key=lambda word:word[0])]
        # The ordinary 14-column RISE grid contains all six labels below as
        # well.  Its first seven columns can look like a compact cut table,
        # but parsing them here shifts drawing IDs and drops the full BOM.
        if any(any(label.startswith(extra) for label in labels)
               for extra in ('GRUPO','ESPESSURA','LARGURA','PROFUNDIDADE','PESO')):
            continue
        expected=('ITEM','QTD','DESCRI','MATERIAL','COMPRIMENTO','DESENHO')
        positions=[next((i for i,label in enumerate(labels)
                         if label.startswith(name)),-1) for name in expected]
        if not all(pos>=0 for pos in positions) or positions!=sorted(positions):
            continue
        y=(header[1]+header[3])/2
        vertical=sorted({round(a.x,1) for a,b in lines
                         if abs(a.x-b.x)<.25 and min(a.y,b.y)<=y<=max(a.y,b.y)
                         and a.x>=header[0]-5})
        first=max((x for x in vertical if x<=header[0] and header[0]-x<5),default=None)
        if first is None:
            continue
        edges=[x for x in vertical if x>=first][:8]
        if len(edges)!=8 or not all(edges[i+1]-edges[i]>10 for i in range(7)):
            continue
        horizontal=sorted({round(a.y,1) for a,b in lines
                           if abs(a.y-b.y)<.25 and abs(a.x-edges[0])<.35
                           and abs(b.x-edges[1])<.35 and a.y>=header[1]-10})
        result=[]
        for top,bottom in zip(horizontal[1:],horizontal[2:]):
            cells=[]
            for left,right in zip(edges,edges[1:]):
                contents=[word for word in words
                          if left<(word[0]+word[2])/2<right
                          and top<(word[1]+word[3])/2<bottom]
                cells.append(' '.join(word[4] for word in sorted(contents,
                    key=lambda word:(round(word[1],1),word[0]))).strip())
            if not re.fullmatch(r'\d{1,3}',cells[0]):
                if result: break
                continue
            quantity=table_measure(cells[1].split()[0]) if cells[1] else 0
            if quantity<=0 or not cells[2]: continue
            material=cells[3]
            group=('Arame' if 'ARAME' in norm(material) else
                   'Chapa de Aço' if 'CHAPA DE ACO' in norm(material) else '')
            if not group: continue
            gauge=re.search(r'(\d+(?:[,.]\d+)?)\s*mm',material,re.I)
            code=re.search(r'\[([A-Z0-9]+)\]',material,re.I)
            result.append({
                'item_num':int(cells[0]),'quantity':quantity,
                'description':cells[2],'group':group,'material':material,
                'thickness':num(gauge.group(1)) if gauge and group!='Arame' else 0,
                'diameter':table_measure(cells[4]) if group=='Arame' else 0,
                'width':0,'depth':0,'length':table_measure(cells[5]),
                'drawing_id':cells[6],'raw_code':code.group(1) if code else '',
                'unit_weight':0,'observation':'','printing_hint':'',
                'compact_cut':True,
            })
        if result:
            return result
    return []



def technical_text_bom(text, page=None):
    """Read the ITEM/QTD/DESENHO/PESO tables in multi-sheet technical PDFs.

    These tables can appear again on detail pages. The caller selects the
    assembly page, then follows drawing identifiers instead of counting every
    repeated detail table as a new product.
    """
    if not re.search(r'(?im)^ITEM\s+QTD\s*\n\s*DESCRI', text): return []
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    starts=[]
    for i in range(len(lines)-2):
        if norm(lines[i])!='ITEM QTD' or not norm(lines[i+1]).startswith('DESCRI'):
            continue
        header_end=next((j for j in range(i+2,min(i+20,len(lines)))
                         if norm(lines[j]).startswith('OBSERVA')),None)
        if header_end is not None: starts.append(header_end+1)
    if not starts: return []
    group_names=('SUB CONJUNTO','CHAPA DE ACO','TUBO QUADRADO','TUBO REDONDO',
                 'ARAME','ACESSORIO','PS','PSAI','PETG','PET','MADEIRA','PAPELAO','ACRILICO')
    rows=[]
    for start in starts:
        end=next((j for j in range(start,len(lines)) if norm(lines[j]).startswith('RESERVADO TODOS')),
                 len(lines))
        next_header=next((j for j in range(start,end) if norm(lines[j])=='LISTA DE MATERIAIS'
                         and j+1<end and norm(lines[j+1])=='ITEM QTD'),end)
        end=min(end,next_header)
        candidates=[]
        for i in range(start,end-3):
            if not re.fullmatch(r'\d{1,2}',lines[i]) or not re.fullmatch(r'\d{1,3}',lines[i+1]):
                continue
            if not re.search(r'[A-Za-zÀ-ÿ]',lines[i+2]): continue
            if any(norm(lines[j]) in group_names or norm(lines[j])=='TUBO'
                   for j in range(i+3,min(i+8,end))):
                candidates.append(i)
        for n,i in enumerate(candidates):
            stop=candidates[n+1] if n+1<len(candidates) else end
            body=lines[i+2:stop]
            group_index=next((j for j,x in enumerate(body) if norm(x) in group_names or norm(x)=='TUBO'),None)
            if group_index is None or group_index==0: continue
            desc=' '.join(body[:group_index]).strip()
            group=body[group_index]
            offset=group_index+1
            if norm(group)=='TUBO' and offset<len(body) and norm(body[offset]) in ('QUADRADO','REDONDO'):
                group+=' '+body[offset]; offset+=1
            if norm(group)=='SUB CONJUNTO' and offset<len(body) and norm(body[offset])=='SUB CONJUNTO':
                offset+=1
            drawing_index=next((j for j in range(offset,len(body))
                                if technical_drawing_code(body[j])),None)
            bought=norm(group)=='ACESSORIO' and drawing_index is None
            if drawing_index is None and not bought: continue
            if bought:
                code=body[-1] if body and re.fullmatch(r'\d{7,10}',body[-1]) else ''
                weight=num(body[-2]) if code and len(body)>=2 else 0.0
                rows.append({'item_num':int(lines[i]),'quantity':int(lines[i+1]),
                    'description':desc,'group':group,'material':' '.join(body[offset:-2]),
                    'thickness':0.0,'width':0.0,'depth':0.0,'length':0.0,'diameter':0.0,
                    'drawing_id':'COMPRADO: '+desc,'raw_code':code,'unit_weight':weight,
                    'observation':'','printing_hint':''})
                continue
            drawing=body[drawing_index]
            if (drawing_index and re.search(r'_[MP]\d{1,3}[-_]?REV\d+',drawing,re.I)
                    and re.search(r'[A-Za-z]',body[drawing_index-1])):
                drawing=body[drawing_index-1]+' '+drawing
            drawing=' '.join(drawing.split())
            measures=[num(x) for x in body[offset:drawing_index]
                      if re.fullmatch(r'\d+(?:[,.]\d+)?',x)]
            material_parts=[]
            for x in body[offset:drawing_index]:
                if re.fullmatch(r'\d+(?:[,.]\d+)?|\.',x): break
                material_parts.append(x)
            material=' '.join(material_parts).strip()
            after=body[drawing_index+1:]
            grid_numbers=(len(after)>=3 and after[:3]==['1','2','3'])
            weight=0.0 if grid_numbers else (num(after[0]) if after else 0.0)
            code=after[1] if not grid_numbers and len(after)>1 and re.fullmatch(
                r'(?:\{?MP\d{5,}\}?|\d{7,10})',after[1],re.I) else ''
            note_parts=[] if grid_numbers else after[2 if code else 1:]
            observation=' '.join(note_parts).lstrip('.').strip()
            printing_hint=''
            if norm(group) in ('PS','PSAI','PETG','PET','ACRILICO') and 'IMPRESS' in norm(observation):
                printing_hint=('frente e verso' if re.search(r'FRENTE\s+E?\s*VERSO|DOIS\s+LADOS',norm(observation))
                               else 'frente')
            thickness=width=depth=length=diameter=0.0
            if norm(group)=='TUBO QUADRADO' and len(measures)>=4:
                thickness,width,depth,length=measures[:4]
            elif norm(group)=='ARAME' and len(measures)>=2:
                diameter,length=measures[0],measures[-1]
            elif len(measures)>=3:
                thickness,width,length=measures[:3]
            elif len(measures)>=2:
                width,length=measures[:2]
            rows.append({'item_num':int(lines[i]),'quantity':int(lines[i+1]),
                         'description':desc,'group':group,'material':material,
                         'thickness':thickness,'width':width,'depth':depth,'length':length,
                         'diameter':diameter,'drawing_id':drawing,'raw_code':code,
                         'unit_weight':weight,'observation':observation,
                         'printing_hint':printing_hint})
    unique={}
    for row in rows:
        key=(row['item_num'],norm(row['drawing_id']),norm(row['description']))
        unique[key]=row
    return list(unique.values())



def technical_drawing_code(value):
    return re.search(r'(?:_[MP]\d{1,3}[-_]?REV\d+|\b(?:[A-Z]{2,5}|P&G)\d{3,}[MP]\d{2,3}\b)',value,re.I)



def technical_subassembly_group(value):
    return norm(value) in ('SUB CONJUNTO', 'SUB MONTAGEM', 'SUB PRODUTO')



def normalize_mdf_grid_dimensions(material, dimensions):
    """Correct a documented RISE MDF grid shift only when its material gauge agrees.

    Small MDF strips in the Heinz/NEXXIA table place the long side under
    ESPESSURA, the material gauge under the next numeric field, and the strip
    width under LARGURA. The stock material independently specifies the gauge.
    """
    result = dict(dimensions)
    if 'MDF' not in norm(material):
        return result
    gauge = material_cell_spec(material).get('thickness', 0)
    if (gauge > 0 and result.get('thickness', 0) > max(gauge * 2, 30)
            and not result.get('depth')
            and abs(result.get('width', 0) - gauge) <= max(0.1, gauge * 0.01)
            and result.get('length', 0) > 0):
        result['length'] = result['thickness']
        result['thickness'] = gauge
        result['width'] = dimensions['length']
        result['diameter'] = 0
    return result



def fallback_technical_description(group, material, drawing_id, *, thickness=0,
                                   diameter=0, width=0, depth=0, length=0):
    """Build an honest stable label when a CAD BOM leaves DESCRIÇÃO blank.

    Some SolidWorks/NEXXIA exports put only the role, stock description and
    drawing number in the row. Keep that physical row and identify it from its
    drawing; never treat a commercial sheet size as the finished part size.
    """
    drawing = str(drawing_id or '').strip()
    role = norm(group)
    material_text = norm(material)
    if technical_subassembly_group(group):
        return f'SUBPRODUTO {drawing}'.strip()
    if 'TUBO' in material_text or 'METALON' in material_text:
        profile = 'QUADRADO' if 'QUADRADO' in material_text else 'RETANGULAR'
        section = f'{width:g}X{depth:g}' if width and depth else ''
        gauge = f'X{thickness:g}MM' if thickness else ''
        return f'TUBO {profile} {section}{gauge} - {drawing}'.strip(' -')
    if 'MDF' in material_text:
        dims = 'X'.join(f'{value:g}' for value in (width, length) if value)
        gauge = f'X{thickness:g}MM' if thickness else ''
        return f'MDF {dims}{gauge} - {drawing}'.strip(' -')
    if any(token in material_text for token in ('PSAI', 'ACRILICO', 'PVC', 'PETG')):
        kind = next((token for token in ('PSAI', 'ACRILICO', 'PVC', 'PETG')
                     if token in material_text), 'CHAPA')
        color = next((token for token in ('BRANCO', 'PRETO', 'CRISTAL', 'LEITOSO')
                      if token in material_text), '')
        dims = 'X'.join(f'{value:g}' for value in (width, length) if value)
        gauge = f'X{thickness:g}MM' if thickness else ''
        return f'{kind} {color} {dims}{gauge} - {drawing}'.strip(' -')
    if 'CHAPA' in material_text:
        dims = 'X'.join(f'{value:g}' for value in (width, length) if value)
        gauge = f'{thickness:g}MM' if thickness else ''
        return f'CHAPA AÇO {gauge} {dims} - {drawing}'.strip(' -')
    label = {'METAL': 'PEÇA METÁLICA', 'POLIMEROS': 'PEÇA POLIMÉRICA',
             'ACESSORIOS': 'ACESSÓRIO', 'ACESSORIO': 'ACESSÓRIO'}.get(role, 'PEÇA')
    return f'{label} {drawing}'.strip()



def technical_title_dimensions(page):
    """Dimensions printed beside labels in the bottom title block."""
    words=page.get_text('words')
    found={}
    for field,label in (('length','COMPRIMENTO'),('width','LARGURA'),
                        ('thickness','ESPESSURA')):
        labels=[word for word in words if norm(word[4])==label
                and word[1]>page.rect.height*.55]
        if not labels:
            continue
        label_word=max(labels,key=lambda word:word[1])
        values=[word for word in words
                if 0<word[0]-label_word[2]<140
                and abs((word[1]+word[3]-label_word[1]-label_word[3])/2)<2
                and re.fullmatch(r'\d+(?:[,.]\d+)?',word[4])]
        if values:
            found[field]=num(min(values,key=lambda word:word[0])[4])
    weights=re.findall(r'(?<![\w])([\d.,]+)\s*kg\b',page.get_text(),re.I)
    if len(weights)==1:
        found['unit_weight']=num(weights[0])
    return found

