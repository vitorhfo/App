import math

# Densidades padronizadas em g/cm³ (= kg/dm³ = 10^-6 kg/mm³)
DENSIDADE_ACO_CARBONO = 7.85
DENSIDADE_INOX = 7.90
DENSIDADE_ALUMINIO = 2.70
DENSIDADE_PSAI = 1.05
DENSIDADE_ACRILICO = 1.19
DENSIDADE_PETG = 1.27
DENSIDADE_POLIONDA = 0.45

def calc_wire(diameter_mm: float, length_mm: float, qty: float = 1.0):
    """
    Cálculo exato para Arame BTC:
    Área superficial externa (m²) e Peso (kg)
    """
    if diameter_mm <= 0 or length_mm <= 0 or qty <= 0:
        return {"area": 0.0, "weight": 0.0}
    
    # Área superficial cilíndrica = pi * diam * comp (em m²)
    area = (math.pi * diameter_mm * length_mm * qty) / 1_000_000.0
    
    # Volume = pi * (d/2)^2 * comp
    radius = diameter_mm / 2.0
    vol_mm3 = math.pi * (radius ** 2) * length_mm * qty
    weight = (vol_mm3 * DENSIDADE_ACO_CARBONO) / 1_000_000.0
    
    return {
        "area": round(area, 4),
        "weight": round(weight, 4)
    }

def calc_sheet(length_mm: float, width_mm: float, thickness_mm: float, qty: float = 1.0, material: str = "Aço Carbono"):
    """
    Cálculo de Chapa:
    Área plana de 1 face (m²), e Peso (kg) conforme densidade do material.
    """
    if length_mm <= 0 or width_mm <= 0 or qty <= 0:
        return {"area": 0.0, "weight": 0.0}
    
    area_1face = (length_mm * width_mm * qty) / 1_000_000.0
    
    mat_upper = (material or "").upper()
    if "INOX" in mat_upper:
        rho = DENSIDADE_INOX
    elif "ALUM" in mat_upper:
        rho = DENSIDADE_ALUMINIO
    elif "PSAI" in mat_upper or "PS" in mat_upper:
        rho = DENSIDADE_PSAI
    elif "ACRIL" in mat_upper:
        rho = DENSIDADE_ACRILICO
    elif "PETG" in mat_upper:
        rho = DENSIDADE_PETG
    elif "POLIONDA" in mat_upper:
        rho = DENSIDADE_POLIONDA
    else:
        rho = DENSIDADE_ACO_CARBONO
        
    thk = thickness_mm
    if thk <= 0:
        return {"area": round(area_1face, 4), "weight": 0.0}
    vol_mm3 = length_mm * width_mm * thk * qty
    weight = (vol_mm3 * rho) / 1_000_000.0
    
    return {
        "area": round(area_1face, 4),
        "weight": round(weight, 4)
    }

def calc_tube_rect(w_mm: float, h_mm: float, thickness_mm: float, length_mm: float, qty: float = 1.0):
    """
    Cálculo de Tubo Retangular ou Quadrado:
    Perímetro externo, área externa superficial total (m²) e peso metálico exato (kg)
    """
    if w_mm <= 0 or h_mm <= 0 or length_mm <= 0 or qty <= 0:
        return {"area": 0.0, "weight": 0.0}
    
    if thickness_mm <= 0 or thickness_mm * 2 >= min(w_mm, h_mm):
        return {"area": 0.0, "weight": 0.0}
    thk = thickness_mm
    
    perimeter = 2.0 * (w_mm + h_mm)
    area = (perimeter * length_mm * qty) / 1_000_000.0
    
    # Área da seção transversal oca = W*H - (W - 2t)*(H - 2t)
    # simplificado: 2*t*(W + H - 2t)
    inner_w = max(0.0, w_mm - 2.0 * thk)
    inner_h = max(0.0, h_mm - 2.0 * thk)
    section_area_mm2 = (w_mm * h_mm) - (inner_w * inner_h)
    
    vol_mm3 = section_area_mm2 * length_mm * qty
    weight = (vol_mm3 * DENSIDADE_ACO_CARBONO) / 1_000_000.0
    
    return {
        "area": round(area, 4),
        "weight": round(weight, 4)
    }

