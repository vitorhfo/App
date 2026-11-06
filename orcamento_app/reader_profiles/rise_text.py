"""Extraction rules for rise_text layouts; no project selection or persistence."""
from .common import norm, num
import re


def rise_bom(text):
    if 'LISTA DE MATERIAIS' not in norm(text): return []
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    start=next((i for i,x in enumerate(lines) if norm(x)=='OBSERVACAO'),None)
    if start is None: return []
    out=[]; i=start+1
    while i<len(lines)-5:
        if not re.fullmatch(r'\d{1,3}',lines[i]):
            i+=1; continue
        item=int(lines[i]); qty_line=lines[i+1]
        inline=re.fullmatch(r'(\d+(?:[.,]\d+)?)\s+(.+)',qty_line)
        if re.fullmatch(r'\d+(?:[.,]\d+)?',qty_line):
            qty=num(qty_line); desc_parts=[lines[i+2]]; j=i+3
        elif inline:
            qty=num(inline.group(1)); desc_parts=[inline.group(2)]; j=i+2
        else:
            i+=1; continue
        while j<len(lines) and j<i+8 and norm(lines[j]) not in ('METAL','POLIMEROS','COMPRADOS','MADEIRA','EMBALAGEM','ACESSORIOS'):
            desc_parts.append(lines[j]); j+=1
        if j>=len(lines): break
        group=lines[j]; desc=' '.join(desc_parts); j+=1
        if qty<=0 or qty>10000 or norm(group) not in ('METAL','POLIMEROS','COMPRADOS','MADEIRA','EMBALAGEM','ACESSORIOS'):
            i+=1; continue
        material_lines=[]
        while j<len(lines) and j<i+14 and not re.fullmatch(r'\d+(?:[.,]\d+)?',lines[j]) and not re.fullmatch(r'(?:PC|CJ|MP|EM|AC)\d+',lines[j],re.I):
            material_lines.append(lines[j]); j+=1
        code_index=next((k for k in range(j,min(j+8,len(lines))) if re.fullmatch(r'(?:PC|CJ|MP|EM|AC)\d+',lines[k],re.I)),None)
        if code_index is None:
            i+=1; continue
        measures=[num(x) for x in lines[j:code_index] if re.fullmatch(r'\d+(?:[.,]\d+)?',x)]
        width=depth=length=thickness=0.0
        if len(measures)>=4:
            thickness,width,depth,length=measures[:4]
        elif len(measures)>=3:
            thickness,width,length=measures[:3]
        elif len(measures)>=1:
            length=measures[-1]
        next_is_item=(code_index+2<len(lines) and re.fullmatch(r'\d{1,3}',lines[code_index+1])
            and (re.fullmatch(r'\d+(?:[.,]\d+)?',lines[code_index+2]) or
                 re.match(r'^\d+(?:[.,]\d+)?\s+[A-Za-z]',lines[code_index+2])))
        weight=0 if next_is_item else (num(lines[code_index+1]) if code_index+1<len(lines) else 0)
        area=0 if next_is_item else (num(lines[code_index+2]) if code_index+2<len(lines) else 0)
        if area>100: area=0
        out.append({'item_num':item,'quantity':qty,'description':desc,'group':group,
                    'material':' '.join(material_lines),'thickness':thickness,
                    'width':width,'depth':depth,'length':length,'drawing_id':lines[code_index],
                    'unit_weight':weight,'unit_area':area,
                    'raw_code':(re.search(r'\{(MP\d+)\}', ' '.join(material_lines)) or [None,''])[1]})
        i=code_index+1
    return out

