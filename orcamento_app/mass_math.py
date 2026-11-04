"""Conservative raw-material mass checks against the drawing title block."""

import math
import re

from calc_engine import (DENSIDADE_ACO_CARBONO, DENSIDADE_INOX,
                         DENSIDADE_ALUMINIO, DENSIDADE_PSAI,
                         DENSIDADE_ACRILICO, DENSIDADE_PETG,
                         DENSIDADE_POLIONDA)


def ceil_kg(value, places=6):
    scale=10**places
    return math.ceil(value*scale-1e-9)/scale if value>0 else 0.0


def density(material):
    text=(material or '').upper()
    if 'INOX' in text: return DENSIDADE_INOX
    if 'ALUM' in text: return DENSIDADE_ALUMINIO
    if 'PSAI' in text: return DENSIDADE_PSAI
    # Some SCORE PDFs decode the accented vowel as U+FFFD ("Acr�lico").
    # Match the material name with either spelling, never a dimension label.
    if re.search(r'ACR.LICO', text): return DENSIDADE_ACRILICO
    if 'PETG' in text: return DENSIDADE_PETG
    if 'POLIONDA' in text: return DENSIDADE_POLIONDA
    return DENSIDADE_ACO_CARBONO


def calculated_weight(item):
    """Return the gross blank weight in kg when its geometry is complete."""
    group=item.get('group_name') or ''
    mat=item.get('material') or ''
    material_text=mat.upper()
    # RISE/HEINZ stores expanded PVC and expanded-metal mesh with net CAD
    # weights. Their rectangular bounding boxes are not solid stock blanks;
    # using steel density here makes a 0.23 kg part appear to weigh 24 kg.
    if 'PVC VIRGEM EXPANDIDO' in material_text or 'TELA EXPANDIDA' in material_text:
        return 0.0
    # MDF density is not calibrated in the company data. The steel default
    # would fabricate a metal weight and overwrite the drawing's MDF weight.
    if 'MDF' in mat.upper():
        return 0.0
    length=float(item.get('length') or 0)
    width=float(item.get('width') or 0)
    depth=float(item.get('depth') or 0)
    thickness=float(item.get('thickness') or 0)
    diameter=float(item.get('radius_diam') or 0)
    rho=density(mat)
    if length<=0: return 0.0
    if group=='Arame' and diameter>0:
        return math.pi*(diameter/2)**2*length*rho/1_000_000
    if group=='Tubo Redondo' and diameter>0 and 0<thickness<diameter/2:
        section=math.pi*((diameter/2)**2-(diameter/2-thickness)**2)
        return section*length*rho/1_000_000
    if group=='Tubo Quadrado/Retangular' and width>0 and depth>0 and 0<thickness<min(width,depth)/2:
        section=width*depth-(width-2*thickness)*(depth-2*thickness)
        return section*length*rho/1_000_000
    if group in ('Chapa','Polímero/PSAI') and width>0 and thickness>0:
        return length*width*thickness*rho/1_000_000
    return 0.0


def strip_weight_note(observation):
    """Replace an old automatic comparison without erasing the user's notes."""
    text=str(observation or '')
    start=text.find('Conferência de peso:')
    if start>=0:
        prefix=text[:start]
        prefix=re.sub(r'Tubo (?:retangular |quadrado |redondo )?'
                      r'[Ø\d][\d.,xØ]* mm; comprimento [\d.,]+ mm\.\s*$',
                      '',prefix)
        end=text.find(' por peça.',start)
        if end>=0:
            end+=len(' por peça.')
            warning=' Cálculo acima da folha: conferir recortes, dobras e medidas.'
            if text.startswith(warning,end): end+=len(warning)
            warning=' Folha acima do peso bruto calculado: conferir densidade, espessura e cotas.'
            if text.startswith(warning,end): end+=len(warning)
            text=(prefix+' '+text[end:]).strip()
    text=text.replace('Peso ajustado ao mínimo calculado e ao peso registrado na folha.','').strip()
    return text.split('Medidas manuais diferentes do PDF:',1)[0].strip()


def reconcile_item_weight(item,pdf_weight=None):
    """Never budget less than either the drawing mass or gross geometry mass."""
    if item.get('item_type')=='subconjunto':
        return False
    theoretical=calculated_weight(item)
    if theoretical<=0: return False
    original=float(item.get('unit_weight') or 0)
    pdf=original if pdf_weight is None else float(pdf_weight or 0)
    chosen=ceil_kg(max(theoretical,pdf,original))
    item['unit_weight']=chosen
    item['total_weight']=ceil_kg(chosen*float(item.get('quantity') or 0))
    profile=''
    if item.get('group_name')=='Tubo Quadrado/Retangular':
        shape=('quadrado' if abs(float(item.get('width') or 0)-float(item.get('depth') or 0))<1e-6
               else 'retangular')
        profile=(f"Tubo {shape} {float(item.get('width') or 0):g}x"
                 f"{float(item.get('depth') or 0):g}x"
                 f"{float(item.get('thickness') or 0):g} mm; "
                 f"comprimento {float(item.get('length') or 0):g} mm. ")
    elif item.get('group_name')=='Tubo Redondo':
        profile=(f"Tubo redondo Ø{float(item.get('radius_diam') or 0):g}x"
                 f"{float(item.get('thickness') or 0):g} mm; "
                 f"comprimento {float(item.get('length') or 0):g} mm. ")
    reference=(f'folha {pdf*1000:.3f} g' if pdf>0 else 'folha sem peso reconhecido')
    note=(profile+f'Conferência de peso: cálculo bruto {theoretical*1000:.3f} g; '
          f'{reference}; adotado {chosen*1000:.3f} g por peça.')
    if theoretical>pdf*1.05 and pdf>0:
        note+=' Cálculo acima da folha: conferir recortes, dobras e medidas.'
    elif (item.get('group_name') in ('Chapa','Polímero/PSAI') and
          pdf>theoretical*1.10):
        note+=' Folha acima do peso bruto calculado: conferir densidade, espessura e cotas.'
    item['observation']=' '.join(x for x in (strip_weight_note(item.get('observation')),note) if x)
    return True
