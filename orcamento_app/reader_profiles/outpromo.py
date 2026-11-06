"""Extraction rules for outpromo layouts; no project selection or persistence."""
from .common import norm, num
import re


def outpromo_bom(text):
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    start=next((i for i in range(len(lines)-6) if norm(lines[i])=='ITEM'
                and norm(lines[i+1]).startswith('DESCRIC') and norm(lines[i+2])=='QTD'
                and norm(lines[i+3])=='MATERIAL'),None)
    if start is None: return [],''
    heading=''
    for x in reversed(lines[max(0,start-14):start]):
        if 'CONJUNTO' in norm(x): heading=x; break
    end=next((i for i in range(start+7,len(lines)) if norm(lines[i])=='ASSINATURA'),len(lines))
    result=[]; i=start+7
    while i<end-2:
        if not re.fullmatch(r'\d{1,2}',lines[i]) or not re.fullmatch(r'\d{1,3}',lines[i+2]):
            i+=1; continue
        number=int(lines[i]); desc=lines[i+1]; qty=int(lines[i+2]); i+=3
        spec=[]
        while i<end and not (re.fullmatch(r'\d{1,2}',lines[i]) and i+2<end and
                              re.fullmatch(r'\d{1,3}',lines[i+2])):
            spec.append(lines[i]); i+=1
        if 0<qty<=1000:
            result.append({'item_num':number,'description':desc,'quantity':qty,
                           'material':spec[0] if spec else '',
                           'dimension_cell':spec[1] if len(spec)>1 else '',
                           'finish_cell':spec[2] if len(spec)>2 else '',
                           'spec':' '.join(spec),'raw_code':''})
    return result,heading



def outpromo_detail_dimensions(text):
    """Named flat PSAI pieces on a later OUTPROMO drawing page.

    The two standalone dimensions immediately before each piece label are the
    horizontal and vertical cut dimensions. Radius notes are deliberately
    skipped; unrelated views without a named PSAI label are not matched.
    """
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    result={}
    for i,label in enumerate(lines):
        key=norm(label)
        if not key.startswith('COMUNICACAO '): continue
        following=' '.join(lines[i+1:i+5])
        if 'PSAI' not in norm(following): continue
        previous=[]
        for candidate in reversed(lines[max(0,i-5):i]):
            if 'PECAS' in norm(candidate): break
            if re.fullmatch(r'\d+(?:[,.]\d+)?',candidate): previous.append(num(candidate))
        previous.reverse()
        if len(previous)!=2 or min(previous)<=0: continue
        printing=re.search(r'\b4[Xx][04]\b',following)
        result[key]={'length':previous[0],'width':previous[1],
                     'printing':printing.group().lower() if printing else '',
                     'label':label}
    return result



def outpromo_detail_key(description):
    """Match BOM role to an explicitly named piece in the detail view."""
    words=norm(description)
    if not words.startswith('PSAI '): return ''
    if 'TESTEIRA' in words: return 'COMUNICACAO TESTEIRA'
    if 'QUADRO LATERAL' in words: return 'COMUNICACAO LATERAL'
    if 'SAIA' in words and ('FRONTAL' in words or 'TRASEIRA' in words):
        return 'COMUNICACAO SAIA MAIOR'
    if 'SAIA LATERAL' in words: return 'COMUNICACAO SAIA MENOR'
    return ''



def can_base_drawn_dimensions(pages):
    """Verified item-to-view links for the twelve-sheet CNBS_5582 drawing.

    A view's overall outline is not automatically a tube cut length. Only
    explicitly straight single-piece tubes and flat plates receive geometry
    that can drive weight. Frames, U channels, bends and flat-iron supports
    retain their visible envelope with a pending developed-length decision.
    """
    if len(pages)!=12 or not any('CNBS_5582' in body for body in pages):
        return {}
    # BOM item: detail page, drawing dimensions, role, expected description.
    specs={
        1:(4,1350,250,'envelope','QUADRO SAIA FRONTAL'),
        2:(4,1350,250,'plate','CHAPA SAIA FRONTAL'),
        3:(4,1350,250,'envelope','CANALETA SAIA FRONTAL'),
        4:(5,1110,250,'envelope','QUADRO SAIA LATERAL'),
        5:(5,1110,250,'plate','CHAPA SAIA LATERAL'),
        6:(5,1110,250,'envelope','CANALETA SAIA LATERAL'),
        7:(8,1530,140,'bend','TUBO BATE CARRINHO FRONTAL'),
        8:(8,172,55,'bend','SUPORTE BATE CARRINHO'),
        9:(9,1050,0,'straight_tube','TUBO BATE CARRINHO LATERAL'),
        10:(10,800,0,'straight_tube','HASTE'),
        11:(11,1000,315,'bend','HASTE'),
        12:(7,650,225,'envelope','QUADRO DA TESTEIRA'),
        13:(7,650,225,'plate','CHAPA TESTEIRA'),
        14:(7,650,225,'envelope','CANALETA TESTEIRA'),
        15:(6,1000,435,'envelope','QUADRO COMUNICA'),
        16:(6,1000,435,'plate','CHAPA COMUNICA'),
        17:(6,1000,435,'envelope','CANALETA COMUNICA'),
        18:(6,47,22,'bend','TRAVA COMUNICA'),
    }
    def printed(body,value):
        return bool(re.search(rf'(?m)^\s*{value}(?:[,.]0)?\s*$',body))
    result={}
    for item_num,(page,length,width,kind,prefix) in specs.items():
        body=pages[page-1]
        if not printed(body,length) or (width and not printed(body,width)):
            continue
        result[item_num]={'page':page,'length':length,'width':width,
                          'kind':kind,'description_prefix':prefix}
    return result

