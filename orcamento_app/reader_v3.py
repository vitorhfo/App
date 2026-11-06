"""Conservative local PDF reader. Every uncertain field remains reviewable."""
from collections import defaultdict
from pathlib import Path
import re
import shutil
import subprocess
import uuid

import pymupdf

# Keep these public names available to the existing import/repair scripts.
from reader_profiles.common import (
    norm, num, inch_mm, table_measure, table_diameter, material_cell_spec, INCH_SIZE,
)
from reader_profiles.cad import cad_bom
from reader_profiles.cad_part_number import is_part_only_bom, cad_row_details, primary_cad_tables
from reader_profiles.selection import is_technical_pdf
from reader_profiles.technical import (
    technical_grid_bom, ordered_rise_grid_bom, compact_rise_cut_bom,
    technical_drawing_code, technical_subassembly_group, normalize_mdf_grid_dimensions,
    fallback_technical_description, technical_title_dimensions,
)
from reader_profiles.scanned import (
    windows_ocr_image_lines, windows_ocr_pixmap_lines, windows_ocr_lines,
    scanned_rise_grid_candidate, normalize_ocr_numeric_code, scanned_rise_grid_bom,
    scanned_technical_bom,
)
from reader_profiles.rise_text import rise_bom
from reader_profiles.outpromo import (
    outpromo_bom, outpromo_detail_dimensions, outpromo_detail_key, can_base_drawn_dimensions,
)
from reader_profiles.router import read_technical_table, technical_table_bom, record_reading

from calc_engine import calc_sheet, calc_wire, calc_tube_rect, calc_tube_round, resolve_material_group


def side_and_base(description):
    """Return a named right/left variant without guessing from a bare D/E."""
    words=norm(description).split()
    right={'DIREITO','DIREITA','DIR','LD'}
    left={'ESQUERDO','ESQUERDA','ESQ','LE'}
    sides={('direita' if word in right else 'esquerda')
           for word in words if word in right or word in left}
    if len(sides)!=1:
        return None,norm(description)
    base=' '.join(word for word in words if word not in right|left)
    return next(iter(sides)),base


def shared_side_drawing(description, docs):
    """Match a side-specific BOM line to one drawing explicitly showing both sides."""
    side,base=side_and_base(description)
    if not side:
        return None
    candidates=[path for path,info in docs.items()
                if info['stem']==base and not side_and_base(info['stem'])[0]]
    if len(candidates)!=1:
        return None
    drawing=candidates[0]
    words=set(norm(docs[drawing]['text']).split())
    has_right=bool(words & {'DIREITO','DIREITA','DIR','LD'})
    has_left=bool(words & {'ESQUERDO','ESQUERDA','ESQ','LE'})
    return drawing if has_right and has_left else None


def mirror_instruction(text):
    """Accept an explicit drawing instruction, not mere visual similarity."""
    normalized=norm(text)
    return bool(re.search(r'\b(?:MONTAGEM|MONTAR|FAZER|SUBMONTAGEM|LADO|LATERAL|SIMETRIA)\b'
                          r'.{0,90}\b(?:ESPELHO|ESPELHADA|ESPELHADO|ESPELHAR|SIMETRICA|SIMETRICO)\b',
                          normalized))


def page_text(page):
    text = page.get_text()
    if len(text.strip()) > 40:
        return text, False
    if not shutil.which('tesseract'):
        return text, True
    image=Path(__file__).with_name('data')/f'ocr_{uuid.uuid4().hex}.png'
    try:
        page.get_pixmap(matrix=pymupdf.Matrix(2, 2)).save(str(image))
        result = subprocess.run(['tesseract', str(image), 'stdout', '-l', 'por+eng'],
                                capture_output=True, text=True, timeout=45)
        return result.stdout or text, True
    finally:
        image.unlink(missing_ok=True)


def title_weight(text):
    # SolidWorks title block: weight in grams followed by the drawing scale.
    # The scale is not necessarily 1:n (these examples use 2:1).
    m=re.search(r'(?m)^\s*([\d.,]+)\s*\n\s*\d+(?:[.,]\d+)?:\d+(?:[.,]\d+)?\s*\n\s*-\s*\n',text)
    if not m:
        m=re.search(r'(?m)^\s*([\d.,]+)\s*\n\s*\d+(?:[.,]\d+)?:\d+(?:[.,]\d+)?\s*\n',text)
    return num(m.group(1))/1000 if m else 0.0


def title_area(text):
    m=re.search(r'Area\s*-\s*mm\S*\s*\n\s*([\d.,]+)',text,re.I)
    return num(m.group(1))/1_000_000 if m else 0.0


def rise_cover_specifications(page, drawing_code):
    """Read explicitly labelled weight breakdowns from a RISE project cover.

    The cover's "Peso Total" is a project summary; drawing title-block mass is
    a separate CAD property and may disagree. Match the cover to its drawing
    code and read values by row geometry so category totals cannot be mistaken
    for the project total.
    """
    text=page.get_text()
    if not re.search(r'\b'+re.escape(str(drawing_code or ''))+r'\b',text,re.I):
        return {}
    words=page.get_text('words')
    rows=[]
    for word in sorted(words,key=lambda item:((item[1]+item[3])/2,item[0])):
        cy=(word[1]+word[3])/2
        row=next((entry for entry in rows if abs(entry['y']-cy)<=3),None)
        if row is None:
            row={'y':cy,'words':[]}; rows.append(row)
        row['words'].append(word)
    result={}
    labels={
        'PESO TOTAL':'total_weight',
        'PESO TOTAL ACO':'steel_weight',
        'PESO TOTAL POLIMEROS':'polymer_weight',
        'PESO TOTAL MDF':'mdf_weight',
        'QUANTIDADE TOTAL TINTA':'paint_weight',
        'AREA DE IMPRESSAO':'printing_area',
    }
    for row in rows:
        left=' '.join(word[4] for word in sorted(row['words'],key=lambda item:item[0])
                      if word[0]<1000)
        label=norm(left)
        # Some HH GLOBAL title blocks place "DATA DO" in the same row as
        # "Peso Total MDF" because the cells slightly overlap vertically.
        # Match the most specific labelled field contained in that row.
        key=next((field for name,field in sorted(labels.items(),
                       key=lambda item:len(item[0]),reverse=True)
                  if name in label),None)
        if not key: continue
        right=' '.join(word[4] for word in sorted(row['words'],key=lambda item:item[0])
                       if word[0]>=1000)
        number=re.search(r'\d+(?:[.,]\d+)?',right)
        if number:
            result[key]=num(number.group())
    return result if 'total_weight' in result else {}


def cut_table_rows(text, page=None):
    """Read the small material/length/quantity table on a part drawing."""
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    header=next((i for i in range(len(lines)-3)
                if norm(lines[i]) in ('N DO ITEM','NO DO ITEM','N ITEM')
                and norm(lines[i+1])=='MATERIAL'
                and norm(lines[i+2])=='COMPRIMENTO'),None)
    rows=[]
    qty_header=(next((i for i in range(header+3,min(header+9,len(lines)))
                      if norm(lines[i]) in ('QTD','QUANTIDADE')),None)
                if header is not None else None)
    if qty_header is not None:
        width=qty_header-header+1
        start=qty_header+1
        for i in range(start,min(start+80,len(lines)-width+1),width):
            if not re.fullmatch(r'\d{1,3}',lines[i]): break
            material=lines[i+1]
            if not re.search(r'[A-Za-z]',material): break
            if lines[i+2]!='-' and not re.fullmatch(r'\d+(?:[.,]\d+)?',lines[i+2]): break
            if not re.fullmatch(r'\d{1,4}',lines[i+width-1]): break
            length=0.0 if lines[i+2]=='-' else num(lines[i+2])
            qty=int(lines[i+width-1])
            if qty<=0: break
            rows.append({'item_num':int(lines[i]),'material':material,
                         'length':length,'quantity':qty})
    if rows or page is None:
        return rows
    # SolidWorks sometimes interleaves text from other drawing regions in its
    # PDF stream. Crop the actual table using the header's page coordinates.
    words=page.get_text('words')
    materials=[w for w in words if norm(w[4])=='MATERIAL']
    for header in materials:
        y=header[1]
        length_header=next((w for w in words if norm(w[4])=='COMPRIMENTO'
                            and abs(w[1]-y)<4 and w[0]>header[0]),None)
        qty_header=next((w for w in words if norm(w[4]) in ('QTD','QUANTIDADE')
                         and abs(w[1]-y)<4 and w[0]>length_header[0]),None) if length_header else None
        if not qty_header:
            continue
        clip=pymupdf.Rect(max(0,header[0]-110),y-3,
                          min(page.rect.x1,qty_header[2]+30),min(page.rect.y1,y+90))
        for line in page.get_text(clip=clip,sort=True).splitlines()[1:]:
            match=re.match(r'^\s*(\d{1,3})\s+(.+?)\s+(-|\d+(?:[.,]\d+)?)'
                           r'(?:\s+\d+\s*[°º�]){0,2}\s+(\d{1,4})\s*$',line)
            if not match:
                if rows: break
                continue
            material=match.group(2).strip()
            if not re.search(r'[A-Za-z]',material):
                if rows: break
                continue
            length=0.0 if match.group(3)=='-' else num(match.group(3))
            qty=int(match.group(4))
            if qty<=0: break
            rows.append({'item_num':int(match.group(1)),'material':material,
                         'length':length,'quantity':qty})
        if rows:
            break
    return rows


def overall_sheet_dimensions(text):
    """Find two dominant outside dimensions on a developed sheet drawing.

    PDF reading order alone is insufficient: orthographic views and bend
    details contain many other dimensions. Accept the first two drawing
    dimensions only when they are also the uniquely dominant pair.
    """
    before,marker,_=text.partition('PERSPECTIVA')
    if not marker:
        return (0.0,0.0)
    values=[num(line.strip()) for line in before.splitlines()
            if re.fullmatch(r'\s*\d+(?:[.,]\d+)?\s*',line) and num(line.strip())>=10]
    if len(values)<3:
        return (0.0,0.0)
    largest=sorted(values,reverse=True)
    first=sorted(values[:2],reverse=True)
    # Some drawing streams interleave small fold annotations between the two
    # outside dimensions. Two equal, clearly dominant dimensions still form
    # an unambiguous square envelope (e.g. the RECKITT PSAI panel).
    if largest[0]==largest[1] and largest[2]<largest[0]*0.5:
        return (largest[0],largest[1])
    # A close third dimension often belongs to another view or a fold.
    if first!=largest[:2] or first[1]<largest[2]*1.15:
        return (0.0,0.0)
    return tuple(first)


def weight_validated_sheet_dimensions(text, material, thickness, sheet_weight):
    """Resolve one ambiguous flat-sheet view only when its mass is unique.

    The first two drawing dimensions must describe the same view. A nearby
    formed length can compete with the blank length; the title mass may then
    distinguish them without treating the formed length as a cut size.
    """
    if ('CHAPA' not in norm(material).split() or 'MDF' in norm(material)
            or thickness<=0 or sheet_weight<=0):
        return (0.0,0.0)
    before,marker,_=text.partition('PERSPECTIVA')
    if not marker:
        return (0.0,0.0)
    values=[num(line.strip()) for line in before.splitlines()
            if re.fullmatch(r'\s*\d+(?:[,.]\d+)?\s*',line) and num(line.strip())>=10]
    if len(values)<3:
        return (0.0,0.0)
    from mass_math import density
    rho=density(material)
    candidates=set()
    for i,left in enumerate(values[:8]):
        for right in values[i+1:8]:
            mass=left*right*thickness*rho/1_000_000
            # A flat blank can weigh more than the finished part because of
            # cutouts. A lighter blank cannot explain the title mass. Keep
            # only a unique candidate; multiple mass-compatible views are
            # not enough to identify the developed sheet.
            if sheet_weight*0.999<=mass<=sheet_weight*1.10:
                candidates.add(tuple(sorted((left,right),reverse=True)))
    return next(iter(candidates)) if len(candidates)==1 else (0.0,0.0)


