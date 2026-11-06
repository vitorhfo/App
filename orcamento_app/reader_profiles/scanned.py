"""Extraction rules for scanned layouts; no project selection or persistence."""
from collections import defaultdict
from .common import norm, num, table_measure, material_cell_spec
from .technical import fallback_technical_description
from pathlib import Path
import json, os, re, subprocess, uuid
import pymupdf


def windows_ocr_image_lines(image):
    script=Path(__file__).resolve().parents[1] / 'ocr_windows.ps1'
    if os.name!='nt' or not script.is_file(): return []
    image=Path(image)
    if not image.is_file(): return []
    result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
        '-File',str(script),'-ImagePath',str(image),'-Structured'],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=90)
    if result.returncode or not result.stdout.strip(): return []
    parsed=json.loads(result.stdout)
    return parsed if isinstance(parsed,list) else [parsed]



def windows_ocr_pixmap_lines(pixmap):
    image=(Path(__file__).resolve().parents[1] / 'data')/f'ocr_{uuid.uuid4().hex}.png'
    try:
        pixmap.save(str(image))
        return windows_ocr_image_lines(image)
    finally:
        image.unlink(missing_ok=True)



def windows_ocr_lines(page):
    return windows_ocr_pixmap_lines(page.get_pixmap(matrix=pymupdf.Matrix(2,2)))



def scanned_rise_grid_candidate(ocr_lines):
    """Recognize the 11-column RISE material-list header in a low-res scan."""
    found={}
    for line in ocr_lines:
        if not isinstance(line,dict) or not line.get('text') or line.get('y',0)>90:
            continue
        text=norm(line['text'])
        if 'DESENHO' in text: found['drawing']=line
        if 'DESCRI' in text and 'SIMPLIFICADA' in text: found['description']=line
        if 'GRUPO' in text: found['group']=line
        if 'MATERIAL' in text: found['material']=line
        if 'QTD' in text: found['quantity']=line
        if 'UNID' in text: found['unit']=line
        if 'LARGURA' in text: found['width']=line
        if 'COMPRIMENTO' in text: found['length']=line
        if 'TRATAMENTO' in text: found['finish']=line
        if 'OBSERVA' in text: found['observation']=line
    required={'drawing','description','material','quantity','width','length'}
    if not required.issubset(found):
        return False
    # Reject unrelated OCR tables that happen to reuse generic column labels.
    return (found['drawing']['x'] < found['description']['x']
            < found['material']['x'] < found['quantity']['x']
            and found['width']['x'] < found['length']['x'])



def normalize_ocr_numeric_code(value):
    """Repair common OCR confusions only for fixed-prefix, all-digit IDs."""
    compact=re.sub(r'\s+','',str(value or ''))
    match=re.fullmatch(r'(MP|PC|AC|EM|CJ)([A-Z0-9]{8})',compact,re.I)
    if not match: return compact
    suffix=(match.group(2).upper().replace('O','0').replace('C','0')
            .replace('Q','0').replace('S','5').replace('I','1')
            .replace('L','1').replace('T','1').replace('B','8'))
    return match.group(1).upper()+suffix if suffix.isdigit() else compact



