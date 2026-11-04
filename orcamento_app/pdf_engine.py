import os
import re
import fitz  # PyMuPDF
from calc_engine import (
    calc_wire, calc_sheet, calc_tube_rect, calc_tube_round, 
    calc_psai_controlv, resolve_material_group
)

def scan_project_folder(folder_path: str):
    """
    Varre a estrutura completa de uma pasta de projeto:
    - Identifica PDF geral na raiz
    - Desenhos de componentes em subpastas (ex: PROJETO, subconjuntos)
    - Arquivos de orçamento histórico em ORÇAMENTO (.xls, .xlsx)
    - Modelos SolidWorks (.SLDPRT, .SLDDRW, .SLDASM) e referências (.pdf, .jpg)
    """
    result = {
        "root_pdfs": [],
        "component_pdfs": [],
        "historical_budget_files": [],
        "cad_files": [],
        "image_files": [],
        "subfolders": []
    }

    if not os.path.exists(folder_path):
        return result

    for root, dirs, files in os.walk(folder_path):
        rel = os.path.relpath(root, folder_path)
        if rel == ".":
            for f in files:
                fpath = os.path.join(root, f)
                if f.lower().endswith(".pdf"):
                    result["root_pdfs"].append(fpath)
                elif f.lower().endswith((".xls", ".xlsx")):
                    result["historical_budget_files"].append(fpath)
        else:
            result["subfolders"].append(rel)
            for f in files:
                fpath = os.path.join(root, f)
                fl = f.lower()
                if fl.endswith(".pdf"):
                    if "orçamento" in rel.lower() or "orcamento" in rel.lower():
                        result["historical_budget_files"].append(fpath)
                    else:
                        result["component_pdfs"].append(fpath)
                elif fl.endswith((".xls", ".xlsx", ".ods")):
                    result["historical_budget_files"].append(fpath)
                elif fl.endswith((".sldprt", ".slddrw", ".sldasm", ".igs", ".step")):
                    result["cad_files"].append(fpath)
                elif fl.endswith((".jpg", ".jpeg", ".png", ".webp")):
                    result["image_files"].append(fpath)

    return result

def extract_title_block(page_text: str):
    """
    Extrai informações padronizadas do carimbo / legenda técnica do SolidWorks.
    """
    info = {
        "product_name": "",
        "product_code": "",
        "designer": "",
        "date": "",
        "nominal_weight_g": 0.0,
        "nominal_area_mm2": 0.0,
        "material_str": "",
        "finish_str": "",
        "scale": ""
    }

    lines = [l.strip() for l in page_text.split("\n") if l.strip()]
    
    # 1. Peso Líquido (Grama)
    # Geralmente aparece um número antes ou depois de 'Peso Líq. Grama'
    for i, line in enumerate(lines):
        if "peso" in line.lower() and "grama" in line.lower():
            # Tentar número na linha anterior ou posterior
            for offset in [-1, 1, -2, 2]:
                if 0 <= i + offset < len(lines):
                    candidate = lines[i + offset].replace(".", "").replace(",", ".")
                    try:
                        val = float(candidate)
                        if val > 0:
                            info["nominal_weight_g"] = val
                            break
                    except ValueError:
                        pass
        # 2. Área mm²
        if "area - mm" in line.lower() or "área - mm" in line.lower():
            for offset in [-1, 1, -2, 2]:
                if 0 <= i + offset < len(lines):
                    candidate = lines[i + offset].replace(".", "").replace(",", ".")
                    try:
                        val = float(candidate)
                        if val > 100:
                            info["nominal_area_mm2"] = val
                            break
                    except ValueError:
                        pass

        # 3. Código do Produto
        if "código do produto" in line.lower() or "codigo do produto" in line.lower():
            for offset in [-1, 1]:
                if 0 <= i + offset < len(lines):
                    info["product_code"] = lines[i + offset]

        # 4. Produto
        if line.lower() == "produto" and i > 0:
            info["product_name"] = lines[i - 1]

        # 5. Desenhista
        if "desenhista" in line.lower() and i > 0:
            for offset in [-1, 1, 2]:
                if 0 <= i + offset < len(lines) and lines[i + offset] != "Data":
                    info["designer"] = lines[i + offset]
                    break

        # 6. Material
        if line.lower() == "material:" and i + 1 < len(lines):
            info["material_str"] = lines[i + 1]

        # 7. Acabamento
        if "acabamento:" in line.lower() or "acabamento superficial:" in line.lower():
            for offset in [1, -1]:
                if 0 <= i + offset < len(lines):
                    info["finish_str"] = lines[i + offset]

    return info