def view_validated_sheet_dimensions(page, material, thickness, sheet_weight, text=''):
    """Read overall sheet dimensions from a dimensioned orthographic view.

    This complements text-order parsing for drawings where the BOM/description
    has no dimensions and the sheet outline is interrupted by bends or cuts.
    Numeric annotations must sit on perpendicular sides of a vector view,
    match that view's aspect ratio, and describe enough blank area to account
    for the title-block mass. This avoids taking a nearby side-view depth as a
    sheet dimension.
    """
    normalized_text=norm(text)
    assembly_markers=(
        'LISTA DE MATERIAIS' in normalized_text,
        'SUBCONJUNTO' in normalized_text,
        bool(re.search(r'\bPRODUZIR\b.{0,24}\bCONJUNTOS?\b',normalized_text)),
        bool(re.search(r'\bITEM\s+QTD\b.{0,100}\bDESCRICAO\b.{0,100}\bMATERIAL\b',
                       normalized_text,re.S)),
    )
    if (page is None or any(assembly_markers)
            or 'CHAPA' not in norm(material).split() or 'MDF' in norm(material)
            or thickness<=0):
        return (0.0,0.0)
    words=[]
    for word in page.get_text('words'):
        match=re.fullmatch(r'(\d+(?:[,.]\d+)?)',str(word[4]).strip())
        if not match:
            continue
        value=num(match.group(1))
        if (value<10 or value>5000 or word[0]>page.rect.width*0.75
                or word[1]>page.rect.height*0.78):
            continue
        words.append((value,word))

    view_rects=[]
    for drawing in page.get_drawings():
        rect=drawing['rect']
        if (len(drawing['items'])<30 or rect.width<max(22,page.rect.width*0.025)
                or rect.height<max(45,page.rect.height*0.075)
                or rect.width>page.rect.width*0.52 or rect.height>page.rect.height*0.58
                or rect.x1>page.rect.width*0.75 or rect.y1>page.rect.height*0.78):
            continue
        view_rects.append((rect.width*rect.height,rect))

    from mass_math import calculated_weight
    matches=[]
    for area,rect in view_rects:
        shape_ratio=max(rect.width,rect.height)/min(rect.width,rect.height)
        attached=[]
        for value,word in words:
            x0,y0,x1,y1=word[:4]
            center_x=(x0+x1)/2
            center_y=(y0+y1)/2
            vertical_side=''
            horizontal_side=''
            if y1<=rect.y0 and rect.y0-y1<=max(18,rect.height*0.35):
                vertical_side='above'
            elif y0>=rect.y1 and y0-rect.y1<=max(18,rect.height*0.35):
                vertical_side='below'
            if x1<=rect.x0 and rect.x0-x1<=max(18,rect.width*0.35):
                horizontal_side='left'
            elif x0>=rect.x1 and x0-rect.x1<=max(18,rect.width*0.35):
                horizontal_side='right'
            if vertical_side and rect.x0-rect.width*0.25<=center_x<=rect.x1+rect.width*0.25:
                attached.append((value,vertical_side,'v',center_x,center_y))
            elif horizontal_side and rect.y0-rect.height*0.2<=center_y<=rect.y1+rect.height*0.2:
                attached.append((value,horizontal_side,'h',center_x,center_y))

        for i,left in enumerate(attached):
            for right in attached[i+1:]:
                if left[2]==right[2]:
                    continue
                long_dim,short_dim=sorted((left[0],right[0]),reverse=True)
                dimension_ratio=long_dim/short_dim
                ratio_error=abs(dimension_ratio/shape_ratio-1)
                if ratio_error>0.06:
                    continue
                blank_weight=calculated_weight({'group_name':'Chapa','material':material,
                    'length':long_dim,'width':short_dim,'thickness':thickness})
                # Cutouts can make the stamped part substantially lighter than
                # its rectangular envelope; a heavier stamp cannot be explained
                # by that envelope. Geometry and text position still must agree.
                if sheet_weight>0 and not sheet_weight*0.98<=blank_weight<=sheet_weight*2.0:
                    continue
                distance_score=(abs(left[3]-(rect.x0+rect.x1)/2)/max(rect.width,1)
                                +abs(right[3]-(rect.x0+rect.x1)/2)/max(rect.width,1)
                                +abs(left[4]-(rect.y0+rect.y1)/2)/max(rect.height,1)
                                +abs(right[4]-(rect.y0+rect.y1)/2)/max(rect.height,1))
                matches.append((area,ratio_error,distance_score,(long_dim,short_dim)))

    if not matches:
        return (0.0,0.0)
    # Prefer the largest orthographic view with a matching dimension pair.
    largest_area=max(match[0] for match in matches)
    main_view=[match for match in matches if match[0]>=largest_area*0.85]
    main_view.sort(key=lambda match:(match[1],match[2]))
    best=main_view[0]
    if len(main_view)>1 and main_view[1][3]!=best[3]:
        if main_view[1][1]<=best[1]+0.01 and main_view[1][2]<=best[2]+0.1:
            return (0.0,0.0)
    return best[3]


def details(text, cut_rows=None, page=None):
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    cut_rows=cut_table_rows(text) if cut_rows is None else cut_rows
    title_material=''
    title=re.search(r'LOCAL DIGITAL:\s*\n(.*?)(?=\n\s*\d{2}/\d{2}/\d{4}\s*\n)',
                    text,re.I|re.S)
    if title:
        title_material=' '.join(x.strip() for x in title.group(1).splitlines() if x.strip())
    material_line=next((x for x in lines if re.match(r'^(PSAI|PETG|ACRILICO|ACRÍLICO|CHAPA|ARAME|TUBO|AÇO|ACO)\b',x,re.I)
                        and re.search(r'\b(?:BTC|SAE|INOX|ESP|VIRGEM)\b|[Øø]\s*\d|\d\s*mm\b',x,re.I)),None)
    if material_line is None:
        material_line=next((x for x in lines if re.match(r'^(PSAI|PETG|ACRILICO|ACRÍLICO|CHAPA|ARAME|TUBO|AÇO|ACO)\b',x,re.I)), '')
    mat=cut_rows[0]['material'] if cut_rows else (title_material or material_line)
    th=re.search(r'(?:#|ESP\.?\s*|E:\s*)(\d+(?:[,.]\d+)?)\s*mm',text,re.I)
    dia=re.search(r'[Øø�]\s*(\d+(?:[,.]\d+)?)',mat or '') or re.search(r'[Øø]\s*(\d+(?:[,.]\d+)?)',text)
    pr=re.search(r'\b([014]x[014])\b',text,re.I)
    n=next((i for i,x in enumerate(lines) if 'PERSPECTIVA' in norm(x)),None)
    dims=[]
    if n is not None:
        for x in lines[max(0,n-12):n]:
            if re.fullmatch(r'\d+(?:[,.]\d+)?',x): dims.append(num(x))
    usable=[x for x in dims if x>=10]
    is_linear=bool(re.search(r'\b(?:ARAME|TUBO|BARRA)\b',norm(mat)))
    length=max(usable) if len(usable)==2 or (len(usable)==1 and is_linear and dia) else 0
    width=min(usable) if len(usable)==2 else 0
    # A dimension table describes alternative formed wires. The nearby 35 mm
    # is a bend height, while the developed cuts are in COMPRIMENTO per code.
    from wire_variants import parse_parameterized_wire_table
    if parse_parameterized_wire_table(text):
        length=0.0
        width=0.0
    if (not length and not is_linear and not cut_rows and
            re.search(r'\b(?:PSAI|PETG|ACRILICO|POLIONDA|CHAPA)\b',norm(mat))):
        length,width=overall_sheet_dimensions(text)
        sheet_thickness=num(th.group(1)) if th else material_cell_spec(mat)['thickness']
        pdf_mass=title_weight(text)
        if length and width and 'CHAPA' in norm(mat).split() and 'MDF' not in norm(mat) \
                and sheet_thickness>0 and pdf_mass>0:
            from mass_math import density
            gross=length*width*sheet_thickness*density(mat)/1_000_000
            if not pdf_mass*0.999<=gross<=pdf_mass*1.10:
                length,width=0.0,0.0
        if not length:
            length,width=weight_validated_sheet_dimensions(text,mat,sheet_thickness,pdf_mass)
        if not length:
            length,width=view_validated_sheet_dimensions(page,mat,sheet_thickness,pdf_mass,text)
    depth=0.0
    # For a formed wire, the overall drawing dimensions describe the bend;
    # the cut-table length is the true developed length of raw material.
    if cut_rows and all(norm(row['material'])==norm(cut_rows[0]['material']) for row in cut_rows):
        length=(sum(row['length']*row['quantity'] for row in cut_rows)
                if all(row['length']>0 for row in cut_rows) else 0)
        width=0
    profile=re.search(r'(\d+(?:[,.]\d+)?)\s*[xX]\s*(\d+(?:[,.]\d+)?)\s*[xX]\s*'
                      r'(\d+(?:[,.]\d+)?)\s*mm',mat or '',re.I)
    if profile and 'TUBO' in norm(mat):
        width,depth=num(profile.group(1)),num(profile.group(2))
        if not cut_rows:
            # On a straight tube drawing, the first overall dimension is the
            # unique longest one. Shorter numbers usually mark holes and slots.
            # Repeated longest dimensions (bent parts) stay unresolved.
            beginning=text.split('PERSPECTIVA',1)[0]
            if beginning==text:
                weight_header=re.search(r'(?m)^\s*[\d.,]+\s*\n\s*\d+(?:[.,]\d+)?:\d+(?:[.,]\d+)?\s*\n',text)
                beginning=text[:weight_header.start()] if weight_header else ''
            values=[num(x.strip()) for x in beginning.splitlines()
                    if re.fullmatch(r'\s*\d+(?:[,.]\d+)?\s*',x)]
            larger=[x for x in values if x>2*max(width,depth)]
            if larger:
                longest=max(larger)
                if values[0]==longest and sum(abs(x-longest)<1e-6 for x in larger)==1:
                    length=longest
                else:
                    length=0
    thickness=num(profile.group(3)) if profile and 'TUBO' in norm(mat) else (num(th.group(1)) if th else 0)
    spec=material_cell_spec(mat)
    if not thickness and spec['thickness']:
        thickness=spec['thickness']
    is_round_inch=bool(re.search(r'\bTUBO\b.*\bRED\b',mat,re.I) and spec['diameter']>0)
    is_flat_iron=bool(re.search(r'\bFERRO\s+(?:CHATO|LAMINADO)\b',mat,re.I)
                      and spec['width']>0 and spec['thickness']>0)
    if is_round_inch or is_flat_iron:
        thickness=spec['thickness']
        if is_round_inch:
            dia_value=spec['diameter']
        else:
            dia_value=0.0
            width=spec['width']
        if not cut_rows and title_weight(text)>0:
            from mass_math import calculated_weight
            beginning=text.split('PERSPECTIVA',1)[0]
            candidates={num(line.strip()) for line in beginning.splitlines()
                        if re.fullmatch(r'\s*\d+(?:[,.]\d+)?\s*',line)}
            matching=[]
            for candidate in candidates:
                geometry=dict(group_name='Tubo Redondo' if is_round_inch else 'Chapa',
                              material=mat,length=candidate,width=spec['width'],
                              radius_diam=spec['diameter'],thickness=thickness)
                gross=calculated_weight(geometry)
                if gross>0 and abs(gross-title_weight(text))/title_weight(text)<=0.05:
                    matching.append(candidate)
            if len(matching)==1:
                length=matching[0]
    else:
        dia_value=num(dia.group(1)) if dia else 0
    return {'material':mat,'thickness':thickness,
            'diameter':dia_value,
            'printing':pr.group(1).lower() if pr else '0x0',
            'length':length,'width':width,'depth':depth,
            'cut_table_rows':cut_rows,
            'unit_weight':title_weight(text),'unit_area':title_area(text)}


def parameterized_details(text, description):
    """Resolve a BOM suffix (for example - 625) using MEDIDA A in one PDF."""
    suffix=re.search(r'\s-\s(\d+(?:[,.]\d+)?)\s*$',description)
    table=re.search(r'MEDIDA\s*["“]?A["”]?\s*\n',text,re.I)
    if not suffix or not table:
        return None
    requested=num(suffix.group(1))
    codes=[]
    for line in text[table.end():].splitlines():
        line=line.strip()
        if re.fullmatch(r'\d+(?:[,.]\d+)?',line):
            codes.append(num(line))
        else:
            break
    if not codes or requested not in codes or codes[0]<=0:
        return None
    reference=codes[0]
    result=details(text)
    result['length']=requested
    result['unit_weight']=round(title_weight(text)*requested/reference,6)
    result['unit_area']=round(title_area(text)*requested/reference,6)
    # On a flat sheet with an "A" length, the one other standalone drawing
    # dimension is its width. Check it against the reference variant's title
    # mass so an angle or another view cannot silently become a cut size.
    if 'CHAPA' in norm(result['material']).split() and result['thickness']>0:
        result['width']=0.0
        before,marker,_=text.partition('PERSPECTIVA')
        fixed=[num(line.strip()) for line in before.splitlines()
               if re.fullmatch(r'\s*\d+(?:[,.]\d+)?\s*',line)] if marker else []
        if len(fixed)==1 and fixed[0]>0 and title_weight(text)>0:
            from mass_math import density
            gross=reference*fixed[0]*result['thickness']*density(result['material'])/1_000_000
            if abs(gross-title_weight(text))/title_weight(text)<=0.03:
                result['width']=fixed[0]
    profile=re.search(r'TUBO[^\n]*\n\s*(\d+(?:[,.]\d+)?)\s*[xX]\s*'
                      r'(\d+(?:[,.]\d+)?)\s*[xX]\s*(\d+(?:[,.]\d+)?)\s*mm',text,re.I)
    if profile:
        result['width']=num(profile.group(1))
        result['depth']=num(profile.group(2))
        result['thickness']=num(profile.group(3))
        if not result['material']:
            result['material']=f'TUBO {profile.group(1)}x{profile.group(2)}x{profile.group(3)} mm'
    return result


