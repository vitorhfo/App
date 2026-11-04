"""Approved-price resolution. Missing prices stay NULL and block final issue."""
from pathlib import Path
from fractions import Fraction
import re
import unicodedata

from config import RAW_DIR


def norm(value):
    text=unicodedata.normalize('NFKD',str(value or ''))
    text=''.join(c for c in text if not unicodedata.combining(c)).upper().replace(',','.')
    return re.sub(r'[^A-Z0-9.]+',' ',text).strip()


def porta_linear_length_mm(item):
    """Length of a bought porta-preço/porta-etiqueta, from explicit measures."""
    if item.get('item_type')!='comprado':
        return 0.0
    description=norm(item.get('description'))
    if not re.search(r'\bPORTA (?:PRECO|ETIQUETA)\b',description):
        return 0.0
    length=float(item.get('length') or 0)
    if length>0:
        return length
    if 'PORTA ETIQUETA' in description:
        # Examples in the BOM: 550x55 and 630 X 40 (length first).
        measure=re.search(r'\b(\d+(?:\.\d+)?)\s*X\s*\d+(?:\.\d+)?\b',description)
        return float(measure.group(1)) if measure else 0.0
    # ALPA OCR records the pair after PET thickness as 64.7 70. The
    # structured version of that same part identifies 64.7 as length.
    material=norm(item.get('material'))
    measure=re.search(r'MM\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*$',material)
    return float(measure.group(1)) if measure else 0.0


def seed_catalog(cur):
    from openpyxl import load_workbook
    path=Path(RAW_DIR)/'RELAÇÃO ITENS COMPRADOS - FEVEREIRO.xlsx'
    if not path.exists(): raise FileNotFoundError(path)
    wb=load_workbook(path,read_only=True,data_only=True)
    for sheet in wb:
        if sheet.title not in ('Tubos','Diversos','Arames','Chapas','Barra_Chata'):
            continue
        unit='kg' if sheet.title in ('Tubos','Arames','Chapas','Barra_Chata') else 'un'
        for row in sheet.iter_rows(min_row=14, max_col=3, values_only=True):
            desc,value=row[1],row[2]
            if not isinstance(desc,str) or not isinstance(value,(int,float)) or value<=0:
                continue
            cur.execute("""INSERT OR IGNORE INTO catalog_prices
                (description,normalized,value,unit,source,effective_date,approved)
                VALUES (?,?,?,?,?,?,?)""",
                (desc,norm(desc),float(value),unit,f'{path.name} / {sheet.title}','2025-05-01',int(sheet.title=='Tubos')))
    wb.close()


def approved_rules(conn):
    return {r['rule_key']:float(r['value']) for r in conn.execute(
        'SELECT rule_key,value FROM price_rules WHERE approved=1 AND is_active=1')}


def _tube_dimensions(description):
    numbers=re.search(r'(\d+(?:[,.]\d+)?)\s*[Xx]\s*(\d+(?:[,.]\d+)?)\s*[Xx]\s*(\d+(?:[,.]\d+)?)',description)
    return tuple(float(n.replace(',','.')) for n in numbers.groups()) if numbers else None


def _round_diameter(description):
    match=re.search(r'(\d+(?:[.,]\d+)?(?:/\d+)?)\s*[\x27\u201d\"]',description)
    if match:
        size=match.group(1).replace(',','.')
        try:
            if '/' in size and '.' in size:
                whole,fraction=size.split('.',1)
                return (float(whole)+float(Fraction(fraction)))*25.4
            return float(Fraction(size))*25.4
        except (ValueError,ZeroDivisionError):
            pass
    match=re.search(r'(?:\u00d8|DIAM(?:ETRO)?)\s*(\d+(?:[,.]\d+)?)',description,re.I)
    return float(match.group(1).replace(',','.')) if match else None