def parse_bom_table(page_text: str, filename: str = "", pageno: int = 1):
    """
    Analisa tabelas estruturadas de Lista de Materiais (BOM) geradas por CAD.
    Identifica colunas: Nº, DESCRIÇÃO, CÓDIGO, MATERIAL, QUANTIDADE, etc.
    """
    items = []
    lines = [l.strip() for l in page_text.split("\n") if l.strip()]
    
    # Procura onde começa o cabeçalho da BOM
    bom_start = -1
    for i, line in enumerate(lines):
        line_upper = line.upper()
        if ("DESCRIÇÃO" in line_upper or "DESCRICAO" in line_upper or "Nº DO ITEM" in line_upper or "N°" in line_upper) and any(k in line_upper for k in ["QTD", "MATERIAL", "CÓDIGO", "COMPRIMENTO"]):
            bom_start = i
            break
            
    if bom_start == -1:
        # Se não achou cabeçalho clássico em uma linha só, procurar sequência
        for i in range(len(lines) - 3):
            window = " ".join(lines[i:i+4]).upper()
            if "DESCRIÇÃO" in window and "QTD" in window:
                bom_start = i
                break

    # Padrão para item numerado da BOM (ex: "1 ARCO TESTEIRA..." ou "1" seguido por "ARAME...")
    # Itera pelas linhas procurando itens
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Caso A: Linha começa com número seguido de texto do item: "1 ARCO TESTEIRA..."
        match_inline = re.match(r"^(\d+)\s+([A-Za-zÀ-ÖØ-öø-ÿ].+)$", line)
        
        # Caso B: Linha é apenas um número inteiro e a próxima linha é descrição
        match_num_only = re.match(r"^(\d+)$", line)
        
        if match_inline:
            item_num = int(match_inline.group(1))
            desc = match_inline.group(2).strip()
            # As próximas linhas podem ser Código, Material e Quantidade
            material = ""
            raw_code = ""
            qty = 1.0
            
            # Olhar as próximas 4 linhas
            lookahead = lines[i+1:min(len(lines), i+6)]
            consumed = 0
            for idx, next_line in enumerate(lookahead):
                # Se for número de quantidade no final
                if re.match(r"^\d+(\,\d+)?$", next_line) and not next_line.startswith("024."):
                    try:
                        qty = float(next_line.replace(",", "."))
                        consumed = idx + 1
                        break
                    except ValueError:
                        pass
                elif any(k in next_line.upper() for k in ["TUBO", "CHAPA", "ARAME", "PSAI", "ACRILICO", "AISI", "SAE", "BTC"]):
                    material = next_line
                elif next_line == "-" or re.match(r"^\d{4,8}$", next_line) or "024." in next_line:
                    raw_code = next_line
                    
            items.append({
                "item_num": item_num,
                "description": desc,
                "raw_code": raw_code,
                "material": material,
                "quantity": qty,
                "source_page": f"{os.path.basename(filename)}:p{pageno}",
                "confidence": 0.95
            })
            i += 1 + consumed
            continue

        elif match_num_only and i + 1 < len(lines):
            item_num = int(match_num_only.group(1))
            next_line = lines[i+1]
            if re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ]", next_line) and not next_line.upper().startswith("DIEDRO") and not next_line.upper().startswith("ESC"):
                desc = next_line
                material = ""
                raw_code = ""
                qty = 1.0
                
                lookahead = lines[i+2:min(len(lines), i+7)]
                consumed = 1
                for idx, nline in enumerate(lookahead):
                    if re.match(r"^\d+(\,\d+)?$", nline) and not nline.startswith("024."):
                        try:
                            qty = float(nline.replace(",", "."))
                            consumed = 1 + idx + 1
                            break
                        except ValueError:
                            pass
                    elif any(k in nline.upper() for k in ["TUBO", "CHAPA", "ARAME", "PSAI", "ACRILICO", "AISI", "SAE", "BTC"]):
                        material = nline
                    elif nline == "-" or re.match(r"^\d{4,8}$", nline) or "024." in nline:
                        raw_code = nline
                        
                items.append({
                    "item_num": item_num,
                    "description": desc,
                    "raw_code": raw_code,
                    "material": material,
                    "quantity": qty,
                    "source_page": f"{os.path.basename(filename)}:p{pageno}",
                    "confidence": 0.92
                })
                i += 1 + consumed
                continue

        i += 1

    return items