def source_ref(root,path,page=1):
    return f'{path.relative_to(root).as_posix()}#page={page}'


def empty_item(desc,qty,source,group='',parent='',**fields):
    from item_types import infer_item_type
    source_group=fields.pop('source_group','')
    item_type=fields.pop('item_type',None)
    entry=dict(item_num=0,description=desc,group_name=group or resolve_material_group(desc,fields.get('material','')),
        material='',thickness=0.0,radius_diam=0.0,width=0.0,depth=0.0,length=0.0,
        quantity=qty,unit='un',unit_weight=0.0,total_weight=0.0,unit_area=0.0,total_area=0.0,
        drawing_id='',raw_code='',finish='',printing='0x0',unit_price=None,total_price=None,
        price_source='',source_page=source,confidence=0.5,parent_assembly=parent,
        is_consolidated=0,is_inferred=0,pending_issue='',observation='')
    entry.update(fields)
    entry['item_type']=item_type or infer_item_type(desc,entry['group_name'],source_group,
        entry['drawing_id'],any(entry[k] for k in ('thickness','radius_diam','width','depth','length')),
        entry['pending_issue'])
    if entry['item_type']=='subconjunto':
        entry['group_name']='Subconjunto'
        if not entry['pending_issue']:
            entry['pending_issue']='Subconjunto sem lista detalhada; conferir composição.'
    return entry


def cut_table_materials(description, assembly_quantity, source, parent, drawing_id,
                        detail, raw_code=''):
    """Expand every cut-table line into its own priced piece.

    A drawing's title weight belongs to the entire welded/assembled part.
    It must not be copied onto each tube and wire from its cut list.
    """
    from mass_math import calculated_weight

    rows=detail.get('cut_table_rows') or []
    items=[]
    for row in rows:
        material=re.sub(r'�(?=\s*\d)','Ø',row['material']).strip()
        group=resolve_material_group(description,material)
        parsed=material_cell_spec(material)
        length=row['length']; qty=assembly_quantity*row['quantity']
        name=(f'{description} — corte {row["item_num"]}: {material}, '
              + (f'{length:g} mm' if length>0 else 'comprimento variável'))
        if group=='Arame' and parsed['diameter']:
            area=3.141592653589793*parsed['diameter']*length/1_000_000
        elif group=='Tubo Quadrado/Retangular' and parsed['width'] and parsed['depth']:
            area=2*(parsed['width']+parsed['depth'])*length/1_000_000
        else:
            area=0.0
        item=empty_item(name,qty,source,group,parent,
            material=material,thickness=parsed['thickness'],
            radius_diam=parsed['diameter'],width=parsed['width'],depth=parsed['depth'],
            length=length,drawing_id=f'{drawing_id}: corte {row["item_num"]}',
            raw_code=raw_code,unit_area=round(area,6),total_area=round(area*qty,6),
            confidence=0.9,observation=(f'Quadro de corte do desenho: item {row["item_num"]}, '
                f'{row["quantity"]} peça(s) por conjunto. Peso do título refere-se ao conjunto completo.'))
        if length<=0:
            item['pending_issue']='Comprimento variável no quadro de corte; selecionar a variante do produto antes de calcular peso e preço.'
            item['confidence']=0.6
        items.append(item)
    gross=[calculated_weight(item) for item in items]
    total_gross=sum(weight*row['quantity'] for weight,row in zip(gross,rows))
    pdf_weight=detail.get('unit_weight') or 0.0
    complete=bool(items) and all(weight>0 for weight in gross)
    for item,weight in zip(items,gross):
        if complete and pdf_weight>0:
            item['unit_weight']=pdf_weight*weight/total_gross
            item['observation']+=(' Peso total do desenho distribuído entre os cortes '
                                   'pela proporção da massa bruta calculada.')
        elif weight<=0 and not item['pending_issue']:
            item['pending_issue']='Perfil ou diâmetro do material não reconhecido; conferir peso individual.'
            item['confidence']=0.6
        item['total_weight']=round(item['unit_weight']*item['quantity'],6)
    return items


def finish_materials(data):
    # The project families use different BOM column layouts. Fill only fields
    # absent from a detail drawing; never replace the measured cut geometry.
    for item in data['materials']:
        parsed=material_cell_spec(item.get('material',''))
        if not item.get('thickness') and parsed['thickness']:
            item['thickness']=parsed['thickness']
        if not item.get('radius_diam') and parsed['diameter']:
            item['radius_diam']=parsed['diameter']
        if not item.get('width') and parsed['width']:
            item['width']=parsed['width']
        if not item.get('depth') and parsed['depth']:
            item['depth']=parsed['depth']
        if (parsed['observation'] and
                'Chapa comercial' not in (item.get('observation') or '') and
                parsed['observation'] not in (item.get('observation') or '')):
            item['observation']=' '.join(x for x in (item.get('observation'),parsed['observation']) if x)
    # Consolidate only identical drawing/material/geometry; keep distinct left/right variants.
    merged={}
    retained=[]
    for item in data['materials']:
        side,_=side_and_base(item['description'])
        key=(item['item_type'],item['parent_assembly'],side,norm(item['description']),
             norm(item['drawing_id']),norm(item['material']),item['thickness'],item['width'],
             item['depth'],item['length'],item['radius_diam'],item['printing'])
        if side and key in merged:
            target=merged[key]; target['quantity']+=item['quantity']
            target['total_weight']=round(target['unit_weight']*target['quantity'],4)
            target['total_area']=round(target['unit_area']*target['quantity'],4)
            target['is_consolidated']=1
        else:
            if side: merged[key]=item
            retained.append(item)
    data['materials']=consolidate_mirrored_materials(retained)
    from mass_math import reconcile_item_weight
    from wire_allowance import apply_wire_allowance
    for item in data['materials']:
        reconcile_item_weight(item)
        apply_wire_allowance(item)
    for i,item in enumerate(data['materials'],1): item['item_num']=i
    return data


def consolidate_mirrored_materials(materials):
    """Count a verified mirrored component once, with both sides in quantity.

    Counterparts with the same drawing, geometry and unit values are merged,
    whether the second page was read directly or inferred from an instruction.
    Distinct drawings and differently priced variants remain separate.
    """
    from collections import defaultdict

    groups=defaultdict(lambda: defaultdict(list))
    for item in materials:
        if item.get('item_type')=='subconjunto' or item.get('mirrored_assembly'):
            continue
        parent=item.get('parent_assembly') or ''
        prefix,separator,last=parent.rpartition(' / ')
        side,base=side_and_base(last)
        if not separator or not side or not base:
            continue
        signature=(norm(prefix),base,norm(item.get('description')),
                   norm(item.get('drawing_id')),item.get('item_type'),
                   item.get('group_name'),norm(item.get('material')),
                   item.get('unit'),
                   *(round(float(item.get(field) or 0),5) for field in
                     ('thickness','radius_diam','width','depth','length',
                      'unit_weight','unit_area')),
                   item.get('unit_price'),item.get('price_source'))
        groups[signature][side].append(item)
    removed=set()
    for sides in groups.values():
        right=sides.get('direita',[])
        left=sides.get('esquerda',[])
        if len(right)!=1 or len(left)!=1:
            continue
        a,b=right[0],left[0]
        source,mirror=(b,a) if a.get('is_inferred') else (a,b)
        if not (source.get('quantity') and mirror.get('quantity')):
            continue
        source['quantity']=float(source['quantity'])+float(mirror['quantity'])
        source['total_weight']=round((source.get('unit_weight') or 0)*source['quantity'],4)
        source['total_area']=round((source.get('unit_area') or 0)*source['quantity'],4)
        if source.get('unit_price') is not None:
            source['total_price']=round(source['unit_price']*source['quantity'],2)
        source['mirrored_assembly']=mirror['parent_assembly']
        source['is_consolidated']=1
        note=f"Quantidade inclui os lados direito e esquerdo; desenho espelhado: {mirror['parent_assembly']}."
        source['observation']=' '.join(x for x in (source.get('observation') or '',note) if x)
        removed.add(id(mirror))
    return [item for item in materials if id(item) not in removed]