def _tube_catalog_match(item,conn):
    rows=conn.execute("""SELECT * FROM catalog_prices WHERE approved=1 AND unit='kg'
        AND source LIKE '% / Tubos'""").fetchall()
    exact=[r for r in rows if r['normalized']==norm(item['description'])]
    if len(exact)==1:
        return exact[0]
    group=item['group_name']
    material=norm((item.get('material') or '')+' '+(item.get('description') or ''))
    is_inox='INOX' in material
    matches=[]
    requested=float(item.get('thickness') or 0)
    if requested<=0:
        return None
    for row in rows:
        desc=row['description']
        if ('INOX' in norm(desc))!=is_inox:
            continue
        if group=='Tubo Quadrado/Retangular':
            dims=_tube_dimensions(desc)
            if dims and item.get('width') and item.get('depth'):
                if (sorted(dims[:2])==sorted((float(item['width']),float(item['depth'])))
                        and dims[2]>=requested-1e-6):
                    matches.append((dims[2],row))
        elif group=='Tubo Redondo':
            diameter=_round_diameter(desc)
            thickness=re.search(r'[Xx]\s*(\d+(?:[,.]\d+)?)\s*MM',desc,re.I)
            if (diameter is not None and thickness and item.get('radius_diam')
                    and abs(diameter-item['radius_diam'])<0.6
                    and float(thickness.group(1).replace(',','.'))>=requested-1e-6):
                matches.append((float(thickness.group(1).replace(',','.')),row))
    if not matches:
        return None
    closest=min(gauge for gauge,_ in matches)
    nearest=[row for gauge,row in matches if abs(gauge-closest)<1e-6]
    # A duplicated/ambiguous catalog size requires review, never an arbitrary rate.
    return nearest[0] if len(nearest)==1 else None


def metal_price_basis(item,rules,conn):
    """Traceable kg rate for raw metal. Ambiguous profiles remain unpriced."""
    # A stamped mass can belong to a bent/welded piece, while the dimensions
    # in the BOM are only its envelope. It cannot price an unknown stock cut.
    issue=norm(item.get('pending_issue') or '')
    if any(fragment in issue for fragment in (
            'SEM COTAS DESENVOLVIDAS', 'SEM CORTES SEPARADOS',
            'SEM QUADRO DE CORTES', 'CORTES DE TUBO NAO INDICADOS',
            'COMPRIMENTO DESENVOLVIDO DO ARAME NAO INDICADO')):
        return None
    weight=item.get('unit_weight') or 0
    if item.get('item_type')!='materia_prima' or weight<=0:
        return None
    group=item['group_name']
    material=norm((item.get('material') or '')+' '+(item.get('description') or ''))
    if 'FERRO CHATO' in material:
        return None  # Distinct purchased stock; sheet tariff is not approved.
    if (group=='Chapa' and ('ACO' in material or 'SAE' in material)
            and 'INOX' not in material and 'ALUMINIO' not in material
            and 'mp_chapa_aco' in rules):
        return {'rate':rules['mp_chapa_aco'],'ipi_pct':0,'factor':1,
                'weight':weight,'source':f'Chapa: modelo vazio, R$ {rules["mp_chapa_aco"]:.2f}/kg'}
    if group=='Arame' and 'INOX' not in material and {'mp_arame','mp_arame_fator_liquido'}<=rules.keys():
        return {'rate':rules['mp_arame'],'ipi_pct':0,'factor':rules['mp_arame_fator_liquido']/100,
                'weight':weight,'source':f'Arame: modelo vazio, R$ {rules["mp_arame"]:.2f}/kg bruto x {rules["mp_arame_fator_liquido"]/100:.4f}'}
    if group in ('Tubo Quadrado/Retangular','Tubo Redondo') and {'mp_tubo_acrescimo_ipi','mp_tubo_fator_liquido'}<=rules.keys():
        match=_tube_catalog_match(item,conn)
        if match:
            dims=_tube_dimensions(match['description'])
            round_gauge=re.search(r'[Xx]\s*(\d+(?:[,.]\d+)?)\s*MM',
                                  match['description'],re.I)
            used_thickness=(dims[2] if dims else
                            float(round_gauge.group(1).replace(',','.')) if round_gauge
                            else float(item['thickness']))
            note=(f', esp {float(item["thickness"]):g}→{used_thickness:g} mm'
                  if used_thickness>float(item['thickness'])+1e-6 else '')
            return {'rate':match['value'],'ipi_pct':rules['mp_tubo_acrescimo_ipi'],
                    'factor':rules['mp_tubo_fator_liquido']/100,'weight':weight,
                    'source':f'Tubo: catálogo #{match["id"]} ({match["description"]}){note}, +{rules["mp_tubo_acrescimo_ipi"]:.2f}% IPI x {rules["mp_tubo_fator_liquido"]/100:.4f}',
                    'thickness_used':used_thickness}
    return None