def calc_tube_round(diameter_mm: float, thickness_mm: float, length_mm: float, qty: float = 1.0):
    """
    Cálculo de Tubo Redondo:
    Área externa e peso por seção anular.
    """
    if diameter_mm <= 0 or length_mm <= 0 or qty <= 0:
        return {"area": 0.0, "weight": 0.0}
    
    if thickness_mm <= 0 or thickness_mm * 2 >= diameter_mm:
        return {"area": 0.0, "weight": 0.0}
    thk = thickness_mm
    area = (math.pi * diameter_mm * length_mm * qty) / 1_000_000.0
    
    # Seção = pi * t * (D - t)
    section_mm2 = math.pi * thk * max(0.0, (diameter_mm - thk))
    vol_mm3 = section_mm2 * length_mm * qty
    weight = (vol_mm3 * DENSIDADE_ACO_CARBONO) / 1_000_000.0
    
    return {
        "area": round(area, 4),
        "weight": round(weight, 4)
    }

def calc_psai_controlv(area_m2: float, thickness_mm: float, color: str = "BRANCO", printing_type: str = "0x0", rules_dict: dict = None):
    """
    Cálculo de PSAI e Impressão conforme Tabela CONTROLV:
    - Preço base do m² do PSAI pela espessura e acabamento
    - Preço de impressão: R$ 25/m² para 4x0, R$ 50/m² para 4x4
    - PSAI Colorido ou 4x1: +10% sobre o valor final
    """
    if area_m2 <= 0:
        return {"material_cost": 0.0, "print_cost": 0.0, "total_unit_cost": 0.0, "sqm_rate": 0.0}
    
    rules = rules_dict or {}
    
    # Tabela padrão CONTROLV
    thk = round(thickness_mm, 2)
    col = (color or "BRANCO").upper()
    
    if "CRISTAL" in col:
        if thk <= 2.2:
            base_sqm = rules.get("pl_psai_cristal_20", 64.24)
        else:
            base_sqm = rules.get("pl_psai_cristal_30", 96.00)
    elif "LEITOSO" in col:
        if thk <= 2.2:
            base_sqm = rules.get("pl_psai_leitoso_20", 64.24)
        else:
            base_sqm = rules.get("pl_psai_leitoso_100", 115.00)
    else: # BRANCO
        if thk <= 1.2:
            base_sqm = rules.get("pl_psai_branco_10", 29.40)
        elif thk <= 1.7:
            base_sqm = rules.get("pl_psai_branco_15", 44.00)
        else:
            base_sqm = rules.get("pl_psai_branco_20", 58.50)
            
    material_cost = area_m2 * base_sqm
    
    print_rate = rules.get("imp_digital_face", 25.00)
    ptype = (printing_type or "0X0").upper().replace("X", "x")
    
    if ptype in ("4x0", "1x0", "0x4"):
        print_cost = area_m2 * print_rate
    elif ptype in ("4x4", "1x1"):
        print_cost = area_m2 * (2.0 * print_rate)
    elif ptype in ("4x1", "1x4"):
        # 4x1 tem impressão e adicional de 10%
        print_cost = area_m2 * (1.5 * print_rate)
    else: # 0x0
        print_cost = 0.0
        
    subtotal = material_cost + print_cost
    
    # Se for 4x1 ou colorido, aplica +10%
    if ptype in ("4x1", "1x4") or "COLORIDO" in col:
        subtotal = subtotal * 1.10
        
    return {
        "material_cost": round(material_cost, 2),
        "print_cost": round(print_cost, 2),
        "total_unit_cost": round(subtotal, 2),
        "sqm_rate": round(subtotal / area_m2, 2) if area_m2 > 0 else 0.0
    }