def scanned_rise_grid_bom(page):
    """Read a raster/vector-outline 11-column RISE BOM by its printed grid.

    This layout has no weight column. Gauge/profile are parsed from MATERIAL,
    while only the dedicated LARGURA/COMPRIMENTO cells become cut dimensions;
    stock sheet sizes in MATERIAL never become piece dimensions.
    """
    vertical=defaultdict(list); horizontal=defaultdict(list)
    for drawing in page.get_drawings():
        for item in drawing['items']:
            if item[0]!='l': continue
            first,second=item[1:3]
            dx=abs(first.x-second.x); dy=abs(first.y-second.y)
            low_y,high_y=sorted((first.y,second.y))
            if dx<0.15 and 7<dy<12.5 and 20<low_y<page.rect.height-20:
                vertical[round(first.x,1)].append((low_y,high_y))
            if dy<0.15 and dx>8 and 20<first.y<page.rect.height-20:
                horizontal[round(first.y,1)].append(
                    (min(first.x,second.x),max(first.x,second.x)))
    if not vertical or not horizontal: return []
    strongest=max(len(segments) for segments in vertical.values())
    x_edges=sorted(x for x,segments in vertical.items()
                   if len(segments)>=max(5,strongest*.65))
    if len(x_edges)!=12: return []
    left,right=x_edges[0],x_edges[-1]
    y_edges=[]
    for y,segments in horizontal.items():
        clipped=sum(max(0,min(right,b)-max(left,a)) for a,b in segments)
        if clipped>=(right-left)*.82 and len(segments)>=8:
            y_edges.append(y)
    y_edges=sorted(y_edges)
    runs=[]; run=[]
    for y in y_edges:
        if run and not 7<=y-run[-1]<=12.5:
            if len(run)>=4: runs.append(run)
            run=[]
        run.append(y)
    if len(run)>=4: runs.append(run)
    if not runs: return []
    table_y=max(runs,key=len)
    if len(table_y)<4: return []
    # OCR is much more reliable on enlarged row strips than on a full-page
    # table. Batch ten strips per call to keep Windows OCR startup affordable.
    from io import BytesIO
    from PIL import Image
    data_rows=list(range(1,len(table_y)-1))  # first interval is the header
    cells_by_row=[defaultdict(list) for _ in data_rows]
    explicit_marks=defaultdict(list)
    left=max(page.rect.x0,x_edges[0]); right=min(page.rect.x1,x_edges[-1])
    scale=4; enlargement=2; gap=24; row_gap=20
    table_clip=pymupdf.Rect(left,table_y[0],right,table_y[-1])
    table_pixmap=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),
                                 clip=table_clip,alpha=False)
    table_image=Image.open(BytesIO(table_pixmap.tobytes('png'))).convert('RGB')
    batch_size=10
    for start in range(0,len(data_rows),batch_size):
        row_indices=data_rows[start:start+batch_size]
        strips=[]; segment_lists=[]
        for row_index in row_indices:
            source_top=round((table_y[row_index]-table_y[0])*scale)+1
            source_bottom=round((table_y[row_index+1]-table_y[0])*scale)-1
            row_cells=[]
            for column in range(11):
                source_left=round((x_edges[column]-left)*scale)+1
                source_right=round((x_edges[column+1]-left)*scale)-1
                cell_image=table_image.crop((source_left,source_top,
                                             source_right,source_bottom))
                cell_image=cell_image.resize((cell_image.width*enlargement,
                    cell_image.height*enlargement),Image.Resampling.LANCZOS)
                row_cells.append(cell_image)
            row_width=sum(cell_image.width for cell_image in row_cells)+gap*10
            strip_height=max(cell_image.height for cell_image in row_cells)
            strip=Image.new('RGB',(row_width,strip_height),'white')
            segment_bounds=[]; x_offset=0
            for cell_image in row_cells:
                strip.paste(cell_image,(x_offset,0))
                segment_bounds.append((x_offset,x_offset+cell_image.width))
                x_offset+=cell_image.width+gap
            strips.append(strip); segment_lists.append(segment_bounds)
        composite_height=sum(strip.height for strip in strips)+row_gap*(len(strips)-1)
        composite=Image.new('RGB',(max(strip.width for strip in strips),composite_height),'white')
        offsets=[]; offset=0
        for strip in strips:
            offsets.append(offset); composite.paste(strip,(0,offset)); offset+=strip.height+row_gap
        image=(Path(__file__).resolve().parents[1] / 'data')/f'ocr_{uuid.uuid4().hex}.png'
        try:
            composite.save(image)
            lines=windows_ocr_image_lines(image)
        finally:
            image.unlink(missing_ok=True)
        for line in lines:
            text=str(line.get('text','')).strip()
            if not text: continue
            y=line.get('y',0)
            local_batch=next((i for i,(top,strip) in enumerate(zip(offsets,strips))
                              if top<=y<top+strip.height),None)
            if local_batch is None: continue  # White row separator.
            row_index=row_indices[local_batch]
            x=line.get('x',0)
            column=next((index for index,(cell_left,cell_right) in
                         enumerate(segment_lists[local_batch])
                         if cell_left<=x<cell_right),None)
            if column is None: continue
            if column==0:
                token=norm(text).replace('O','0').replace('I','1').replace('L','1').replace('S','5')
                if re.fullmatch(r'\d{1,3}',token): explicit_marks[row_index].append(int(token))
                continue
            cells_by_row[row_index-1][column].append((y,x,text))

    def cell(values):
        parts=[]; seen=set()
        for _,_,text in sorted(values):
            clean=' '.join(text.split())
            if clean and norm(clean) not in seen:
                parts.append(clean); seen.add(norm(clean))
        return ' '.join(parts).strip()

    def measure(value):
        match=re.search(r'(?<![A-Z])\d{1,4}(?:[.,]\d+)?',str(value or ''),re.I)
        return table_measure(match.group()) if match else 0.0

    observed=[(index-1,values[0]) for index,values in explicit_marks.items() if values]
    if len(observed)<2: return []
    bases=sorted(item_num-index for index,item_num in observed)
    base_num=bases[len(bases)//2]
    rows=[]
    for index,bucket in enumerate(cells_by_row):
        cells={column:cell(bucket.get(column,[])) for column in range(1,11)}
        drawing=normalize_ocr_numeric_code(cells[1].strip('.-'))
        description=cells[2]; group=cells[3]; material=cells[4]
        if not any((drawing,description,group,material,cells[5])): continue
        explicit=explicit_marks.get(index+1,[])
        expected_item=base_num+index
        item_num=(explicit[0] if explicit and explicit[0]==expected_item else expected_item)
        quantity_match=re.match(r'\s*(\d{1,4}(?:[.,]\d+)?)',cells[5])
        quantity=table_measure(quantity_match.group(1)) if quantity_match else 0
        issue=[]
        if not explicit or explicit[0]!=item_num:
            issue.append('Número do item recuperado pela sequência da tabela; conferir OCR.')
        if quantity<=0:
            quantity=1
            issue.append('Quantidade não reconhecida; 1 unidade provisória, conferir PDF.')
        normalized_group=norm(group)
        if 'SUB PRODUTO' in normalized_group or 'SUBCONJUNTO' in normalized_group:
            group='SUB PRODUTO'
        elif 'POLIMER' in normalized_group:
            group='POLIMEROS'
        elif 'ACESSOR' in normalized_group:
            group='ACESSORIOS'
        elif 'EMBALAGEM' in normalized_group:
            group='EMBALAGEM'
        elif 'METAL' in normalized_group:
            group='METAL'
        elif not group and 'SUB PRODUTO' in norm(material):
            group='SUB PRODUTO'
        elif not group and 'POLIMER' in norm(material):
            group='POLIMEROS'
        spec=material_cell_spec(material)
        material_norm=norm(material)
        if 'TUBO' in material_norm and not (spec['width'] and spec['depth'] and spec['thickness']):
            gauge=re.search(r'\bE\s*:?\s*(\d+(?:[,.]\d+)?)\s*MM',material,re.I)
            lengths=re.findall(r'\bL\s*:?\s*(\d+(?:[,.]\d+)?)\s*MM?',material,re.I)
            if gauge and len(lengths)>=2:
                spec.update(thickness=num(gauge.group(1)),width=num(lengths[0]),depth=num(lengths[1]))
        if ('CHAPA' in material_norm or 'PSAI' in material_norm) and not spec['thickness']:
            gauge=re.search(r'\bE\s*:?\s*(\d+(?:[,.]\d+)?)\s*MM',material,re.I)
            if gauge: spec['thickness']=num(gauge.group(1))
        if 'ARAME' in material_norm and not spec['diameter']:
            wire_material=material.upper().replace('O','0').replace('C','0')
            gauge=re.search(r'(\d{1,2}[,.]\d{1,2})\s*MM\b',wire_material,re.I)
            if gauge: spec['diameter']=num(gauge.group(1))
        if not description:
            description=fallback_technical_description(group,material,drawing,
                thickness=spec['thickness'],diameter=spec['diameter'],
                width=spec['width'],depth=spec['depth'],length=measure(cells[8]))
        raw_code=''
        code=re.search(r'[\[{]\s*((?:MP|AC|EM)[A-Z0-9]{5,})\s*[\]}]',material,re.I)
        if code: raw_code=normalize_ocr_numeric_code(code.group(1))
        treatment=cells[9]
        printing_match=re.search(r'\b([014]x[014])\b',treatment,re.I)
        unit_text=norm(cells[6])
        unit='un' if unit_text in ('UN','UNID','UIV','U N','UNIDADE') else (cells[6] or 'un')
        rows.append({'item_num':item_num,'quantity':quantity,
            'description':description,'group':group,'material':material,
            'thickness':spec['thickness'],'diameter':spec['diameter'],
            'width':measure(cells[7]) or spec['width'],'depth':spec['depth'],
            'length':measure(cells[8]),'drawing_id':drawing,
            'unit_weight':0.0,'unit_area':0.0,'raw_code':raw_code,
            'observation':cells[10],'printing_hint':printing_match.group(1).lower() if printing_match else '',
            'printing':printing_match.group(1).lower() if printing_match else '0x0',
            'unit':unit,'finish':treatment,'_ocr_issue':' '.join(issue)})
    return rows



def scanned_technical_bom(ocr_lines):
    """Recover a preliminary BOM from coordinates on a scanned table page."""
    lines=[x for x in ocr_lines if isinstance(x,dict) and x.get('text')]
    def header(label):
        return next((x for x in lines if norm(x['text']).startswith(label)),None)
    item=header('ITEM QTD'); group=header('GRUPO'); material=header('MATERIAL')
    drawing=header('DESENHO'); weight=header('PESO KG')
    if not all((item,group,material,drawing,weight)): return []
    y0=item['y']; x0=item['x']; gx=group['x']; mx=material['x']; dx=drawing['x']; wx=weight['x']
    descriptions=[]
    for line in lines:
        x=line['x']; y=line['y']; value=line['text'].strip()
        if y<=y0+12 or not (x0+65<x<gx-45): continue
        if norm(value) in ('DESCRICAO','PROJETO','ENGENHEIRO','FOLHA'): continue
        has_cell=any(abs(other['y']-y)<13 and
                     (gx-30<other['x']<gx+120 or wx-20<other['x']<wx+80)
                     for other in lines)
        if has_cell: descriptions.append(line)
    descriptions.sort(key=lambda x:x['y'])
    rows=[]
    for i,line in enumerate(descriptions):
        y=line['y']; next_y=descriptions[i+1]['y'] if i+1<len(descriptions) else y+32
        nearby=lambda left,right,low,high: [x for x in lines if left<x['x']<right and low<=x['y']<high]
        quantity_candidates=nearby(x0+30,x0+75,y-5,y+7)
        quantity=next((int(x['text']) for x in quantity_candidates
                       if re.fullmatch(r'\d{1,3}',x['text']) and 0<int(x['text'])<100),None)
        groups=nearby(gx-35,mx-50,y-7,y+10)
        materials=nearby(mx-115,dx-80,y-10,next_y-5)
        weights=nearby(wx-25,wx+90,y-8,y+11)
        drawings=nearby(dx-85,wx-35,y-10,next_y-3)
        raw_weight=next((num(x['text']) for x in weights if re.fullmatch(r'\d+(?:[,.]\d+)?',x['text'])),0.0)
        group_text=' '.join(x['text'] for x in sorted(groups,key=lambda z:z['x']))
        if not group_text and not raw_weight and not drawings: continue
        rows.append({'description':line['text'].strip(),'quantity':quantity,
                     'group':group_text,'material':' '.join(x['text'] for x in sorted(materials,key=lambda z:(z['y'],z['x']))),
                     'drawing_id':' '.join(x['text'] for x in sorted(drawings,key=lambda z:(z['y'],z['x']))),
                     'unit_weight':raw_weight})
    return rows