def score_package_materials(data, root, path, pdf, bom, cuts):
    """Expand the continued SCORE BOM without pricing welded parent rows."""
    from score_package import drawing_code, split_sheet_flat_bar
    from score_quote_reference import (confirmed_brahma_additions,
                                       confirmed_brahma_reinforcements,
                                       confirmed_brahma_sheet_cut)
    data['code']='AMB_2239_25_03' if path.stem.upper().startswith('AMB_2239_25') else path.stem
    reinforcement_reference=confirmed_brahma_reinforcements(path)
    sheet_cut_reference=confirmed_brahma_sheet_cut(path)
    detail_pages={}
    for page_number, page in enumerate(pdf, 1):
        body=page.get_text()
        code=drawing_code(body)
        if code:
            detail_pages[code]=(page_number,body)
    weights=[num(match) for match in re.findall(
        r'(\d+(?:[,.]\d+)?)\s*kg\b', pdf[0].get_text(), re.I)]
    if weights:
        data['nominal_weight_pdf']=max(weights)
    assemblies={row['drawing_id']:row for row in bom
                if row['item_num'] and '_ASM_' in row['drawing_id']}
    current=None
    last_numbered=None
    component_index=0
    for row in bom:
        desc=row['description']
        code=row['drawing_id'] or row['description']
        source=source_ref(root,path,row['page'])
        if row['item_num']:
            last_numbered=row
            component_index=0
        elif last_numbered and row['page']==last_numbered['page']:
            # A detail BOM may repeat the constituents already opened by the
            # referenced cut table, or call the same sheet blank simply Sheet.
            # These are local aliases, not extra stock pieces. Continuations
            # of an ASM across pages remain eligible below.
            if last_numbered['drawing_id'] in cuts:
                continue
            if re.search(r'[Ø�]\s*\d+(?:[,.]\d+)?\s*[xX×]\s*\d+(?:[,.]\d+)?\s*\(?\s*LINEAR',
                         last_numbered['dimensions'],re.I):
                continue
            if (norm(desc)=='SHEET' and
                    'CHAPA' in norm(last_numbered['material']) and
                    re.search(r'\d+\s*[xX×]\s*\d+',last_numbered['dimensions'])):
                continue
            if ('+' in last_numbered['dimensions'] and
                    'TUBO' in norm(last_numbered['dimensions'])):
                component_index+=1
                code=f"{last_numbered['drawing_id']}: componente {component_index}"
                desc=f"{last_numbered['description']} — {desc} {component_index}"
        owner=assemblies.get(row.get('owner_assembly',''))
        if row['item_num'] and '_ASM_' in row['drawing_id']:
            current=row
            parent=(root.name+' / '+owner['description']) if owner else root.name
            assembly_quantity=row['quantity']*(owner['quantity'] if owner else 1)
            group=empty_item(desc,assembly_quantity,source,'Subconjunto',parent,
                item_type='subconjunto',drawing_id=code,unit_weight=row['unit_weight'],
                total_weight=row['unit_weight']*assembly_quantity,
                confidence=.95,pending_issue=' ',
                observation='Estrutura da lista SCORE; filhos contabilizados separadamente.')
            group['pending_issue']=''
            data['materials'].append(group)
            continue
        if row['item_num']:
            current=None
        component_parent=(last_numbered if not row['item_num'] and
                          last_numbered and '+' in last_numbered['dimensions'] and
                          'TUBO' in norm(last_numbered['dimensions']) else None)
        active_parent=owner or current
        parent=(root.name+' / '+active_parent['description']) if active_parent else root.name
        quantity=row['quantity']*(active_parent['quantity'] if active_parent else 1)
        if component_parent:
            parent+=' / '+component_parent['description']
            quantity*=component_parent['quantity']
        cut=cuts.get(row['drawing_id'])
        if cut:
            group=empty_item(desc,quantity,source,'Subconjunto',parent,
                item_type='subconjunto',drawing_id=code,
                unit_weight=row['unit_weight'],total_weight=quantity*row['unit_weight'],
                confidence=.9,pending_issue=' ',
                observation=' '.join(x for x in (
                    f'Conjunto soldado: quadro de corte na página {cut["page"]}.',
                    row.get('weight_note','')) if x))
            group['pending_issue']=''
            data['materials'].append(group)
            cut_source=source_ref(root,path,cut['page'])
            components=cut_table_materials(desc,quantity,cut_source,parent+' / '+desc,
                code,dict(cut_table_rows=cut['rows'],unit_weight=row['unit_weight']))
            for component in components:
                if row.get('weight_note'):
                    component['observation']+=' '+row['weight_note']
                if component['material'].casefold()=='sheet':
                    component['group_name']='Chapa'
                    component['item_type']='materia_prima'
                    reference=sheet_cut_reference.get(component['drawing_id'])
                    if reference:
                        component.update(material='Chapa aço carbono',
                            length=reference['length'],width=reference['width'],
                            thickness=reference['thickness'],
                            unit_area=reference['length']*reference['width']/1_000_000,
                            total_area=reference['length']*reference['width']*component['quantity']/1_000_000,
                            confidence=.9,pending_issue='')
                        component['observation']+=(
                            f' Cotas da aba no desenho SCORE página {cut["page"]}; '
                            f'conferidas com {reference["source"]}.')
                    else:
                        component['pending_issue']='Chapa do quadro de corte sem cotas desenvolvidas e espessura; conferir desenho antes de precificar.'
                        component['observation']+=' Material da peça base: '+row['material']+'.'
            data['materials'].extend(components)
            continue
        reference_components=reinforcement_reference.get(row['drawing_id'])
        if reference_components and row['drawing_id'] in detail_pages:
            detail_page=detail_pages[row['drawing_id']][0]
            detail_source=source_ref(root,path,detail_page)
            assembly=empty_item(desc,quantity,source,'Subconjunto',parent,
                item_type='subconjunto',drawing_id=code,unit_weight=row['unit_weight'],
                total_weight=quantity*row['unit_weight'],confidence=.8,
                observation='Reforço soldado: tubo e chapas lançados separadamente conforme orçamento concluído.')
            assembly['pending_issue']=''
            data['materials'].append(assembly)
            for suffix,length,width,depth,gauge,quote_source in reference_components:
                is_tube=suffix=='tubo'
                group='Tubo Quadrado/Retangular' if is_tube else 'Chapa'
                material=(f'Tubo quadrado aço carbono {width:g}x{depth:g}x{gauge:g}mm'
                          if is_tube else 'Chapa aço carbono')
                area=(2*(width+depth)*length if is_tube else length*width)/1_000_000
                piece=empty_item(f'{desc} — {suffix}',quantity,detail_source,
                    group,parent+' / '+desc,item_type='materia_prima',
                    material=material,length=length,width=width,depth=depth,
                    thickness=gauge,drawing_id=f'{code}: componente {suffix}',
                    unit_area=round(area,6),total_area=round(area*quantity,6),
                    confidence=.8,is_inferred=1,
                    pending_issue='Bitola ou planificação adotada do orçamento manual; conferir para produção.',
                    observation=f'{quote_source}. PDF página {detail_page}; o carimbo pesa o reforço montado, não cada componente.')
                data['materials'].append(piece)
            continue
        material=re.sub(r'(?i)acr.lico', 'Acrílico', row['material'])
        material=material.replace('a�o','aço').replace('A�o','Aço')
        dimension=row['dimensions']
        composite='+' in dimension or 'TUBO E CHAPA' in norm(dimension)
        detail=detail_pages.get(row['drawing_id'])
        sheet_bar=(split_sheet_flat_bar(detail[1]) if composite and detail else None)
        if sheet_bar:
            detail_source=source_ref(root,path,detail[0])
            assembly=empty_item(desc,quantity,source,'Subconjunto',parent,
                item_type='subconjunto',drawing_id=code,unit_weight=row['unit_weight'],
                total_weight=quantity*row['unit_weight'],confidence=.9,
                observation='Composição explícita de chapa e ferro chato no desenho; filhos contabilizados separadamente.')
            assembly['pending_issue']=''
            data['materials'].append(assembly)
            component_parent=parent+' / '+desc
            for suffix,component_material,length,width,gauge,issue in (
                ('chapa','Chapa aço carbono',sheet_bar['sheet_length'],
                 sheet_bar['sheet_width'],sheet_bar['sheet_gauge'],''),
                ('ferro chato','Ferro chato aço carbono',sheet_bar['bar_length'],
                 sheet_bar['bar_width'],sheet_bar['bar_gauge'],
                 'Tarifa de ferro chato pendente; não usar automaticamente o preço da chapa.')):
                piece=empty_item(f'{desc} — {suffix}',quantity,detail_source,'Chapa',
                    component_parent,item_type='materia_prima',material=component_material,
                    length=length,width=width,thickness=gauge,
                    drawing_id=f'{code}: componente {suffix}',confidence=.9,
                    pending_issue=issue,
                    observation=f'Componente separado pela nota do desenho SCORE na página {detail[0]}; peso do carimbo refere-se à composição completa.')
                data['materials'].append(piece)
            continue
        if composite and 'TUBO' in norm(dimension):
            assembly=empty_item(desc,quantity,source,'Subconjunto',parent,
                item_type='subconjunto',drawing_id=code,unit_weight=row['unit_weight'],
                total_weight=quantity*row['unit_weight'],confidence=.85,
                observation='Composição de tubo e chapa: linhas físicas abaixo do item; cortes pendentes quando a tabela não os informa.')
            assembly['pending_issue']=''
            data['materials'].append(assembly)
            continue
        linear_wire=re.search(
            r'[Ø�]\s*(\d+(?:[,.]\d+)?)\s*[xX×]\s*(\d+(?:[,.]\d+)?)\s*\(?\s*LINEAR',
            dimension,re.I)
        is_wire=bool(linear_wire) or 'ARAME' in norm(dimension+' '+material)
        if is_wire:
            diameter=re.search(r'[Ø�]\s*(\d+(?:[,.]\d+)?)',dimension,re.I)
            if diameter:
                material=f'Arame Ø{diameter.group(1)} mm — '+material
        group=('Arame' if is_wire else resolve_material_group(desc,material))
        if 'ACRIL' in norm(material): group='Polímero/PSAI'
        if 'TUBO' in norm(material): group='Tubo Quadrado/Retangular'
        values=re.search(r'(\d+(?:[,.]\d+)?)\s*[xX×]\s*'
                         r'(\d+(?:[,.]\d+)?)'
                         r'(?:\s*[xX×]\s*(\d+(?:[,.]\d+)?))?',dimension)
        dimensions=[num(value) for value in values.groups()] if values else [0,0,0]
        length=width=depth=thickness=diam=0.0
        issue=''
        observation=row.get('weight_note','')
        if is_wire:
            diam=material_cell_spec(material)['diameter']
            if linear_wire:
                diam=num(linear_wire.group(1))
                length=num(linear_wire.group(2))
                observation=f'Corte linear explícito na lista: {dimension}.'
            else:
                issue='Comprimento desenvolvido do arame não indicado; cotas gerais não representam o corte.'
                observation=(f'Cotas externas da peça: {dimension}. '
                             'Sem comprimento desenvolvido; não inferir do peso.')
        elif group=='Tubo Quadrado/Retangular':
            issue=('Composição de tubo e chapa sem quadro de cortes; conferir cada material.'
                   if composite else 'Comprimento e perfil dos cortes de tubo não indicados; cotas gerais não representam o corte.')
            observation=f'Cotas externas da peça: {dimension}.'
        elif composite:
            issue='Composição de chapa e ferro chato sem cortes separados; conferir desenvolvimento e espessura.'
            observation=f'Cotas externas da composição: {dimension}.'
        elif values and group in ('Chapa','Polímero/PSAI'):
            length,width=dimensions[:2]
            if dimensions[2] and dimensions[2]<=10:
                thickness=dimensions[2]
            elif group=='Chapa':
                depth=dimensions[2]
                issue='Cota externa de chapa dobrada; espessura e corte desenvolvido não indicados.'
                observation=f'Cotas externas da peça: {dimension}.'
            if group=='Polímero/PSAI' and not thickness:
                issue='Espessura da peça comprada não indicada; conferir antes de precificar.'
        elif values:
            observation=f'Cotas gerais informadas na lista: {dimension}; sem corte unitário confirmado.'
        else:
            issue='Sem cotas individuais na lista de materiais; conferir desenho e fornecedor.'
        area=length*width/1_000_000 if length and width else 0.0
        item=empty_item(desc,quantity,source,group,parent,material=material,
            thickness=thickness,radius_diam=diam,width=width,depth=depth,length=length,
            drawing_id=code,finish=row['finishing'],unit_weight=row['unit_weight'],
            total_weight=round(quantity*row['unit_weight'],6),unit_area=round(area,6),
            total_area=round(quantity*area,6),confidence=.9 if not issue else .65,
            pending_issue=issue,observation=observation)
        if group=='Chapa' and not issue and row['unit_weight']>0:
            from mass_math import calculated_weight
            gross=calculated_weight(item)
            if gross>row['unit_weight']*1.1:
                item['pending_issue']=(
                    f'Peso bruto pelas cotas ({gross:.3f} kg) excede o peso da folha '
                    f'({row["unit_weight"]:.3f} kg); conferir espessura, recortes ou perfuração.')
                item['confidence']=.65
        data['materials'].append(item)
    for addition in confirmed_brahma_additions(path):
        piece=empty_item(addition['description'],addition['quantity'],
            source_ref(root,path,36),'Chapa',root.name+' / '+addition['parent'],
            item_type='materia_prima',material='Chapa aço carbono',
            length=addition['length'],width=addition['width'],
            thickness=addition['thickness'],drawing_id=addition['drawing_id'],
            confidence=.85,is_inferred=0,
            pending_issue='Peça confirmada no orçamento manual, sem desenho individual vinculado; conferir para produção.',
            observation=f"{addition['source']}. {addition['note']} Confirmado pelo usuário; não confundir com a peça de mesmo tamanho.")
        data['materials'].append(piece)
    # Apply geometry and mass after PDF parts and the signed-off quote additions.
    finish_materials(data)
    data['pending_decisions'].append({'title':'Pacote SCORE preliminar',
        'description':f'{path.name}: a lista de materiais foi aberta; conferir os cortes ainda sem desenvolvimento e a massa do conjunto antes do orçamento final.',
        'impact_level':'ALTO'})
    physical_weight=sum(item['total_weight'] for item in data['materials']
                        if item['item_type']!='subconjunto')
    if data['nominal_weight_pdf'] and abs(physical_weight-data['nominal_weight_pdf'])>max(1, data['nominal_weight_pdf']*.05):
        data['pending_decisions'].append({'title':'Peso do conjunto não fecha',
            'description':f'Soma dos pesos de consumo {physical_weight:.3f} kg; carimbo do pacote {data["nominal_weight_pdf"]:.3f} kg. A lista de peças acabadas e os brutos de corte devem ser conferidos separadamente.',
            'impact_level':'ALTO'})
    return data


def select_technical_root(tables, page_codes, assembly_code_pattern):
    """Start at the parent sheet of the selected PDF, not its longest BOM.

    When a project folder contains both production drawings and reference
    material, prefer the production drawings before comparing BOM sizes. A
    scanned historical/reference BOM must not displace the current project
    root merely because OCR found more rows in it.
    Within that package, an assembly referenced by another table is a child;
    the first unreferenced sheet is the root of that package.
    """
    project_tables=[entry for entry in tables
                    if any(norm(part)=='PROJETO' for part in entry[0].parts)]
    if project_tables:
        tables=project_tables
    anchor=max(tables,key=lambda x:(len(x[2]),-len(x[0].parts)))
    same_pdf=[entry for entry in tables if entry[0]==anchor[0]]
    referenced={norm(match.group()) for entry in same_pdf for row in entry[2]
                for match in re.finditer(assembly_code_pattern,
                                         row.get('drawing_id',''),re.I)}
    roots=[entry for entry in same_pdf
           if not page_codes.get((entry[0],entry[1],id(entry[2])),
                                 page_codes.get((entry[0],entry[1]))) or
              page_codes.get((entry[0],entry[1],id(entry[2])),
                             page_codes.get((entry[0],entry[1]))) not in referenced]
    return min(roots or same_pdf,key=lambda entry:entry[1])


