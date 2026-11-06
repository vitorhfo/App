"""Extraction rules for cad layouts; no project selection or persistence."""
from .common import norm
from .cad_part_number import cad_part_number_bom
from .cad_grids import cad_named_grid_bom
import re


def cad_bom(text, page=None):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    start = next((i for i in range(len(lines)-2) if norm(lines[i]) in ('N', 'NO', 'N ITEM')
                  and norm(lines[i+1]).startswith('DESCRI')
                  and (norm(lines[i+2]).startswith('QTD') or
                       (i+3<len(lines) and norm(lines[i+2]).startswith('CODIGO')
                        and norm(lines[i+3]).startswith('QTD')))), None)
    if start is None:
        return (cad_part_number_bom(page,text) or cad_named_grid_bom(page,text)) if page is not None else []
    has_code=norm(lines[start+2]).startswith('CODIGO')
    result=[]; i=start+(4 if has_code else 3)
    while i < len(lines):
        if 'PESO LIQ' in norm(lines[i]) or 'SISTEMA' in norm(lines[i]) or 'LOCAL DIGITAL' in norm(lines[i]):
            break
        m=re.fullmatch(r'(\d{1,3})(?:\s+(.+))?', lines[i])
        if not m:
            i+=1; continue
        item=int(m.group(1)); desc=m.group(2)
        if not desc:
            if i+1>=len(lines): break
            desc=lines[i+1]; i+=1
        if not re.search(r'[A-Za-zÀ-ÿ]', desc) or norm(desc) in ('ITEM','ESCALA'):
            i+=1; continue
        code=''
        if has_code and i+1 < len(lines) and lines[i+1]=='-':
            i+=1  # Empty code cell on parameterized parts.
        elif has_code and i+1 < len(lines) and not re.fullmatch(r'\d{1,3}', lines[i+1]):
            maybe=lines[i+1]
            if re.fullmatch(r'[A-Z0-9.\-]{4,25}', maybe) and not re.match(r'^\d+:', maybe):
                code=maybe; i+=1
        if i+1>=len(lines) or not re.fullmatch(r'\d{1,4}',lines[i+1]):
            i+=1; continue
        qty=int(lines[i+1]); i+=2
        if qty<=0 or qty>10000: continue
        result.append({'item_num':item,'description':desc,'raw_code':code,'quantity':qty})
    return result or (cad_named_grid_bom(page,text) if page is not None else [])