def psai_price_basis(item,rules,conn):
    """Find an exact CONTROLV PSAI color/thickness and its printing rate."""
    if item.get('item_type')!='comprado' or item.get('group_name')!='Polímero/PSAI':
        return None
    d=norm((item.get('material') or '')+' '+(item.get('description') or ''))
    area=item.get('unit_area') or 0
    if area<=0 and (item.get('width') or 0)>0 and (item.get('length') or 0)>0:
        area=item['width']*item['length']/1_000_000
    if 'PSAI' not in d or area<=0:
        return None
    colors=[name for name in ('BRANCO','CRISTAL','LEITOSO') if name in d]
    colored_tokens=('COLORIDO','VERMELHO','AZUL','VERDE','AMARELO','PRETO',
                    'LARANJA','ROSA','ROXO','CINZA','MARROM')
    colored=not colors and any(token in d for token in colored_tokens)
    if len(colors)!=1 and not colored:
        return None
    color=colors[0] if colors else 'BRANCO'
    known={'pl_psai_branco_10':1.0,'pl_psai_branco_15':1.5,
           'pl_psai_branco_20':2.0,'pl_psai_cristal_20':2.0,
           'pl_psai_cristal_30':3.0,'pl_psai_leitoso_20':2.0,
           'pl_psai_leitoso_100':10.0}
    thickness=float(item.get('thickness') or 0)
    if thickness<=0:
        return None
    candidates=sorted((size,key) for key,size in known.items()
                      if key.startswith(f'pl_psai_{color.lower()}_')
                      and key in rules and size>=thickness-0.0001)
    if not candidates:
        return None
    used_thickness,key=candidates[0]
    printing=(item.get('printing') or '0x0').lower()
    faces={'0x0':0,'4x0':1,'4x4':2}.get(printing)
    if faces is None or (faces and 'imp_digital_face' not in rules):
        return None
    if colored and 'imp_psai_adicional_4x1' not in rules:
        return None
    source_row=conn.execute('SELECT source FROM price_rules WHERE rule_key=?',(key,)).fetchone()
    source=source_row['source'] if source_row else 'CONTROLV'
    if colored:
        source+=' + CONTROLV!K4'
    return {'rate':rules[key],'print_rate':rules['imp_digital_face']*faces if faces else 0,
            'area':area,'printing':printing,'source':source,'key':key,
            'color_pct':rules['imp_psai_adicional_4x1'] if colored else 0,
            'thickness_requested':thickness,'thickness_used':used_thickness}