def select_bom_package_root(candidates, root_name=''):
    """Choose a parent BOM by its references to other BOM-bearing PDFs.

    Uploaded folders are often named ``source`` or ``PROJETO`` rather than
    after the product. In that case filename-prefix ranking can select the
    largest child module as the quote root. A BOM row that uniquely names
    another BOM PDF is evidence of a parent-to-child link; prefer the unique
    candidate that is not referenced by another candidate. Return ``None``
    when the package has multiple plausible roots so callers can retain their
    existing ambiguity handling.
    """
    if not candidates:
        return None
    paths=[path for path,_ in candidates]
    incoming=set()
    for parent_path,info in candidates:
        for _,rows in info.get('boms',[]):
            for row in rows:
                description=norm(row.get('description',''))
                if not description:
                    continue
                matches=[path for path in paths if path!=parent_path and
                         (norm(path.stem)==description or
                          norm(path.stem).startswith(description+' '))]
                if len(matches)==1:
                    incoming.add(matches[0])
    roots=[path for path in paths if path not in incoming]
    if len(roots)==1:
        return roots[0]
    normalized_root=norm(root_name)
    if normalized_root:
        preferred=[path for path in roots or paths
                   if norm(path.stem).startswith(normalized_root)]
        if len(preferred)==1:
            return preferred[0]
    return None