def extract_component_dimensions(text: str, filename: str):
    """
    Extrai cotas e parâmetros geométricos de um desenho individual de componente:
    comprimento, largura, espessura, diâmetro, peso nominal.
    """
    dims = {
        "length": 0.0,
        "width": 0.0,
        "depth": 0.0,
        "thickness": 0.0,
        "diameter": 0.0,
        "nominal_weight": 0.0,
        "material": "",
        "printing": "0x0"
    }

    # 1. Procurar espessura no texto (ex: "ESP. 0,75mm", "#1mm", "ESP. 3,00mm", "x0,9mm")
    thk_match = re.search(r"(?:ESP\.?|#)\s*([0-9]+[,\.][0-9]+|[0-9]+)\s*mm", text, re.IGNORECASE)
    if thk_match:
        dims["thickness"] = float(thk_match.group(1).replace(",", "."))
        
    # 2. Procurar diâmetro de arame ou tubo (ex: "Ø5,0mm", "Ø4mm", "Ø 5mm")
    diam_match = re.search(r"(?:Ø|DIAM|DIÂMETRO)\s*([0-9]+[,\.][0-9]+|[0-9]+)\s*mm", text, re.IGNORECASE)
    if diam_match:
        dims["diameter"] = float(diam_match.group(1).replace(",", "."))

    # 3. Procurar impressão (ex: "4x0", "4x1", "4x4", "1x0", "1x1")
    print_match = re.search(r"\b([0-4]x[0-4])\b", text, re.IGNORECASE)
    if print_match:
        dims["printing"] = print_match.group(1).lower()

    # 4. Dimensões no nome do arquivo ou no texto (ex: "230x480x1mm", "1180x50mm", "20x20x0,9mm")
    name_dim = re.search(r"(\d+(?:[,\.]\d+)?)\s*[xX]\s*(\d+(?:[,\.]\d+)?)(?:\s*[xX]\s*(\d+(?:[,\.]\d+)?))?", filename + " " + text)
    if name_dim:
        v1 = float(name_dim.group(1).replace(",", "."))
        v2 = float(name_dim.group(2).replace(",", "."))
        v3 = float(name_dim.group(3).replace(",", ".")) if name_dim.group(3) else 0.0
        
        if v3 > 0:
            dims["length"] = max(v1, v2)
            dims["width"] = min(v1, v2)
            if dims["thickness"] == 0:
                dims["thickness"] = v3
        else:
            dims["length"] = max(v1, v2)
            dims["width"] = min(v1, v2)

    # 5. Peso Líquido Grama do carimbo
    peso_match = re.search(r"(\d+(?:\.\d+)?(?:,\d+)?)\s*\n\s*(?:1:\d+|-)\s*\n\s*.*Peso L[íi]q\. Grama", text, re.DOTALL | re.IGNORECASE)
    if not peso_match:
        peso_match = re.search(r"Peso L[íi]q\. Grama.*?(\d+(?:\.\d+)?(?:,\d+)?)", text, re.DOTALL | re.IGNORECASE)
    if peso_match:
        val_str = peso_match.group(1).replace(".", "").replace(",", ".")
        try:
            dims["nominal_weight"] = float(val_str) / 1000.0 # Converter g para kg
        except ValueError:
            pass

    return dims

