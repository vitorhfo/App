"""Extraction rules for common layouts; no project selection or persistence."""
import re
import unicodedata

INCH_SIZE = '(\\d+(?:\\s*[-/]\\s*\\d+)?)\\s*(?:\\"|\'{1,2})'


def norm(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return re.sub(r'[^A-Z0-9]+', ' ', value.upper()).strip()



def num(value):
    try:
        return float(str(value).replace(' ', '').replace(',', '.'))
    except (TypeError, ValueError):
        return 0.0



def inch_mm(value):
    """Read fractional inch sizes, including CAD's 1-2'' spelling for 1/2''."""
    parts=re.split(r'\s*[-/]\s*',value)
    if len(parts)==2:
        denominator=float(parts[1])
        return round(25.4*float(parts[0])/denominator,6) if denominator else 0.0
    return round(25.4*num(value),6)



def table_measure(value):
    """Numeric CAD cell, optionally followed by the printed mm unit."""
    cleaned=str(value or '').strip().replace(' ', '')
    match=re.fullmatch(r'(\d+(?:[,.]\d+)?)(?:mm)?',cleaned,re.I)
    return num(match.group(1)) if match else num(cleaned)



def table_diameter(value):
    """Return diameter; an explicit radius marker is doubled."""
    cleaned=str(value or '').strip()
    match=re.fullmatch(r'(RAIO|R\.?|DI[ÂA]METRO|DIAM\.?|Ø)?\s*(\d+(?:[,.]\d+)?)\s*(?:mm)?',
                       cleaned,re.I)
    if not match: return 0.0,False
    measure=num(match.group(2))
    is_radius=bool(match.group(1) and norm(match.group(1)) in ('R','RAIO'))
    return (measure*2 if is_radius else measure),is_radius



def material_cell_spec(material, dimension_cell=''):
    """Read material/profile data without mistaking commercial sheet size for cut size.

    The seven-column OUTPROMO lists put the gauge before a hyphen and the
    supplier's full sheet after it. Part dimensions belong to the detail view.
    Other projects put gauge in the separate Dimensões column or in a tube
    profile, so the two cells are interpreted together.
    """
    material=str(material or '').strip()
    dimension_cell=str(dimension_cell or '').strip()
    result=dict(thickness=0.0,diameter=0.0,width=0.0,depth=0.0,
                stock_width=0.0,stock_length=0.0,observation='')
    flat=re.search(rf'\bFERRO\s+(?:CHATO|LAMINADO)\s+{INCH_SIZE}\s*[xX×]\s*{INCH_SIZE}',material,re.I)
    if flat:
        result.update(width=inch_mm(flat.group(1)),thickness=inch_mm(flat.group(2)))
        return result
    round_inch=(re.search(rf'{INCH_SIZE}\s*[xX×]\s*(\d+(?:[,.]\d+)?)\s*mm',material,re.I)
                if re.search(r'\bTUBO\b.*\bRED\b',material,re.I) else None)
    if round_inch:
        result.update(diameter=inch_mm(round_inch.group(1)),
                      thickness=num(round_inch.group(2)))
        return result
    # HH GLOBAL RISE stock syntax: E:gauge X L:width X L:depth X C:stock.
    # Extract the profile separately from the cut length in the BOM row.
    tube=re.search(rf'\b(?:TUBO|METALON)\b.*?\bE\s*:\s*(\d+(?:[,.]\d+)?)\s*mm\s*'
                   rf'[xX×]\s*L\s*:\s*(\d+(?:[,.]\d+)?)\s*mm\s*'
                   rf'[xX×]\s*L\s*:\s*(\d+(?:[,.]\d+)?)\s*mm\s*'
                   rf'[xX×]\s*C\s*:\s*(\d+(?:[,.]\d+)?)\s*mm',material,re.I)
    if tube:
        gauge,width,depth,stock_length=(num(value) for value in tube.groups())
        result.update(thickness=gauge,width=width,depth=depth,stock_length=stock_length)
        return result
    sheet_stock=re.search(r'\bE\s*:\s*(\d+(?:[,.]\d+)?)\s*mm\s*'
                          r'[xX×]\s*L\s*:\s*(\d+(?:[,.]\d+)?)\s*mm\s*'
                          r'[xX×]\s*C\s*:\s*(\d+(?:[,.]\d+)?)\s*mm',material,re.I)
    if sheet_stock:
        gauge,stock_width,stock_length=(num(value) for value in sheet_stock.groups())
        result.update(thickness=gauge,stock_width=stock_width,stock_length=stock_length)
    flat_bar=re.search(rf'\bBARRA\s+CHATA\b.*?\bE\s*:\s*{INCH_SIZE}\s*'
                       rf'[xX×]\s*L\s*:\s*{INCH_SIZE}',material,re.I)
    if flat_bar:
        result.update(thickness=inch_mm(flat_bar.group(1)),width=inch_mm(flat_bar.group(2)))
        return result
    profile_pattern=(r'(\d+(?:[,.]\d+)?)\s*[xX×]\s*'
                     r'(\d+(?:[,.]\d+)?)\s*[xX×]\s*'
                     r'(\d+(?:[,.]\d+)?)\s*(?:mm)?')
    profiles=list(re.finditer(profile_pattern,material,re.I))
    if re.search(r'\b(?:TUBO|METALON)\b',norm(material)) and profiles:
        if len(profiles)==1:
            a,b,gauge=(num(x) for x in profiles[0].groups())
            result.update(width=a,depth=b,thickness=gauge)
        else:
            result['observation']='Mais de um perfil de tubo na lista; conferir a composição no desenho.'
        return result
    dia=re.search(r'[Øø�]\s*(\d+(?:[,.]\d+)?)\s*(?:mm)?',material+' '+dimension_cell,re.I)
    if dia and 'ARAME' in norm(material):
        result['diameter']=num(dia.group(1))
    explicit=re.search(r'\bESP(?:ESSURA)?\.?\s*[:=]?\s*(\d+(?:[,.]\d+)?)\s*(?:mm)?',dimension_cell,re.I)
    if explicit:
        result['thickness']=num(explicit.group(1))
    is_sheet=bool(re.search(r'\b(?:CHAPA|PSAI|PS|PVC|PETG|PET|ACRILICO|ACRÍLICO|POLIONDA)\b',norm(material)))
    stock=re.search(r'[-–]\s*(\d{3,4}(?:[,.]\d+)?)\s*[xX×]\s*'
                    r'(\d{3,4}(?:[,.]\d+)?)\s*(?:mm)?\b',material,re.I) if is_sheet else None
    if stock:
        result['stock_length']=num(stock.group(1))
        result['stock_width']=num(stock.group(2))
        result['observation']=f'Chapa comercial {stock.group(1)}×{stock.group(2)} mm.'
    if is_sheet and not result['thickness']:
        before=material[:stock.start()] if stock else material
        gauge=re.search(r'(\d+(?:[,.]\d+)?)\s*(?:mm)?\s*$',before,re.I)
        if gauge and 0<num(gauge.group(1))<=20:
            result['thickness']=num(gauge.group(1))
    return result