def process_complete_project(project_folder, approved_rules=None):
    root=Path(project_folder).resolve()
    if not root.is_dir(): raise ValueError('Pasta do projeto não encontrada')
    pdfs=sorted(p for p in root.rglob('*') if p.is_file()
                and is_technical_pdf(p.relative_to(root)))
    data=dict(name=root.name,code='',nominal_weight_pdf=0.0,nominal_area_pdf=0.0,
              materials=[],wire_variants=[],tree={'name':root.name,'children':[]},pending_decisions=[],
              reading_report={'version':1,'documents':[],'events':[]})
    if not pdfs:
        data['pending_decisions'].append({'title':'Sem PDF técnico','description':'Importe desenho ou preencha a lista manualmente.','impact_level':'ALTO'})
        return data
    docs={}; scanned=[]
    for path in pdfs:
        try:
            with pymupdf.open(path) as doc:
                pages=[page_text(page) for page in doc]
                cut_rows=[row for page in doc
                          for row in cut_table_rows(page.get_text(),page)]
            text='\n'.join(x[0] for x in pages)
            if any(x[1] for x in pages): scanned.append(str(path.relative_to(root)))
            boms=[]; seen_rows=set()
            with pymupdf.open(path) as source_doc:
                for n,(page_body,_) in enumerate(pages):
                    fresh=[]
                    for row in cad_bom(page_body,source_doc[n]):
                        signature=(row['item_num'],norm(row['description']),row['quantity'],row['raw_code'])
                        if signature not in seen_rows:
                            fresh.append(row); seen_rows.add(signature)
                    if fresh:
                        boms.append((n+1,fresh))
                        profile=('cad_part_number' if any(r.get('cad_layout')=='part_number_grid'
                                                        for r in fresh) else
                                 'cad_named_grid' if any(r.get('cad_layout') for r in fresh) else 'cad')
                        record_reading(data,source_ref(root,path,n+1),profile,len(fresh),
                                       reason=('Grade com número da peça, descrição e quantidade reconhecida.'
                                               if profile=='cad_part_number' else
                                               'Colunas identificadas da lista CAD, incluindo células vazias.'
                                               if profile=='cad_named_grid' else
                                               'Cabeçalho CAD e linhas com quantidade reconhecidos.'))
            boms,unlinked_cad_pages=primary_cad_tables(boms)
            if unlinked_cad_pages:
                data['pending_decisions'].append({
                    'title':'Vincular listas CAD de detalhe',
                    'description':f"{path.name}: listas das páginas "+', '.join(map(str,unlinked_cad_pages))+
                        ' não foram somadas à lista principal; confirmar conjunto dono e multiplicadores para evitar duplicidade.',
                    'impact_level':'ALTO'})
            detail=details(text,cut_rows)
            if not detail.get('length') and not detail.get('width'):
                with pymupdf.open(path) as doc:
                    page_candidates=[details(body,page=doc[index])
                                     for index,(body,_) in enumerate(pages)]
                unique_dimensions={(item.get('length',0),item.get('width',0))
                                   for item in page_candidates
                                   if item.get('length',0)>0 and item.get('width',0)>0}
                if len(unique_dimensions)==1:
                    length,width=next(iter(unique_dimensions))
                    detail['length'],detail['width']=length,width
            part_only=is_part_only_bom(boms,path.stem)
            if part_only:
                detail=cad_row_details(boms[0][1][0],detail)
            if not detail.get('unit_weight') and any(row.get('cad_layout') for _,rows in boms for row in rows):
                labelled_weights={num(w) for w in re.findall(
                    r'PESO\s+TOTAL\s*\[\s*kg\s*\]\s*:\s*(\d+(?:[,.]\d+)?)',text,re.I)}
                if len(labelled_weights)==1:detail['unit_weight']=next(iter(labelled_weights))
            data['reading_report']['documents'].append({
                'path':path.relative_to(root).as_posix(),'pages':len(pages),
                'has_scanned_pages':any(page[1] for page in pages)})
            docs[path]={'text':text,'pages':[x[0] for x in pages],
                        'boms':boms,'details':detail,'part_only_bom':part_only,
                        'stem':norm(path.stem)}
            from wire_variants import parse_parameterized_wire_table
            for page_number, (page_body, _) in enumerate(pages, 1):
                for variant in parse_parameterized_wire_table(page_body):
                    data['wire_variants'].append({**variant,
                        'source_page':source_ref(root,path,page_number),
                        'description':path.stem})
        except Exception as exc:
            record_reading(data,source_ref(root,path),'unrecognized',stage='error',reason=str(exc))
            data['pending_decisions'].append({'title':'PDF não lido','description':f'{path.name}: {exc}','impact_level':'ALTO'})
    for path in scanned:
        data['pending_decisions'].append({'title':'Conferir OCR','description':f'{path}: página digitalizada ou sem texto. OCR local usado quando disponível.','impact_level':'ALTO'})
    if not docs: return data
    # SCORE packages have a continued 12-column BOM at the end of one PDF.
    # Check this exact table layout before the generic single-PDF fallback.
    from score_package import read_score_package
    for path in docs:
        with pymupdf.open(path) as pdf:
            if len(pdf)<2 or 'SCORE' not in norm(pdf[0].get_text()):
                continue
            bom,cuts=read_score_package(pdf)
            if len(bom)>=10:
                for bom_page in sorted({row['page'] for row in bom}):
                    record_reading(data,source_ref(root,path,bom_page),'score',
                                   sum(row['page']==bom_page for row in bom),stage='selected',
                                   reason='Lista SCORE nesta folha; continuação e cortes lidos no mesmo pacote.')
                return score_package_materials(data,root,path,pdf,bom,cuts)
    # Some older project packages contain only rasterized sheets. Read the
    # product list on sheet two with the built-in Windows OCR engine, keeping
    # every uncertain quantity visible for review.
    scanned_main=[(p,v) for p,v in docs.items() if len(v['pages'])>=3
                  and len(v['pages'][1].strip())<40]
    scanned_rise_tables=[]
    if scanned_main:
        path,info=max(scanned_main,key=lambda pv:(len(pv[1]['pages']),
                                                -len(pv[0].relative_to(root).parts)))
        ocr_cache={}
        try:
            with pymupdf.open(path) as doc:
                ocr_cache[(path,1)]=windows_ocr_lines(doc[1])
                ocr_rows=scanned_technical_bom(ocr_cache[(path,1)])
        except Exception as exc:
            ocr_rows=[]
            data['pending_decisions'].append({'title':'OCR não concluído',
                'description':f'{path.name}: {exc}','impact_level':'ALTO'})
        # The legacy fallback only inspected page 2 and returned early. A
        # different RISE family keeps the BOM on later sheets as vector text
        # outlines, so inspect scanned pages for its distinctive 11-column
        # header before accepting that fallback as the sole reading.
        for scanned_path,scanned_info in scanned_main:
            try:
                with pymupdf.open(scanned_path) as doc:
                    for page_index,page in enumerate(doc):
                        if len(scanned_info['pages'][page_index].strip())>=40:
                            continue
                        key=(scanned_path,page_index+1)
                        lines=ocr_cache.get(key)
                        if lines is None:
                            lines=windows_ocr_lines(page)
                            ocr_cache[key]=lines
                        if not scanned_rise_grid_candidate(lines):
                            continue
                        rows=scanned_rise_grid_bom(page)
                        if len(rows)<2:
                            continue
                        # OCR text is only used to recover BOM cells. Do not
                        # treat arbitrary visible numbers (e.g. wheel capacity
                        # 80 kg) as the product weight/title block.
                        body=''
                        record_reading(data,source_ref(root,scanned_path,page_index+1),
                                       'scanned_rise',len(rows),reason='Colunas recuperadas por OCR; conferir a imagem.')
                        scanned_rise_tables.append((scanned_path,page_index+1,
                                                    rows,body,None))
            except Exception as exc:
                data['pending_decisions'].append({'title':'OCR não concluído',
                    'description':f'{scanned_path.name}: {exc}','impact_level':'ALTO'})
        if len(ocr_rows)>=5 and not scanned_rise_tables:
            record_reading(data,source_ref(root,path,2),'scanned_technical',len(ocr_rows),
                           stage='selected',reason='Lista OCR da página 2; nenhuma grade RISE posterior reconhecida.')
            for row in ocr_rows:
                qty=row['quantity'] if row['quantity'] is not None else 1
                weight=row['unit_weight']; group=resolve_material_group(row['description'],row['material'])
                if norm(row['group']).startswith('CHAPA DE ACO'): group='Chapa'
                if norm(row['group']).startswith('TUBO QUADRADO'): group='Tubo Quadrado/Retangular'
                if norm(row['group']).startswith('ARAME'): group='Arame'
                issues=['PDF digitalizado: conferir descrição, quantidade e desenho com a imagem.']
                if row['quantity'] is None: issues.append('Quantidade não reconhecida; valor 1 provisório.')
                if weight<=0: issues.append('Peso não reconhecido ou zerado.')
                if norm(row['group']).startswith('ACESS') and weight>1:
                    issues.append(f'Peso OCR {weight:g} kg suspeito para acessório; valor zerado.')
                    weight=0.0
                data['materials'].append(empty_item(row['description'],qty,source_ref(root,path,2),
                    group,path.stem,source_group=row['group'],material=row['material'],drawing_id=row['drawing_id'] or row['description'],
                    unit_weight=weight,total_weight=round(qty*weight,4),
                    unit='?' if row['quantity'] is None else 'un',
                    confidence=0.45,pending_issue=' '.join(issues)))
            data['pending_decisions'].append({'title':'Lista extraída por OCR',
                'description':f'{path.name}, página 2: conferir toda a lista. Subconjuntos permanecem agregados até leitura dos detalhes.',
                'impact_level':'ALTO'})
            return finish_materials(data)
    # A scanned RISE reference can be a valid standalone BOM when the upload
    # contains only that PDF, but it must not replace a production package's
    # linked parent/child PDFs just because OCR recovered more rows. Keep the
    # reference evidence visible while letting the existing package-root
    # resolver build the quote from PROJETO.
    production_bom_files={path for path,info in docs.items()
                          if info['boms'] and any(
                              norm(part)=='PROJETO'
                              for part in path.relative_to(root).parts)}
    ignored_reference_tables=[entry for entry in scanned_rise_tables
                              if any(norm(part)=='REFERENCIA'
                                     for part in entry[0].relative_to(root).parts)]
    if production_bom_files and ignored_reference_tables:
        ignored_ids={id(entry[2]) for entry in ignored_reference_tables}
        scanned_rise_tables=[entry for entry in scanned_rise_tables
                             if id(entry[2]) not in ignored_ids]
        reference_pages=', '.join(str(page)
                                  for _,page,_,_,_ in ignored_reference_tables)
        data['pending_decisions'].append({
            'title':'BOM escaneada em referência não substitui o projeto atual',
            'description':(
                f'{len(ignored_reference_tables)} quadro(s) nas páginas {reference_pages} '
                'foram lidos em PDFs da pasta REFERENCIA. Como há BOMs de produção '
                'na pasta PROJETO, esses quadros de referência não entram no custo '
                'nem substituem a hierarquia atual; conferir se algum detalhe precisa '
                'complementar uma peça específica.'),
            'impact_level':'MÉDIO'})
    technical=list(scanned_rise_tables)
    technical_details={}
    for path,info in docs.items():
        with pymupdf.open(path) as pdf:
            for page,body in enumerate(info['pages'],1):
                sheet=pdf[page-1]
                part_codes={norm(match.group()) for match in re.finditer(
                    r'\b(?:[A-Z]{2,5}|P&G)\d{3,}P\d{2,3}\b',body,re.I)}
                if len(part_codes)==1:
                    measurements=technical_title_dimensions(sheet)
                    if measurements:
                        technical_details[(path,next(iter(part_codes)))]=(page,measurements)
                reading=read_technical_table(body,sheet)
                sections=reading.sections
                if reading.rows:
                    record_reading(data,source_ref(root,path,page),reading.profile,len(reading.rows),
                                   reason=reading.reason)
                if sections:
                    words=sheet.get_text('words')
                    for index,(rows,_,bottom) in enumerate(sections):
                        next_top=(sections[index+1][1] if index+1<len(sections)
                                  else sheet.rect.height)
                        own_codes={norm(match.group()) for word in words
                                   if bottom < (word[1]+word[3])/2 < next_top
                                   for match in re.finditer(
                                       r'(?:_[MP]\d{1,3}[-_]?REV\d+|'
                                       r'\b(?:[A-Z]{2,5}|P&G)\d{3,}M\d{2,3}\b)',
                                       word[4],re.I)}
                        child_codes={norm(match.group()) for row in rows
                                     for match in re.finditer(
                                         r'(?:_[MP]\d{1,3}[-_]?REV\d+|'
                                         r'\b(?:[A-Z]{2,5}|P&G)\d{3,}M\d{2,3}\b)',
                                         row['drawing_id'],re.I)}
                        own_codes -= child_codes
                        code_hint=next(iter(own_codes)) if len(own_codes)==1 else ''
                        # Empty hint on a multi-table page must not inherit
                        # another grid's code from the page text.
                        if len(sections)==1 and not code_hint:
                            code_hint=None
                        technical.append((path,page,rows,body,code_hint))
                else:
                    rows=reading.rows
                    if rows: technical.append((path,page,rows,body,None))
    if technical:
        # The product BOM is generally the largest table; smaller tables on
        # subsequent sheets detail individual components of that assembly.
        assembly_pages={}
        page_codes={}
        assembly_code_pattern=(r'(?:_M\d{1,3}[-_]?REV\d+|'
                               r'\b(?:[A-Z]{2,5}|P&G)\d{3,}M\d{2,3}\b|'
                               r'\b(?:PA|CJ|RI)\d{8}\b)')
        for path,page,rows,body,code_hint in technical:
            if code_hint is not None:
                page_code=code_hint or None
            else:
                heading=re.split(r'ITEM\s+(?:QTD|DESENHO)',body,maxsplit=1,flags=re.I)[0]
                code=re.search(assembly_code_pattern,heading,re.I)
                if code:
                    page_code=norm(code.group())
                else:
                    # On RISE drawings the page's own code is in the title block
                    # after the material table. Codes inside BOM rows name children;
                    # only a unique remaining code may identify this page.
                    child_codes={norm(match.group()) for row in rows
                                 for match in re.finditer(assembly_code_pattern,
                                                          row['drawing_id'],re.I)}
                    codes_on_page={norm(match.group()) for match in
                                   re.finditer(assembly_code_pattern,body,re.I)}-child_codes
                    page_code=next(iter(codes_on_page)) if len(codes_on_page)==1 else None
            page_codes[(path,page,id(rows))]=page_code
            if page_code: assembly_pages.setdefault(page_code,(path,page,rows,body))
        main=select_technical_root(technical,page_codes,assembly_code_pattern)
        # RISE keeps long material lists on consecutive sheets, continuing
        # item numbering (e.g. 1..68 on page 8 and 69..82 on page 9).
        # Join only a gapless continuation for the selected root; detail BOMs
        # that restart at item 1 remain separate assemblies.
        main_path, main_page, main_rows, main_body, main_code = main
        main_source=source_ref(root,main_path,main_page)
        main_profile=next((event['profile'] for event in reversed(data['reading_report']['events'])
                           if event['source_page']==main_source),'technical_text')
        record_reading(data,main_source,main_profile,len(main_rows),stage='selected',
                       reason='Raiz técnica selecionada por pasta de produção, referências pai/filho e ordem das folhas.')
        next_item = max((row['item_num'] for row in main_rows), default=0) + 1
        continuation_ids = set()
        for path, page, rows, body, code_hint in sorted(technical, key=lambda entry: entry[1]):
            if path != main_path or page <= main_page or rows is main_rows:
                continue
            numbers = [row['item_num'] for row in rows]
            if numbers and numbers == list(range(next_item, next_item + len(rows))):
                for row in rows:
                    row['_source_page'] = page
                main_rows.extend(rows)
                continuation_ids.add(id(rows))
                next_item += len(rows)
        if continuation_ids:
            technical = [entry for entry in technical if id(entry[2]) not in continuation_ids]
            main = (main_path, main_page, main_rows, main_body, main_code)
        # A second grid on the same sheet may lack its own printed assembly
        # code (RISE013 three-hook drawing). Associate it only when a distinctive
        # component name appears in exactly one still-unlinked root assembly.
        generic_tokens={'CONJUNTO','MONTADO','SOLDADO','ESTRUTURA','LATERAL',
                        'COMUNICACAO','SUPERIOR','INFERIOR','PRINCIPAL'}
        for entry in technical:
            path,page,rows,body,_=entry
            key=(path,page,id(rows))
            if path!=main[0] or rows is main[2] or page_codes.get(key):
                continue
            section_tokens=set(norm(' '.join(row['description'] for row in rows)).split())
            candidates=[]
            for parent_row in main[2]:
                if not technical_subassembly_group(parent_row['group']):
                    continue
                code=re.search(assembly_code_pattern,parent_row['drawing_id'],re.I)
                if not code or norm(code.group()) in assembly_pages:
                    continue
                evidence={word for word in norm(parent_row['description']).split()
                          if len(word)>=7 and not any(c.isdigit() for c in word)
                          and word not in generic_tokens and word in section_tokens}
                if evidence:
                    candidates.append((norm(code.group()),parent_row,evidence))
            if len(candidates)==1:
                code,parent_row,evidence=candidates[0]
                assembly_pages[code]=(path,page,rows,body)
                page_codes[key]=code
                data['pending_decisions'].append({
                    'title':'Vínculo de submontagem pelo nome',
                    'description':f'{parent_row["description"]}: lista da página {page} vinculada pela palavra {sorted(evidence)[0]}; conferir código do conjunto no desenho.',
                    'impact_level':'MÉDIO'})
        root_row_ids={id(row) for row in main[2]}
        linked_row_ids={id(row) for _,_,rows,_ in assembly_pages.values()
                        for row in rows}
        unlinked_scanned=[entry for entry in scanned_rise_tables
                          if not any(id(row) in root_row_ids|linked_row_ids
                                     for row in entry[2])]
        if unlinked_scanned:
            pages=', '.join(str(page) for _,page,_,_,_ in unlinked_scanned)
            data['pending_decisions'].append({
                'title':'Lista escaneada sem vínculo confirmado',
                'description':(
                    f'{len(unlinked_scanned)} quadro(s) detectado(s) nas páginas {pages} '
                    'não corresponde(m) a uma submontagem identificada na BOM principal. '
                    'Mantido(s) fora do custo para evitar duplicar peças; conferir a relação no desenho.'),
                'impact_level':'ALTO'})
        visiting=set()
        unpaired_reported=set()
        def drawing_child(row):
            code=re.search(assembly_code_pattern,row['drawing_id'],re.I)
            return assembly_pages.get(norm(code.group())) if code else None

        def mirror_pairs(rows):
            by_base=defaultdict(dict)
            for row in rows:
                if not technical_subassembly_group(row['group']): continue
                side,base=side_and_base(row['description'])
                if side and base: by_base[base][side]=row
            mirrors={}
            for base,sides in by_base.items():
                if len(sides)==1:
                    lone=next(iter(sides.values()))
                    source=drawing_child(lone)
                    if source and mirror_instruction(source[3]) and base not in unpaired_reported:
                        unpaired_reported.add(base)
                        data['pending_decisions'].append({
                            'title':'Contraparte espelhada sem item na lista',
                            'description':f'{lone["description"]}: o desenho pede montagem espelhada, mas a lista não identifica a quantidade nem o código do lado oposto.',
                            'impact_level':'ALTO'})
                    continue
                for target_side,source_side in (('direita','esquerda'),('esquerda','direita')):
                    target=sides.get(target_side); source_row=sides.get(source_side)
                    if not target or not source_row or drawing_child(target): continue
                    source=drawing_child(source_row)
                    if not source or not mirror_instruction(source[3]): continue
                    if any(side_and_base(component['description'])[0] for component in source[2]):
                        continue  # Componentes já têm lado próprio; requer desenho específico.
                    mirrors[id(target)]=(source,source_row)
            return mirrors

        def walk_table(path,page,rows,mult,parent,mirror_from=None):
            table_key=(path,page,id(rows))
            if table_key in visiting: return
            visiting.add(table_key)
            mirrors=mirror_pairs(rows)
            for row in rows:
                row_page = row.get('_source_page', page)
                qty=mult*row['quantity']; desc=row['description']
                child=drawing_child(row)
                if child and child[:2]==(path,page) and child[2] is rows: child=None
                mirror=mirrors.get(id(row)) if not child else None
                detail=child or (mirror[0] if mirror else None)
                if technical_subassembly_group(row['group']) and detail:
                    note=(f'Montagem espelhada de {mirror[1]["description"]}; '
                          f'desenho {mirror[1]["drawing_id"]}, página {detail[1]}.') if mirror else ''
                    if mirror_from and not note:
                        note=f'Composição vinda do desenho espelhado de {mirror_from}.'
                    note=' '.join(x for x in (row.get('observation') or '',note) if x)
                    assembly=empty_item(desc,qty,source_ref(root,path,row_page),'Subconjunto',parent,
                        source_group='Sub Conjunto',item_type='subconjunto',
                        drawing_id=row['drawing_id'],raw_code=row.get('raw_code',''),
                        unit_weight=row['unit_weight'],
                        total_weight=round(qty*row['unit_weight'],4),
                        is_inferred=1 if mirror or mirror_from else 0,
                        confidence=0.9,observation=note)
                    assembly['pending_issue']=''  # Os componentes detalhados vêm logo abaixo.
                    if row.get('_ocr_issue'):
                        assembly['pending_issue']=row['_ocr_issue']
                    data['materials'].append(assembly)
                    origin=mirror[1]['description'] if mirror else mirror_from
                    walk_table(detail[0],detail[1],detail[2],qty,parent+' / '+desc,origin)
                    continue
                group=resolve_material_group(desc,row['material'])
                if norm(row['group'])=='CHAPA DE ACO': group='Chapa'
                if norm(row['group'])=='TUBO QUADRADO': group='Tubo Quadrado/Retangular'
                if norm(row['group'])=='ARAME': group='Arame'
                raw_metal = (norm(row['group']) == 'BARRA CHATA' or
                             (norm(row['group']) in ('ACESSORIO', 'ACESSORIOS') and
                              norm(row['material']).startswith('CHAPA DE ACO') and
                              technical_drawing_code(row['drawing_id'])))
                issues=[]
                thickness_sources=[]
                description_gauge=re.search(
                    r'\b(?:E|ESP(?:ESSURA)?\.?)\s*[:=]?\s*'
                    r'(\d+(?:[,.]\d+)?)\s*MM\b',desc,re.I)
                material_gauge=material_cell_spec(row['material']).get('thickness',0)
                table_gauge=float(row.get('thickness') or 0)
                if description_gauge:
                    thickness_sources.append(('descrição',num(description_gauge.group(1))))
                if material_gauge:
                    thickness_sources.append(('material',float(material_gauge)))
                if table_gauge:
                    thickness_sources.append(('coluna espessura',table_gauge))
                if (group in ('Chapa','Tubo Quadrado/Retangular','Tubo Redondo') and
                        len(thickness_sources)>1 and
                        max(value for _,value in thickness_sources)-
                        min(value for _,value in thickness_sources)>0.01):
                    evidence='; '.join(f'{source} {value:g} mm'
                                       for source,value in thickness_sources)
                    issues.append('Espessuras divergentes no PDF ('+evidence+'); conferir antes de fechar.')
                if row.get('_ocr_issue'):
                    issues.append(row['_ocr_issue'])
                weight=row['unit_weight']
                if technical_subassembly_group(row['group']):
                    issues.append('Subconjunto sem lista detalhada correspondente; conferir a composição.')
                if weight<=0: issues.append('Peso unitário ausente ou zerado no PDF.')
                if norm(row['group'])=='ACESSORIO' and weight>1:
                    issues.append('Peso de acessório aparentemente elevado; conferir unidade no desenho.')
                    weight=0.0
                if row.get('printing_hint'):
                    issues.append(f'PDF indica impressão {row["printing_hint"]}; confirmar cores e área impressa para calcular o custo.')
                depth=row['depth']; length=row['length']
                observation=row.get('observation') or ''
                width=row['width']; thickness=row['thickness']
                if row.get('compact_cut') and group=='Chapa':
                    part_code=technical_drawing_code(row['drawing_id'])
                    detail=(technical_details.get((path,norm(part_code.group())))
                            if part_code else None)
                    if detail:
                        detail_page,measures=detail
                        proposed_width=width or measures.get('width',0)
                        proposed_thickness=thickness or measures.get('thickness',0)
                        stamp=measures.get('unit_weight',0)
                        gross=length*proposed_width*proposed_thickness*7.85e-6
                        if (length and proposed_width and proposed_thickness and stamp
                                and stamp<=gross<=stamp*1.10):
                            width=proposed_width; thickness=proposed_thickness
                            weight=max(weight,stamp)
                            observation=' '.join(x for x in (observation,
                                f'Largura {width:g} mm do desenho da peça, página {detail_page}; bruto {gross:.5f} kg compatível com carimbo {stamp:.5f} kg.') if x)
                        else:
                            issues.append('Chapa dobrada sem corte desenvolvido confiável; conferir desenho da peça.')
                if (row.get('compact_cut') and
                        ((group=='Arame' and row['diameter'] and length) or
                         (group=='Chapa' and width and thickness and weight))):
                    issues=[issue for issue in issues
                            if issue!='Peso unitário ausente ou zerado no PDF.']
                if (not length and depth and row['width'] and
                        norm(row['group']) in ('CHAPA DE ACO','PS','PSAI','PETG','PET','ACRILICO')):
                    length=depth
                    observation=' '.join(x for x in (observation,
                        'Segunda cota da chapa está na coluna Profundidade; usada como comprimento para calcular área.') if x)
                item=empty_item(desc,qty,source_ref(root,path,row_page),group,parent,source_group=row['group'],
                    item_type='materia_prima' if raw_metal else None,
                    material=row['material'],thickness=thickness,width=width,
                    depth=depth,length=length,radius_diam=row['diameter'],
                    drawing_id=row['drawing_id'],raw_code=row.get('raw_code',''),
                    unit=row.get('unit') or 'un',finish=row.get('finish') or '',
                    printing=row.get('printing') or '0x0',
                    unit_weight=weight,total_weight=round(qty*weight,4),
                    confidence=0.65 if issues else 0.9,pending_issue=' '.join(issues),
                    is_inferred=1 if mirror_from else 0,
                    observation=' '.join(x for x in (observation,
                        (f'Componente do lado espelhado de {mirror_from}; '
                         f'geometria extraída do desenho da peça original.') if mirror_from else '') if x))
                data['materials'].append(item)
            visiting.remove(table_key)
        repeated_across_pages=defaultdict(list)
        for row in main[2]:
            row_page=row.get('_source_page',main[1])
            if not row.get('drawing_id'): continue
            key=(norm(row['drawing_id']),round(row['quantity'],6),
                 norm(row['description']),norm(row['material']))
            repeated_across_pages[key].append((row_page,row['item_num'],row['drawing_id']))
        duplicate_evidence=[entries for entries in repeated_across_pages.values()
                            if len({entry[0] for entry in entries})>1]
        if duplicate_evidence:
            examples=[]
            for entries in duplicate_evidence:
                examples.append(' / '.join(f'item {item} p.{page} ({drawing})'
                                           for page,item,drawing in entries))
            data['pending_decisions'].append({
                'title':'Conferir linhas repetidas entre páginas',
                'description':('Mesmo desenho, descrição, material e quantidade aparecem '
                    'em itens numerados separados: '+'; '.join(examples[:12])+'. '
                    'As linhas foram mantidas separadas como o PDF lista; confirmar se '
                    'são ocorrências distintas ou repetição da BOM antes de fechar custo.'),
                'impact_level':'ALTO'})
        walk_table(main[0],main[1],main[2],1,main[0].stem)
        # RISE title blocks put the assembled product weight/area after the
        # second LISTA DE MATERIAIS label. BOM row weights are unit values;
        # only the selected root sheet can define the nominal product total.
        title_block = main[3].rsplit('LISTA DE MATERIAIS', 1)[-1]
        title_weights = re.findall(r'(?<![\w])([\d.,]+)\s*kg\b', title_block, re.I)
        title_areas = re.findall(r'(?<![\w])([\d.,]+)\s*m[²2]\b', title_block, re.I)
        if len(title_weights) == 1:
            data['nominal_weight_pdf'] = num(title_weights[0])
        if len(title_areas) == 1:
            data['nominal_area_pdf'] = num(title_areas[0])
        # HH GLOBAL and related RISE packs show component subtotals on their
        # summary cover. The product mass is in the title block beside its
        # drawing number, so use that paired evidence instead of the first kg
        # token in the whole PDF (which may be a component subtotal).
        if not data['nominal_weight_pdf'] or not data['nominal_area_pdf']:
            root_match = re.match(r'\s*([A-Z]{1,8}\d{5,})', main[0].stem, re.I)
            root_code = root_match.group(1) if root_match else ''
            if root_code:
                paired_weights = set()
                paired_areas = set()
                for body in docs[main[0]]['pages']:
                    paired = re.search(re.escape(root_code) + r'(.{0,700})', body, re.I | re.S)
                    if not paired:
                        continue
                    title_evidence = paired.group(1)
                    paired_weights.update(num(value) for value in
                        re.findall(r'(?<![\w])([\d.,]+)\s*kg\b', title_evidence, re.I))
                    paired_areas.update(num(value) for value in
                        re.findall(r'(?<![\w])([\d.,]+)\s*m[²2]\b', title_evidence, re.I))
                if not data['nominal_weight_pdf'] and len(paired_weights) == 1:
                    data['nominal_weight_pdf'] = next(iter(paired_weights))
                if not data['nominal_area_pdf'] and len(paired_areas) == 1:
                    data['nominal_area_pdf'] = next(iter(paired_areas))
                # Prefer an explicit, code-matched "Peso Total" on the RISE
                # project cover over the CAD title-block mass. Keep both
                # values visible as a conflict instead of silently choosing
                # the larger or first number in the PDF.
                if docs[main[0]]['pages']:
                    with pymupdf.open(main[0]) as source_pdf:
                        cover = rise_cover_specifications(source_pdf[0], root_code)
                else:
                    cover = {}
                if cover:
                    title_block_weight = data['nominal_weight_pdf']
                    data['nominal_weight_pdf'] = cover['total_weight']
                    breakdown = sum(cover.get(key,0.0) for key in
                                    ('steel_weight','polymer_weight','mdf_weight'))
                    if abs(breakdown-cover['total_weight'])>0.05:
                        data['pending_decisions'].append({
                            'title':'Conferir peso total da capa versus subtotais',
                            'description':(
                                f'A capa declara {cover["total_weight"]:.2f} kg; '
                                f'aço {cover.get("steel_weight",0):.2f} + polímeros '
                                f'{cover.get("polymer_weight",0):.2f} + MDF '
                                f'{cover.get("mdf_weight",0):.2f} = {breakdown:.2f} kg '
                                f'(diferença {abs(breakdown-cover["total_weight"]):.2f} kg). '
                                f'Tinta {cover.get("paint_weight",0):.2f} kg é campo separado.'),
                            'impact_level':'ALTO'})
                    if title_block_weight and abs(title_block_weight-cover['total_weight'])>0.05:
                        data['pending_decisions'].append({
                            'title':'Conferir massa da capa e do carimbo CAD',
                            'description':(
                                f'Peso Total da capa: {cover["total_weight"]:.4f} kg; '
                                f'peso do carimbo associado a {root_code}: '
                                f'{title_block_weight:.4f} kg. Manter a capa como referência '
                                'do peso total do produto até validação da diferença.'),
                            'impact_level':'ALTO'})
        data['pending_decisions'].append({'title':'Conferir tabela técnica',
            'description':'Lista extraída de desenhos técnicos com submontagens e páginas de detalhe. Conferir itens sem peso e subconjuntos não detalhados.',
            'impact_level':'ALTO'})
        return finish_materials(data)
    rise=[]
    # RISE exports carry a flat BOM on a dedicated page.
    for path,info in docs.items():
        if 'LISTA DE MATERIAIS' in norm(info['text']):
            with pymupdf.open(path) as doc:
                for n,page in enumerate(doc):
                    rows=rise_bom(page.get_text())
                    if rows:
                        rise.append((path,n+1,rows))
                        record_reading(data,source_ref(root,path,n+1),'rise_text',len(rows),
                                       reason='Lista RISE textual com códigos de peças e grupos reconhecidos.')
    if rise:
        path,page,rows=max(rise,key=lambda x:len(x[2]))
        record_reading(data,source_ref(root,path,page),'rise_text',len(rows),stage='selected',
                       reason='Maior lista RISE textual entre as páginas reconhecidas.')
        head=docs[path]['text']
        wt=re.search(r'Peso Total:\s*\n(?:[^\n]*\n){0,8}?([\d,.]+)\s*kg',head,re.I)
        values=re.findall(r'([\d,.]+)\s*kg',head,re.I)
        if values: data['nominal_weight_pdf']=num(values[0])
        for idx,row in enumerate(rows,1):
            group=resolve_material_group(row['description'],row['material'])
            if row['group']=='METAL' and group=='Outros Comprados': group='Chapa'
            if row['group']=='POLIMEROS' and group=='Outros Comprados': group='Polímero/PSAI'
            unit_weight=row['unit_weight']; qty=row['quantity']
            issues=[]
            if unit_weight <= 0: issues.append('Peso unitário ausente no PDF; conferir no desenho.')
            if qty != int(qty): issues.append('Quantidade fracionária sem unidade explícita; confirmar unidade.')
            entry=empty_item(row['description'],qty,source_ref(root,path,page),group,path.stem,source_group=row['group'],
                material=row['material'],thickness=row['thickness'],width=row['width'],depth=row['depth'],length=row['length'],
                drawing_id=row['drawing_id'],raw_code=row['raw_code'],unit_weight=unit_weight,
                total_weight=round(qty*unit_weight,4),unit_area=row['unit_area'],
                total_area=round(qty*row['unit_area'],4),confidence=0.75 if issues else 0.93,
                item_num=idx,unit='?' if qty != int(qty) else 'un',pending_issue=' '.join(issues))
            data['materials'].append(entry)
    else:
        # Choose the top assembly. A folder with several unrelated root PDFs is ambiguous.
        all_candidates=[(p,v) for p,v in docs.items() if v['boms']]
        candidates=[(p,v) for p,v in all_candidates if not v.get('part_only_bom')] or all_candidates
        if candidates:
            root_name=norm(root.name)
            selected_root=select_bom_package_root(candidates,root_name)
            candidates.sort(key=lambda pv:(
                                       0 if selected_root or any(not row.get('cad_layout')
                                           for _,rows in pv[1]['boms'] for row in rows) else 1,
                                       0 if pv[1]['stem'].startswith(root_name) else 1,
                                       len(pv[0].relative_to(root).parts),
                                       -sum(len(b) for _,b in pv[1]['boms'])))
            main=selected_root or candidates[0][0]
            main_profile=('cad_part_number' if any(row.get('cad_layout')=='part_number_grid'
                          for _,rows in docs[main]['boms'] for row in rows) else
                          'cad_named_grid' if any(row.get('cad_layout')
                          for _,rows in docs[main]['boms'] for row in rows) else 'cad')
            record_reading(data,source_ref(root,main,docs[main]['boms'][0][0]),main_profile,
                           sum(len(rows) for _,rows in docs[main]['boms']),stage='selected',
                           reason=('Raiz identificada pelas referências entre conjuntos ou nome da pasta.'
                                   if selected_root else 'Seleção por nome, profundidade de pasta e tamanho da lista; conferir variantes.'))
            top_level=[p for p,v in candidates if len(p.relative_to(root).parts)==len(main.relative_to(root).parts)]
            if selected_root is None and len(top_level)>1:
                data['pending_decisions'].append({'title':'Escolher variante do produto',
                'description':'Há vários conjuntos principais. Importe a subpasta da variante desejada para evitar mistura de orçamentos.','impact_level':'ALTO'})
            data['nominal_weight_pdf']=docs[main]['details']['unit_weight']
            data['nominal_area_pdf']=docs[main]['details']['unit_area']
            byname=defaultdict(list)
            for p,v in docs.items(): byname[v['stem']].append(p)
            visiting=set()
            aliases_used=set()
            def match_child(desc, part_number=''):
                key=norm(desc)
                exact=byname.get(key,[])
                if len(exact)==1: return exact[0]
                matches=[p for p,v in docs.items() if v['stem']==key or v['stem'].startswith(key+' ')]
                if len(matches)==1: return matches[0]
                if part_number:
                    printed=norm(part_number)
                    numbered=[p for p,v in docs.items() if v['stem']==printed
                              or v['stem'].startswith(printed+' ')
                              or (re.fullmatch(r'[A-Z0-9]+',printed)
                                  and v['stem'].endswith(' '+printed))]
                    if len(numbered)==1:return numbered[0]
                shared=shared_side_drawing(desc,docs)
                if shared: return shared
                variant=re.search(r'\s\d+(?:[,.]\d+)?$',key)
                if variant:
                    base=key[:variant.start()].strip()
                    candidates=byname.get(base,[])
                    valid=[p for p in candidates if parameterized_details(docs[p]['text'],desc)]
                    if len(valid)==1: return valid[0]
                # Some archived drawings kept an earlier customer's name in
                # the BOM while the PDF files were renamed. Match only the
                # complete component prefix, and only when it is unique.
                prefix=key.split(' DISPLAY ',1)[0]
                if prefix!=key and prefix:
                    aliases=[p for p,v in docs.items()
                             if v['stem'].split(' DISPLAY ',1)[0]==prefix and ' DISPLAY ' in v['stem']]
                    if len(aliases)==1:
                        aliases_used.add((desc,aliases[0].name))
                        return aliases[0]
                return None
            def walk(path,mult,parent):
                if path in visiting:
                    data['pending_decisions'].append({'title':'Ciclo na estrutura','description':path.name,'impact_level':'ALTO'})
                    return
                visiting.add(path)
                info=docs[path]
                rows=[(page,row) for page,bom in info['boms'] for row in bom]
                for page,row in rows:
                    qty=mult*row['quantity']; desc=row['description']; child=match_child(desc,row.get('part_number',''))
                    if child and child!=path and docs[child]['boms'] and not docs[child].get('part_only_bom'):
                        walk(child,qty,parent+' / '+desc)
                        continue
                    detail=(parameterized_details(docs[child]['text'],desc) or docs[child]['details']) if child else {}
                    detail=cad_row_details(row,detail)
                    source=source_ref(root,child or path,1 if child else page)
                    if child and detail.get('cut_table_rows'):
                        data['materials'].extend(cut_table_materials(
                            desc,qty,source,parent,child.stem,detail,row['raw_code']))
                        continue
                    mat=detail.get('material','') or row.get('material',''); group=resolve_material_group(desc,mat)
                    weight=detail.get('unit_weight',0.0); area=detail.get('unit_area',0.0)
                    issue=('Desenho da peça não localizado; conferir dimensões e peso.' if not child
                           else ('Comprimento desenvolvido do tubo não identificado; conferir desenho.'
                                 if group in ('Tubo Quadrado/Retangular','Tubo Redondo')
                                 and not detail.get('length') else ''))
                    if row.get('assembly_hint'):
                        group='Subconjunto'
                        issue='Subconjunto sem lista detalhada; confirmar a composição no desenho.'
                    if row.get('row_weight_raw') and not row.get('weight_unit_explicit'):
                        issue=' '.join(x for x in (issue,'Peso da lista sem unidade explícita; conferir kg ou g.') if x)
                    item=empty_item(desc,qty,source,group,parent,
                        material=mat,thickness=detail.get('thickness',0.0),radius_diam=detail.get('diameter',0.0),
                        width=detail.get('width',0.0),depth=detail.get('depth',0.0),length=detail.get('length',0.0),
                        drawing_id=(child.stem if child else desc),raw_code=row['raw_code'],
                        printing=detail.get('printing','0x0'),unit_weight=weight,total_weight=round(weight*qty,4),
                        unit_area=area,total_area=round(area*qty,4),confidence=0.9 if child else 0.6,
                        pending_issue=issue,
                        observation=('Quadro de corte: '+ '; '.join(
                            f"item {r['item_num']}: {r['quantity']} x {r['length']:g} mm ({r['material']})"
                            for r in detail.get('cut_table_rows',[]))
                            if detail.get('cut_table_rows') else
                            f"Lista CAD: item {row['item_num']}"+
                            (f"; peso impresso {row['row_weight_raw']} (unidade a conferir)."
                             if row.get('row_weight_raw') and not row.get('weight_unit_explicit') else '.')
                            if row.get('cad_layout') else ''))
                    data['materials'].append(item)
                visiting.remove(path)
            walk(main,1,main.stem)
            if aliases_used:
                data['pending_decisions'].append({'title':'Nomes divergentes entre lista e desenhos',
                    'description':'Algumas peças foram vinculadas pelo nome do componente, pois o cliente/produto no PDF difere do nome dos arquivos. Conferir estes vínculos antes de finalizar.',
                    'impact_level':'ALTO'})
    if not data['materials']:
        outpromo=[]; outpromo_details=[]
        for path in docs:
            with pymupdf.open(path) as doc:
                for n,page in enumerate(doc):
                    body=page.get_text()
                    rows,heading=outpromo_bom(body)
                    if rows:
                        outpromo.append((path,n+1,rows,heading))
                        record_reading(data,source_ref(root,path,n+1),'outpromo',len(rows),
                                       reason='Cabeçalho Item/Descrição/Qtd/Material da lista de sete colunas.')
                    for key,detail in outpromo_detail_dimensions(body).items():
                        outpromo_details.append((path,n+1,key,detail))
        if outpromo:
            root_pages=[entry for entry in outpromo if entry[3]=='']
            main=max(root_pages or outpromo,key=lambda x:len(x[2]))
            record_reading(data,source_ref(root,main[0],main[1]),'outpromo',len(main[2]),stage='selected',
                           reason='Lista principal sem cabeçalho de subconjunto, ou maior lista disponível.')
            detail_lookup={key:(page,detail) for path,page,key,detail in outpromo_details
                           if path==main[0]}
            drawn_views=can_base_drawn_dimensions(docs[main[0]]['pages'])
            def heading_key(value):
                words=norm(value).split()
                ignored={'SUBCONJUNTO','CONJUNTO','DA','DO','DE','DIREITA','DIREITO',
                         'ESQUERDA','ESQUERDO','DIR','ESQ','LD','LE'}
                return ' '.join(word for word in words if word not in ignored)
            lookup={heading_key(h):(p,n,rows) for p,n,rows,h in outpromo if h}
            def walk_outpromo(path,page,rows,mult,parent,seen):
                if (path,page) in seen: return
                seen=seen | {(path,page)}
                for row in rows:
                    qty=mult*row['quantity']; desc=row['description']; group=resolve_material_group(desc,row['material'])
                    child=lookup.get(heading_key(desc)) if 'CONJUNTO' in norm(desc) else None
                    if child and child[1]!=page:
                        walk_outpromo(child[0],child[1],child[2],qty,parent+' / '+desc,seen)
                        continue
                    spec=row['spec']
                    parsed=material_cell_spec(row['material'],row.get('dimension_cell',''))
                    pr=re.search(r'\b([04]x[014])\b',spec,re.I)
                    dims=re.search(r'(\d+(?:[,.]\d+)?)\s*[xX]\s*(\d+(?:[,.]\d+)?)',desc)
                    detail=detail_lookup.get(outpromo_detail_key(desc))
                    view=drawn_views.get(row['item_num'])
                    if view and not desc.upper().startswith(view['description_prefix']):
                        view=None
                    issue='Conferir cotas/peso no desenho; extração parcial.'
                    if 'CONJUNTO' in norm(desc) and norm(row['material']) in ('','--','VER DET'):
                        issue='Subconjunto sem lista detalhada correspondente; conferir composição.'
                    elif detail:
                        issue='Cotas da peça encontradas no detalhe; conferir recortes e peso calculado.'
                    length=detail[1]['length'] if detail else (num(dims.group(1)) if dims else 0)
                    width=detail[1]['width'] if detail else (num(dims.group(2)) if dims else parsed['width'])
                    observation=parsed['observation']
                    if detail:
                        observation=observation.split(';',1)[0].rstrip('.')+'.' if observation else ''
                        observation=' '.join(x for x in (observation,
                            f"Cotas da peça {length:g}×{width:g} mm no detalhe da página {detail[0]} "
                            f"({detail[1]['label']}).") if x)
                    if view:
                        if view['kind'] in ('plate','straight_tube'):
                            length=view['length']
                            if view['kind']=='plate': width=view['width']
                            observation=' '.join(x for x in (observation,
                                f"Cotas de corte {length:g}"
                                f"{'×'+format(width,'g') if view['kind']=='plate' else ''} mm "
                                f"na página {view['page']} do desenho.") if x)
                            issue='Peso bruto calculado pelas cotas do desenho; conferir recortes e soldas.'
                        else:
                            observation=' '.join(x for x in (observation,
                                f"Cotas gerais do desenho: {view['length']:g}"
                                f"{'×'+format(view['width'],'g') if view['width'] else ''} mm "
                                f"(página {view['page']}).") if x)
                            issue=('Peça dobrada: cota externa encontrada; comprimento desenvolvido '
                                   'ainda não indicado.' if view['kind']=='bend' else
                                   'Conjunto/perfil U: cotas externas encontradas; conferir '
                                   'comprimentos e quantidades dos segmentos.')
                    area=round(length*width/1_000_000,4) if group in ('Chapa','Polímero/PSAI') else 0.0
                    item=empty_item(desc,qty,source_ref(root,path,page),group,parent,
                        material=row['material'],thickness=parsed['thickness'],
                        radius_diam=parsed['diameter'],
                        length=length,width=width,
                        depth=parsed['depth'],
                        unit_area=area,total_area=round(area*qty,4),
                        printing=(detail[1]['printing'] if detail and detail[1]['printing']
                                  else pr.group(1).lower() if pr else '0x0'),
                        drawing_id=f'{path.stem}:p{page}:{row["item_num"]}',confidence=0.75,
                        finish=row.get('finish_cell',''),
                        observation=observation,pending_issue=issue)
                    data['materials'].append(item)
            walk_outpromo(main[0],main[1],main[2],1,main[0].stem,set())
    if not data['materials']:
        if not any(info['details'].get('cut_table_rows') for info in docs.values()):
            for path in docs:
                record_reading(data,source_ref(root,path),'unrecognized',stage='unresolved',
                               reason='Nenhuma lista de componentes reconhecida; composição pendente.')
        if len(docs)==1:
            path,info=next(iter(docs.items()))
            data['nominal_weight_pdf']=info['details'].get('unit_weight',0.0)
            data['nominal_area_pdf']=info['details'].get('unit_area',0.0)
            detail=info['details']; rows=detail.get('cut_table_rows',[])
            if rows:
                record_reading(data,source_ref(root,path),'cut_table',len(rows),stage='selected',
                               reason='PDF avulso com quadro de corte reconhecido.')
                data['materials'].extend(cut_table_materials(
                    path.stem,1,source_ref(root,path,1),path.stem,path.stem,detail))
            else:
                data['materials'].append(empty_item(path.stem,1,source_ref(root,path,1),
                    'Subconjunto',item_type='subconjunto',drawing_id=path.stem,
                    confidence=0.4,pending_issue='PDF único sem lista de componentes; conferir o corpo principal e cadastrar as peças.'))
                data['pending_decisions'].append({'title':'PDF único sem lista de materiais',
                    'description':'O desenho foi anexado como corpo principal; confira e adicione os componentes antes de finalizar.',
                    'impact_level':'ALTO'})
        else:
            path=next(iter(docs))
            data['materials'].append(empty_item(root.name,1,source_ref(root,path,1),
                'Subconjunto',item_type='subconjunto',drawing_id=root.name,
                confidence=0.3,pending_issue=f'{len(docs)} PDFs sem lista de componentes reconhecível; conferir o corpo principal e cadastrar as peças.'))
            data['pending_decisions'].append({'title':'Nenhuma peça confirmada',
                'description':'Os PDFs foram anexados, mas nenhuma lista de componentes foi identificada. Revise os desenhos e adicione as peças.',
                'impact_level':'ALTO'})
    return finish_materials(data)