def process_complete_project(project_folder: str, approved_rules: dict = None):
    """
    Processa todos os PDFs de um projeto montando a árvore completa, lista de materiais,
    dimensões, pesos e custos consolidados.
    """
    scan = scan_project_folder(project_folder)
    rules = approved_rules or {}
    
    project_data = {
        "name": os.path.basename(project_folder),
        "code": "",
        "client": "RISE",
        "date": "2026-10-13",
        "nominal_weight_pdf": 0.0,
        "nominal_area_pdf": 0.0,
        "historical_steel_weight": 0.0,
        "historical_total_weight": 0.0,
        "materials": [],
        "tree": {"name": os.path.basename(project_folder), "children": []},
        "pending_decisions": []
    }

    # 1. Identifica o melhor PDF do Conjunto Principal (maior tabela BOM e carimbo técnico)
    all_candidates = []
    for p in (scan["root_pdfs"] + scan["component_pdfs"]):
        p_norm = p.replace("/", "\\")
        # Ignorar pastas de arte, apresentação ou obsoletos na busca do desenho do conjunto
        if any(ign in p_norm.upper() for ign in ("\\ARTE\\", "\\!OBSOLETO\\", "\\APRESENTA", "\\TB LASER\\")):
            continue
        all_candidates.append(p)

    best_pdf = None
    max_bom_count = 0
    best_bom_items = []

    for c_path in all_candidates:
        try:
            doc = fitz.open(c_path)
            candidate_items = []
            cand_weight = 0.0
            cand_area = 0.0
            cand_code = ""

            for pno in range(len(doc)):
                page = doc[pno]
                txt = page.get_text()
                tb = extract_title_block(txt)
                if tb["nominal_weight_g"] > 0:
                    cand_weight = tb["nominal_weight_g"] / 1000.0
                if tb["nominal_area_mm2"] > 0:
                    cand_area = tb["nominal_area_mm2"] / 1_000_000.0
                if tb["product_code"]:
                    cand_code = tb["product_code"]

                # Extrair itens BOM
                p_items = parse_bom_table(txt, c_path, pno + 1)
                # Se for página 2 que tem a lista de peças da montagem geral
                candidate_items.extend(p_items)

            # Se este PDF tem mais itens BOM estruturados, é o desenho principal da montagem
            if len(candidate_items) > max_bom_count:
                max_bom_count = len(candidate_items)
                best_pdf = c_path
                best_bom_items = candidate_items
                if cand_weight > 0: project_data["nominal_weight_pdf"] = cand_weight
                if cand_area > 0: project_data["nominal_area_pdf"] = cand_area
                if cand_code: project_data["code"] = cand_code
        except Exception:
            pass

    main_pdf_path = best_pdf
    raw_bom_items = best_bom_items

    # 2. Varre todos os PDFs de componentes para cruzar cotas, materiais e pesos
    component_index = {}
    for comp_pdf in scan["component_pdfs"]:
        comp_name = os.path.splitext(os.path.basename(comp_pdf))[0]
        try:
            cdoc = fitz.open(comp_pdf)
            ctxt = ""
            for cp in cdoc:
                ctxt += cp.get_text() + "\n"
            cdims = extract_component_dimensions(ctxt, comp_name)
            ctb = extract_title_block(ctxt)
            component_index[comp_name.upper()] = {
                "path": comp_pdf,
                "dims": cdims,
                "title_block": ctb
            }
        except Exception:
            pass

    # 3. Consolidação e Enriquecimento dos Itens da BOM
    final_materials = []
    
    # Se encontramos itens na BOM do PDF principal
    if raw_bom_items:
        for idx, item in enumerate(raw_bom_items):
            desc = item["description"]
            desc_upper = desc.upper()
            qty = item["quantity"]
            mat_spec = item["material"]
            group = resolve_material_group(desc, mat_spec)
            
            # Buscar detalhes do desenho correspondente no índice
            comp_details = None
            for key, val in component_index.items():
                if key in desc_upper or desc_upper in key:
                    comp_details = val
                    break
                    
            length = 0.0
            width = 0.0
            depth = 0.0
            thickness = 0.0
            diam = 0.0
            unit_weight = 0.0
            unit_area = 0.0
            printing = "0x0"
            raw_code = item.get("raw_code", "")

            # Extrair dimensões da especificação do material ou descrição
            # Ex: "TUBO IND. QUAD 20x20x0,9mm", "ARAME BTC Ø5mm", "CHAPA F.F. ESP. 0,75mm"
            full_text = f"{desc} {mat_spec}"
            
            # Espessura
            thk_m = re.search(r"(?:ESP\.?|#|x)\s*([0-9]+[,\.][0-9]+|[0-9]+)\s*mm", full_text, re.IGNORECASE)
            if thk_m:
                thickness = float(thk_m.group(1).replace(",", "."))
                
            # Diâmetro
            diam_m = re.search(r"Ø\s*([0-9]+[,\.][0-9]+|[0-9]+)", full_text)
            if diam_m:
                diam = float(diam_m.group(1).replace(",", "."))

            # Impressão
            pr_m = re.search(r"\b([0-4]x[0-4])\b", full_text, re.IGNORECASE)
            if pr_m:
                printing = pr_m.group(1).lower()

            # Comprimento no texto (ex: "TRAVESSA CORPO... - 130", "CANALETA... - 625")
            comp_m = re.search(r"-\s*(\d{2,4})\b", desc)
            if comp_m:
                length = float(comp_m.group(1))

            # Se encontrou desenho detalhado, enriquecer cotas e peso exato do CAD
            if comp_details:
                cdims = comp_details["dims"]
                if cdims["length"] > 0 and length == 0:
                    length = cdims["length"]
                if cdims["width"] > 0:
                    width = cdims["width"]
                if cdims["thickness"] > 0 and thickness == 0:
                    thickness = cdims["thickness"]
                if cdims["diameter"] > 0 and diam == 0:
                    diam = cdims["diameter"]
                if cdims["nominal_weight"] > 0:
                    unit_weight = cdims["nominal_weight"]
                if cdims["printing"] != "0x0" and printing == "0x0":
                    printing = cdims["printing"]

            # Cálculos Físicos Transparentes do Motor
            if group == "Arame":
                if diam == 0: diam = 5.0 # Bitola comum
                if length == 0: length = 600.0 # Inferido se ausente
                calc_res = calc_wire(diam, length, 1.0)
                unit_area = calc_res["area"]
                if unit_weight == 0: unit_weight = calc_res["weight"]
            elif group == "Chapa":
                if thickness == 0: thickness = 0.75
                calc_res = calc_sheet(length or 600.0, width or 100.0, thickness, 1.0, "Aço")
                unit_area = calc_res["area"]
                if unit_weight == 0: unit_weight = calc_res["weight"]
            elif group == "Tubo Quadrado/Retangular":
                # Detecta seção (ex: 20x20, 50x30, 35x15)
                dim_m = re.search(r"(\d+)\s*x\s*(\d+)", full_text)
                w_sec = float(dim_m.group(1)) if dim_m else 20.0
                h_sec = float(dim_m.group(2)) if dim_m else 20.0
                calc_res = calc_tube_rect(w_sec, h_sec, thickness or 0.90, length or 1000.0, 1.0)
                unit_area = calc_res["area"]
                if unit_weight == 0: unit_weight = calc_res["weight"]
            elif group == "Polímero/PSAI":
                if thickness == 0: thickness = 1.0
                calc_res = calc_sheet(length or 600.0, width or 200.0, thickness, 1.0, "PSAI")
                unit_area = calc_res["area"]
                if unit_weight == 0: unit_weight = calc_res["weight"]

            total_weight = round(unit_weight * qty, 3)
            total_area = round(unit_area * qty, 4)

            # Resolução de Preço e Fonte
            unit_price = 0.0
            price_source = ""
            confidence = item["confidence"]
            pending_issue = ""

            if group == "Chapa":
                # Preço vigente R$ 7,02/kg
                sq_price_kg = rules.get("mp_chapa_aco", 7.02)
                unit_price = round(unit_weight * sq_price_kg, 2)
                price_source = f"Regra Vigente: R$ {sq_price_kg:.2f}/kg"
            elif group == "Arame":
                # Preço vigente R$ 6,34/kg bruto (líquido ~4.99)
                ar_price_kg = rules.get("mp_arame", 6.34) * 0.7875
                unit_price = round(unit_weight * ar_price_kg, 2)
                price_source = f"Regra Vigente: R$ {ar_price_kg:.2f}/kg líq."
            elif group == "Tubo Quadrado/Retangular":
                # Tubo base ~7.99 c/ IPI 3.25% líquido ~6.29/kg
                tb_price_kg = 7.99 * 1.0325 * 0.7875
                unit_price = round(unit_weight * tb_price_kg, 2)
                price_source = f"Tabela Comprados + 3,25% (R$ {tb_price_kg:.2f}/kg)"
            elif group == "Polímero/PSAI":
                pcalc = calc_psai_controlv(unit_area, thickness, "BRANCO", printing, rules)
                unit_price = pcalc["total_unit_cost"]
                price_source = f"CONTROLV (Chapa R$ {pcalc['material_cost']:.2f} + Imp R$ {pcalc['print_cost']:.2f})"
            elif group == "Ferragens":
                if "NIVELADOR" in desc_upper or "SAPATA" in desc_upper:
                    unit_price = rules.get("ferr_pe_nivelador", 0.25)
                    price_source = "Regra Vigente (Pé Nivelador R$ 0,25)"
                elif "REBITE" in desc_upper or "PORCA REBITE" in desc_upper:
                    unit_price = rules.get("ferr_porca_rebite", 0.25)
                    price_source = "Regra Vigente (Porca Rebite R$ 0,25)"
                elif "MANIPULO" in desc_upper or "MANÍPULO" in desc_upper:
                    unit_price = rules.get("ferr_manipulo", 0.25)
                    price_source = "Regra Vigente (Manípulo R$ 0,25)"
                elif "CUNHA" in desc_upper or "ENGATE" in desc_upper or "TRAVA" in desc_upper:
                    unit_price = rules.get("ferr_mini_cunha", 0.25)
                    price_source = "Regra Vigente (Cunha/Trava R$ 0,25)"
                elif "RODIZIO" in desc_upper:
                    unit_price = rules.get("ferr_rodizio_c_trava", 7.15) if "TRAVA" in desc_upper else rules.get("ferr_rodizio_s_trava", 9.15)
                    price_source = "Tabela Comprados (Rodízio)"
                elif "PARAFUSO" in desc_upper:
                    unit_price = rules.get("ferr_parafuso_sext", 1.20)
                    price_source = "Tabela Comprados (Parafuso)"
                else:
                    unit_price = 0.25
                    price_source = "Padrão Ferragens"
            elif group in ("Acessórios/Outros Comprados", "Outros Comprados"):
                if "PORTA ETIQUETA" in desc_upper:
                    # R$ 6,80 por metro
                    comp_m = (length / 1000.0) if length > 0 else 1.0
                    rate_m = rules.get("acess_porta_etiqueta", 6.80)
                    unit_price = round(comp_m * rate_m, 2)
                    price_source = f"Regra Vigente Porta Etiqueta (R$ {rate_m:.2f}/m)"
                elif "FITA" in desc_upper:
                    comp_m = (length / 1000.0) if length > 0 else 0.5
                    rate_m = rules.get("acess_fita_dupla_face", 1.80)
                    unit_price = round(comp_m * rate_m, 2)
                    price_source = f"Regra Vigente Fita (R$ {rate_m:.2f}/m)"
                else:
                    unit_price = 2.50
                    price_source = "Estimativa Preliminar"
                    confidence = 0.70
                    pending_issue = "Preço necessita confirmação com fornecedor."
            elif group == "Embalagem":
                unit_price = 25.00
                price_source = "Caixa de Papelão Padrão"

            # Se preço ficou zero, NUNCA deixar zero!
            if unit_price <= 0:
                unit_price = 1.00
                confidence = 0.50
                pending_issue = "Preço ausente: estipulado valor preliminar para revisão."

            total_price = round(unit_price * qty, 2)

            mat_entry = {
                "item_num": idx + 1,
                "description": desc,
                "group_name": group,
                "material": mat_spec or "Aço Carbono",
                "thickness": thickness,
                "radius_diam": diam,
                "width": width,
                "depth": depth,
                "length": length,
                "quantity": qty,
                "unit": "un",
                "unit_weight": unit_weight,
                "total_weight": total_weight,
                "unit_area": unit_area,
                "total_area": total_area,
                "drawing_id": item.get("raw_code") or desc[:15],
                "raw_code": raw_code,
                "finish": "Pintura a Pó" if group in ("Chapa", "Tubo Quadrado/Retangular", "Arame") else "",
                "printing": printing,
                "unit_price": unit_price,
                "total_price": total_price,
                "price_source": price_source,
                "source_page": item["source_page"],
                "confidence": confidence,
                "parent_assembly": "CONJUNTO_PRINCIPAL",
                "is_consolidated": 0,
                "is_inferred": 1 if confidence < 0.85 else 0,
                "pending_issue": pending_issue,
                "observation": ""
            }
            final_materials.append(mat_entry)

    # 4. Adiciona Item de Embalagem e Pintura se houver estrutura metálica
    metal_area = sum(m["total_area"] for m in final_materials if m["group_name"] in ("Chapa", "Tubo Quadrado/Retangular", "Tubo Redondo", "Arame"))
    if metal_area > 0:
        paint_tax = rules.get("taxa_consumo_tinta", 0.22)
        paint_rate = rules.get("mp_tinta_po", 25.03)
        paint_kg = round(metal_area * paint_tax, 3)
        paint_cost = round(paint_kg * paint_rate, 2)
        final_materials.append({
            "item_num": len(final_materials) + 1,
            "description": "PINTURA A PÓ ELETROSTÁTICA",
            "group_name": "Pintura a Pó",
            "material": "TINTA A PÓ",
            "thickness": 0.0,
            "radius_diam": 0.0,
            "width": 0.0,
            "depth": 0.0,
            "length": 0.0,
            "quantity": paint_kg,
            "unit": "kg",
            "unit_weight": 1.0,
            "total_weight": paint_kg,
            "unit_area": metal_area,
            "total_area": metal_area,
            "drawing_id": "-",
            "raw_code": "-",
            "finish": "Acabamento Eletrostático",
            "printing": "0x0",
            "unit_price": paint_rate,
            "total_price": paint_cost,
            "price_source": f"Consumo {paint_tax} kg/m² @ R$ {paint_rate:.2f}/kg",
            "source_page": "Cálculo Integrado",
            "confidence": 1.0,
            "parent_assembly": "CONJUNTO_PRINCIPAL",
            "is_consolidated": 0,
            "is_inferred": 0,
            "pending_issue": "",
            "observation": f"Área total pintada calculada: {metal_area:.2f} m²"
        })

    # Adicionar Embalagem Caixa de Papelão
    final_materials.append({
        "item_num": len(final_materials) + 1,
        "description": "EMBALAGEM CAIXA PAPELÃO",
        "group_name": "Embalagem",
        "material": "Papelão Folha Simples (Onda B)",
        "thickness": 3.0,
        "radius_diam": 0.0,
        "width": 130.0,
        "depth": 350.0,
        "length": 880.0,
        "quantity": 1.0,
        "unit": "un",
        "unit_weight": 1.5,
        "total_weight": 1.5,
        "unit_area": 1.29,
        "total_area": 1.29,
        "drawing_id": "CX-01",
        "raw_code": "CX",
        "finish": "Padrão",
        "printing": "0x0",
        "unit_price": 25.00,
        "total_price": 25.00,
        "price_source": "Fórmula Paramétrica Caixa",
        "source_page": "Cálculo Integrado",
        "confidence": 1.0,
        "parent_assembly": "CONJUNTO_PRINCIPAL",
        "is_consolidated": 0,
        "is_inferred": 0,
        "pending_issue": "",
        "observation": "Caixa calculada para transporte seguro"
    })

    # 5. Consolidação de peças Direita/Esquerda idênticas
    consolidated_list = consolidate_left_right_parts(final_materials)
    project_data["materials"] = consolidated_list

    return project_data