def calc_cardboard_box(length_mm: float, width_mm: float, height_mm: float, flap_type: int = 2, sheet_type: int = 2, rules_dict: dict = None, qty: float = 1.0):
    """
    Fórmula original da planilha "ORÇAMENTO CAIXA PAPELÃO.ods":
    - Aba Normal (1): ((100 + 2*(C + L)) * (A + L)) / 1.000.000
    - Aba Transpassada (2): ((100 + 2*(C + L)) * (A + 2*L)) / 1.000.000
    - Tipos de folha:
      1: Onda Baixa (R$ 2,09/m²)
      2: Folha Simples (R$ 5,20/m²)
      3: Folha Dupla (R$ 5,40/m²)
    """
    if length_mm <= 0 or width_mm <= 0 or height_mm <= 0:
        return {"area_m2": 0.0, "unit_cost": 0.0, "total_cost": 0.0}
        
    rules = rules_dict or {}
    C = length_mm
    L = width_mm
    A = height_mm
    
    comp_aberto = 100.0 + 2.0 * (C + L)
    if flap_type == 1: # Aba Normal
        larg_aberta = A + L
    else: # Aba Transpassada
        larg_aberta = A + 2.0 * L
        
    area_m2 = (comp_aberto * larg_aberta) / 1_000_000.0
    
    if sheet_type == 1:
        sqm_rate = rules.get("cx_onda_baixa", 2.09)
    elif sheet_type == 3:
        sqm_rate = rules.get("cx_folha_dupla", 5.40)
    else:
        sqm_rate = rules.get("cx_folha_simples", 5.20)
        
    unit_cost = area_m2 * sqm_rate
    total_cost = unit_cost * qty
    
    return {
        "area_m2": round(area_m2, 4),
        "sqm_rate": round(sqm_rate, 2),
        "unit_cost": round(unit_cost, 2),
        "total_cost": round(total_cost, 2)
    }

def resolve_material_group(description: str, material_str: str = ""):
    """
    Classifica automaticamente o item em seu grupo padronizado.
    """
    text = f"{description} {material_str}".upper()
    
    if "EMBALAGEM" in text or "CAIXA" in text:
        return "Embalagem"
    elif ("MDF" in material_str.upper() or
          (not material_str.strip() and "MDF" in description.upper())):
        # MDF is a purchased board even when the CAD role says woodwork or
        # the source material begins with "CHAPA DE MDF".
        return "Outros Comprados"
    elif "FERRO CHATO" in text or "FERRO LAMINADO" in text or "BARRA CHATA" in text:
        # A dimensioned flat bar is cut from raw metal, including when it is
        # one row inside a drawing whose other cuts are tubes.
        return "Chapa"
    elif "TUBO" in text or " TB " in text or text.startswith("TB "):
        if "RED" in text or "Ø" in text:
            return "Tubo Redondo"
        return "Tubo Quadrado/Retangular"
    elif "ARAME" in text:
        return "Arame"
    elif "PORTA ETIQUETA" in text or "PORTA PRECO" in text or "PORTA PREÇO" in text:
        return "Acessórios/Outros Comprados"
    elif "PSAI" in text or "ACRILICO" in text or "ACRÍLICO" in text or "PETG" in text or "POLIONDA" in text or "ADESIVO" in text or "PVC" in text:
        return "Polímero/PSAI"
    elif "CHAPA" in text or " CH " in text or text.startswith("CH ") or "SAE 1008" in text or "CANALETA" in text or "BAGUETE" in text:
        return "Chapa"
    elif any(k in text for k in ["PARAFUSO", "PORCA", "ARRUELA", "REBITE", "NIVELADOR", "MANIPULO", "MANÍPULO", "SAPATA", "RODIZIO", "RODÍZIO", "CUNHA", "ENGATE", "TRAVA"]):
        return "Ferragens"
    elif ("FITA" in text or "PORTA ETIQUETA" in text or
          "PORTA PRECO" in text or "PORTA PREÇO" in text or "PERFIL" in text):
        return "Acessórios/Outros Comprados"
    elif "TINTA" in text or "PINTURA" in text:
        return "Pintura a Pó"
    elif "IMPRESSÃO" in text or "IMPRESSAO" in text:
        return "Impressão"
    else:
        return "Outros Comprados"