def _rule_price(item,rules):
    d=norm(item['description']+' '+(item['material'] or ''))
    group=item['group_name']
    area=item['unit_area'] or 0
    if group=='Polímero/PSAI' and area>0:
        th=round(item['thickness'] or 0,2)
        material=norm(item['material'])
        if 'PSAI' in d:
            key=None  # Handled by psai_price_basis with CONTROLV source tracing.
        elif 'PETG' in d:
            key={0.5:'pl_petg_crist_05',1.0:'pl_petg_crist_10',1.5:'pl_petg_crist_15'}.get(th)
        elif 'ACRILICO' in d:
            family='leit' if 'LEITOSO' in d else 'crist' if 'CRISTAL' in d else None
            key={2.0:f'pl_acrilico_{family}_20',3.0:f'pl_acrilico_{family}_30'}.get(th) if family else None
        elif 'POLIONDA' in d:
            key={3.0:'pl_polionda_30',4.0:'pl_polionda_40'}.get(th)
        elif 'ADESIVO' in d:
            key='pl_adesivo_vinil_010'
        else: key=None
        if key and key in rules:
            printing=(item['printing'] or '0x0').lower()
            if printing=='0x0': return area*rules[key],key
            if printing in ('4x0','4x4') and 'imp_digital_face' in rules:
                faces=1 if printing=='4x0' else 2
                return area*(rules[key]+faces*rules['imp_digital_face']),key+' + imp_digital_face'
            # 4x1 has no evidenced rate; it requires a separate explicit decision.
    mapping=[('NIVELADOR','ferr_pe_nivelador'),('PORCA REBITE','ferr_porca_rebite'),
             ('REBITE COM ROSCA','ferr_porca_rebite'),('MANIPULO','ferr_manipulo'),
             ('TRAVA DE ENCAIXE','ferr_trava_encaixe'),('MINI CUNHA','ferr_mini_cunha'),
             ('ENGATE CAMA','ferr_mini_cunha')]
    for token,key in mapping:
        if token in d and key in rules:
            return rules[key],key
    if 'FITA DUPLA FACE' in d and 'acess_fita_dupla_face' in rules:
        length=item['length'] or 0
        if length>0: return length/1000*rules['acess_fita_dupla_face'],'acess_fita_dupla_face'
    return None,''


def price_item(item,rules,conn):
    if item.get('item_type')=='subconjunto':
        return None,''
    # This bought profile is quoted by linear meter even if the material
    # description also contains PET/PETG sheet terms.
    if (item.get('item_type')=='comprado' and
            re.search(r'\bPORTA (?:PRECO|ETIQUETA)\b',norm(item.get('description')))):
        length=porta_linear_length_mm(item)
        if length>0 and 'acess_porta_etiqueta' in rules:
            return (round(length/1000*rules['acess_porta_etiqueta'],4),
                    'Regra aprovada: acess_porta_etiqueta')
        return None,''
    basis=metal_price_basis(item,rules,conn)
    if basis:
        value=basis['weight']*basis['rate']*(1+basis['ipi_pct']/100)*basis['factor']
        return round(value,4),basis['source']
    basis=psai_price_basis(item,rules,conn)
    if basis:
        value=basis['area']*(basis['rate']+basis['print_rate'])*(1+basis['color_pct']/100)
        return round(value,4),f'PSAI {basis["source"]}: {basis["key"]}, esp {basis["thickness_requested"]:g}→{basis["thickness_used"]:g} mm, {basis["printing"]}, cor +{basis["color_pct"]:.0f}%, área {basis["area"]:.4f} m²'
    value,source=_rule_price(item,rules)
    if value is not None:
        return round(value,4),'Regra aprovada: '+source
    description=norm(item['description'])
    group=item['group_name']
    if group in ('Ferragens','Outros Comprados','Acessórios/Outros Comprados'):
        match=conn.execute('SELECT * FROM catalog_prices WHERE approved=1 AND unit=? AND normalized=? LIMIT 1',
                           (item['unit'],description)).fetchone()
        if match: return match['value'],f'Tabela aprovada #{match["id"]}'
    return None,''


def reprice_project(conn,project_id):
    rules=approved_rules(conn)
    for row in conn.execute('SELECT * FROM materials WHERE project_id=?',(project_id,)).fetchall():
        item=dict(row)
        if item.get('item_type')=='subconjunto':
            conn.execute("UPDATE materials SET unit_price=NULL,total_price=NULL,price_source='' WHERE id=?",(item['id'],))
            continue
        if item['price_source'] and item['price_source'].startswith('Ajuste manual aprovado'):
            continue
        value,source=price_item(item,rules,conn)
        total=round(value*item['quantity'],2) if value is not None else None
        conn.execute('UPDATE materials SET unit_price=?,total_price=?,price_source=? WHERE id=?',
                     (value,total,source,item['id']))