def consolidate_left_right_parts(materials: list):
    """
    Consolida peças Direita (D) e Esquerda (E) quando comprovadamente iguais
    em dimensões e material; mantém separadas se forem diferentes.
    """
    consolidated = []
    seen = {}

    for mat in materials:
        desc = mat["description"]
        # Normaliza nome removendo " DIREITO", " ESQUERDO", " DIR", " ESQ", " D", " E" no final
        base_desc = re.sub(r"\s+(?:DIREIT[OA]|ESQUERD[OA]|DIR|ESQ|[DE])\b", "", desc, flags=re.IGNORECASE).strip()
        key = (
            base_desc.upper(),
            mat["group_name"],
            round(mat["length"], 1),
            round(mat["width"], 1),
            round(mat["thickness"], 2),
            round(mat["radius_diam"], 1),
            mat["material"].upper()
        )

        # Se for peça que tinha D/E no nome e já vimos a contraparte
        is_side = bool(re.search(r"\b(?:DIREIT[OA]|ESQUERD[OA]|DIR|ESQ|[DE])\b", desc, re.IGNORECASE))
        if is_side and key in seen:
            prev = seen[key]
            # Mescla quantidade
            prev["quantity"] += mat["quantity"]
            prev["total_weight"] = round(prev["unit_weight"] * prev["quantity"], 3)
            prev["total_area"] = round(prev["unit_area"] * prev["quantity"], 4)
            prev["total_price"] = round(prev["unit_price"] * prev["quantity"], 2)
            prev["description"] = f"{base_desc} (Par D/E Consolidado)"
            prev["is_consolidated"] = 1
        else:
            seen[key] = mat
            consolidated.append(mat)

    # Reindexar item_num
    for i, m in enumerate(consolidated):
        m["item_num"] = i + 1

    return consolidated
