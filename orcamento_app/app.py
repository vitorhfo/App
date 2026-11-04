import os
import json
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import BASE_DIR, UPLOADS_DIR, HOST, PORT, DADOS_DIR
from database import get_connection, init_db, get_default_markup_json
from calc_engine import (
    calc_wire, calc_sheet, calc_tube_rect, calc_tube_round, 
    calc_cardboard_box
)
from markup_engine import calculate_markup
from comparator import analyze_weights
from reader_v3 import process_complete_project
from wire_variants import insert_wire_variants
from pricing import (approved_rules, reprice_project, price_item, metal_price_basis,
                     psai_price_basis, porta_linear_length_mm)
from side_quantities import annotate_side_totals
from wire_allowance import apply_wire_allowance, mass_per_mm
from mass_math import calculated_weight, ceil_kg, reconcile_item_weight, strip_weight_note
from manual_validation import synchronize_tube_profile, linked_drawing, drawing_difference
from item_types import infer_item_type, has_detail_children, VALID_TYPES
from assembly_quantities import scaled_descendants
from exporter import export_budget_pdf, export_budget_xlsx, export_budget_csv
from template_reports import export_template_reports, XLSX_MIME, XLS_MIME
from source_inventory import list_project_pdfs
from ai_pdf_review import (configured_key, resolve_pdf, page_payload, request_google,
                           load_review, save_review, compare_review, validate_model,
                           AUTO_MODEL, AUTO_MODELS, MODEL, MODEL_OPTIONS)
from ai_review_queue import enqueue_project, enqueue_pdf, job_status, pause_until, start_worker
from ai_apply_dimensions import apply_review
from ai_bulk_dimensions import apply_pending_ai_dimensions, preview_pending_ai_dimensions
from quote_views import build_quote_views
from upload_imports import (MAX_BYTES, MAX_PDFS, new_upload_area, pdf_target,
                            save_upload, extract_zip_pdfs, extract_rar_pdfs)
from manual_import_overrides import preserve_manual_values

app = FastAPI(title="Orçamentos PDV & Displays - Sistema Integrado", version="2.0")

# Montar arquivos estáticos
static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.on_event("startup")
def startup_event():
    init_db()
    start_worker()

# --- MODELOS PYDANTIC ---
class ProjectCreate(BaseModel):
    name: str
    code: Optional[str] = ""
    client: Optional[str] = "RISE"
    date: Optional[str] = "2026-10-13"
    folder_path: Optional[str] = ""
    notes: Optional[str] = ""

class MaterialUpdate(BaseModel):
    description: Optional[str] = None
    group_name: Optional[str] = None
    item_type: Optional[str] = None
    parent_assembly: Optional[str] = None
    material: Optional[str] = None
    thickness: Optional[float] = None
    radius_diam: Optional[float] = None
    width: Optional[float] = None
    depth: Optional[float] = None
    length: Optional[float] = None
    quantity: Optional[float] = None
    unit_weight: Optional[float] = None
    unit_price: Optional[float] = None
    printing: Optional[str] = None
    observation: Optional[str] = None
    unit: Optional[str] = None
    pending_issue: Optional[str] = None

class MaterialCreate(MaterialUpdate):
    description: str
    group_name: str
    quantity: float = 1.0
    unit: str = 'un'
    source_page: Optional[str] = None
    drawing_id: Optional[str] = None
    raw_code: Optional[str] = None
    confidence: Optional[float] = None

class WireVariantSelection(BaseModel):
    quantity: float

class MarkupUpdate(BaseModel):
    mo_items: Optional[list] = None
    operational_items: Optional[list] = None
    tax_items: Optional[list] = None
    margin_mp: Optional[float] = None
    margin_mc: Optional[float] = None

class BoxConfigUpdate(BaseModel):
    length: float
    width: float
    height: float
    flap_type: int
    sheet_type: int
    quantity: Optional[float] = 1.0

class RuleUpdate(BaseModel):
    value: float
    is_active: Optional[int] = 1
    notes: Optional[str] = None
    approved: Optional[int] = 0

class VersionCreate(BaseModel):
    final: bool = False
    final_price: Optional[float] = None
    name: Optional[str] = None

class AiPdfReviewRequest(BaseModel):
    path: str
    page: int = 1
    model: str = MODEL
    force: bool = False

class AiPdfReviewAllRequest(BaseModel):
    path: str
    model: str = AUTO_MODEL
    force: bool = False

# --- AUXILIARES DE CÁLCULO E REGRAS ---
def get_rules_dict(conn):
    return approved_rules(conn)

def get_project_full_data(project_id: int):
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    p_row = cur.fetchone()
    if not p_row:
        conn.close()
        raise HTTPException(status_code=404, detail="Projeto não encontrado")
    project = dict(p_row)

    cur.execute("SELECT * FROM materials WHERE project_id = ? ORDER BY item_num", (project_id,))
    materials = [dict(r) for r in cur.fetchall()]
    annotate_side_totals(materials)
    rules=approved_rules(conn)
    for item in materials:
        if (item.get('price_source') or '').startswith(('Chapa:','Arame:','Tubo:')):
            basis=metal_price_basis(item,rules,conn)
            if basis and item.get('unit_price')==round(
                    basis['weight']*basis['rate']*(1+basis['ipi_pct']/100)*basis['factor'],4):
                item['price_basis']=basis
        elif (item.get('price_source') or '').startswith('PSAI '):
            basis=psai_price_basis(item,rules,conn)
            if basis and item.get('unit_price')==round(
                    basis['area']*(basis['rate']+basis['print_rate'])*(1+basis['color_pct']/100),4):
                item['psai_price_basis']=basis

    cur.execute("SELECT * FROM markup_configs WHERE project_id = ?", (project_id,))
    mk_row = cur.fetchone()
    if mk_row:
        mk_config = {
            "mo_items": json.loads(mk_row["mo_items"]),
            "operational_items": json.loads(mk_row["operational_items"]),
            "tax_items": json.loads(mk_row["taxes_items"]),
            "margin_mp": mk_row["margin_mp"],
            "margin_mc": mk_row["margin_mc"]
        }
    else:
        mk_config = get_default_markup_json()
        cur.execute("""
        INSERT INTO markup_configs (project_id, mo_items, operational_items, taxes_items, margin_mp, margin_mc)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (project_id, json.dumps(mk_config["mo_items"]), json.dumps(mk_config["operational_items"]), json.dumps(mk_config["tax_items"]), mk_config["margin_mp"], mk_config["margin_mc"]))
        conn.commit()

    cur.execute("SELECT * FROM box_configs WHERE project_id = ?", (project_id,))
    box_row = cur.fetchone()
    if box_row:
        box_config = dict(box_row)
    else:
        box_config = {"length": 880.0, "width": 130.0, "height": 350.0, "flap_type": 2, "sheet_type": 2, "quantity": 1.0}
        cur.execute("""
        INSERT INTO box_configs (project_id, length, width, height, flap_type, sheet_type, quantity)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (project_id, 880.0, 130.0, 350.0, 2, 2, 1.0))
        conn.commit()

    cur.execute("SELECT * FROM pending_decisions WHERE project_id = ?", (project_id,))
    pendings = [dict(r) for r in cur.fetchall()]
    wire_variants = [dict(r) for r in cur.execute('''SELECT v.*,
        m.quantity AS current_quantity FROM wire_variants v
        LEFT JOIN materials m ON m.id=v.material_id
        WHERE v.project_id=? ORDER BY v.source_page, v.measure_a''', (project_id,))]
    ai_discovered_items = [dict(r) for r in cur.execute('''SELECT d.*,
        m.quantity AS current_quantity FROM ai_discovered_items d
        LEFT JOIN materials m ON m.id=d.material_id
        WHERE d.project_id=? ORDER BY d.source_page,d.description''', (project_id,))]

    # Totais de custo
    def is_psai(m):
        return m['group_name'] == 'Polímero/PSAI' or 'PSAI' in (m.get('material') or '').upper()
    cost_mp = sum(m["total_price"] or 0 for m in materials
                  if m['item_type'] == 'materia_prima' and not is_psai(m))
    cost_mc = sum(m["total_price"] or 0 for m in materials
                  if m['item_type'] == 'comprado' or (m['item_type'] != 'subconjunto' and is_psai(m)))
    missing_prices = [m['id'] for m in materials if m['item_type']!='subconjunto' and m['unit_price'] is None]
    missing_units = [m['id'] for m in materials if m['item_type']!='subconjunto' and m['unit'] not in ('un','kg','m','m2')]
    missing_weights = [m['id'] for m in materials if (m['unit_weight'] or 0) <= 0
                       and m['item_type']!='subconjunto' and m['group_name'] not in ('Impressão','Pintura a Pó')]
    unresolved_assemblies=[m['id'] for m in materials if m['item_type']=='subconjunto'
                           and not has_detail_children(m,materials)]
    unresolved = [p['id'] for p in pendings if p['status']=='PENDENTE']
    markup_approved = bool(mk_row['approved']) if mk_row else False
    steel_weight = sum(m["total_weight"] for m in materials if m['item_type']!='subconjunto' and m["group_name"] in ("Chapa", "Tubo Quadrado/Retangular", "Tubo Redondo", "Arame"))

    # Markup calculation
    markup_res = calculate_markup(cost_mp, cost_mc, steel_weight, mk_config)

    # Weight comparison
    weight_res = analyze_weights(
        materials,
        nominal_pdf_weight=project.get("nominal_weight_pdf", 0.0),
        historical_steel_weight=project.get("historical_steel_weight", 0.0),
        historical_total_weight=project.get("historical_total_weight", 0.0),
        tolerance_pct=project.get("tolerance_percent", 5.0)
    )
    can_finalize = (bool(materials) and not missing_prices and not missing_units
                    and not missing_weights and not unresolved and not unresolved_assemblies
                    and weight_res['status_pdf_compare'] != 'DIVERGENCIA')
    project['status'] = 'FINAL' if can_finalize and project['status']=='FINAL' else 'PRELIMINAR'
    project['missing_prices_count'] = len(missing_prices)
    project['missing_units_count'] = len(missing_units)
    project['missing_weights_count'] = len(missing_weights)
    project['open_decisions_count'] = len(unresolved)
    project['unresolved_assemblies_count'] = len(unresolved_assemblies)

    conn.close()

    return {
        "project": project,
        "materials": materials,
        "wire_variants": wire_variants,
        "ai_discovered_items": ai_discovered_items,
        "markup_config": mk_config,
        "markup_result": markup_res,
        "box_config": box_config,
        "weight_result": weight_res,
        "pending_decisions": pendings,
        "missing_price_ids": missing_prices,
        "missing_unit_ids": missing_units,
        "missing_weight_ids": missing_weights,
        "unresolved_assembly_ids": unresolved_assemblies,
        "can_finalize": can_finalize,
        "markup_approved": markup_approved
    }

# --- ROTAS PRINCIPAIS ---
@app.get("/", response_class=HTMLResponse)
def index_page():
    html_path = os.path.join(BASE_DIR, "templates", "index.html")
    if os.path.exists(html_path):
        with open(html_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Sistema de Orçamentos de Displays PDV</h1><p>Template em carregamento...</p>"

@app.get("/api/projects")
def list_projects():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM projects ORDER BY updated_at DESC")
    projects = [dict(r) for r in cur.fetchall()]
    
    # Adicionar resumo financeiro rápido para cada projeto
    for p in projects:
        p_id = p["id"]
        cur.execute("SELECT group_name, item_type, unit_price, total_price, total_weight, finished_total_weight FROM materials WHERE project_id = ?", (p_id,))
        mats = [dict(m) for m in cur.fetchall()]
        cost_mp = sum(m["total_price"] or 0 for m in mats if m['item_type']=='materia_prima')
        cost_mc = sum(m["total_price"] or 0 for m in mats if m['item_type']=='comprado')
        finished=lambda m: (m['finished_total_weight'] if m['group_name']=='Arame'
                            and m['finished_total_weight'] is not None else m['total_weight'] or 0)
        steel_w = sum(finished(m) for m in mats if m['item_type']!='subconjunto' and m["group_name"] in ("Chapa", "Tubo Quadrado/Retangular", "Tubo Redondo", "Arame"))
        tot_w = sum(finished(m) for m in mats if m['item_type']!='subconjunto')
        p["cost_total"] = round(cost_mp + cost_mc, 2)
        p["missing_prices_count"] = sum(m['item_type']!='subconjunto' and m['unit_price'] is None for m in mats)
        p["unresolved_assemblies_count"] = sum(m['item_type']=='subconjunto' for m in mats)
        p["steel_weight"] = round(steel_w, 3)
        p["total_weight"] = round(tot_w, 3)
        p["items_count"] = len(mats)
    conn.close()
    return projects

@app.post("/api/projects")
def create_project(data: ProjectCreate):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO projects (name, code, client, date, folder_path, notes)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (data.name, data.code, data.client, data.date, data.folder_path, data.notes))
    p_id = cur.lastrowid
    
    # Criar config padrão de markup
    mk = get_default_markup_json()
    cur.execute("""
    INSERT INTO markup_configs (project_id, mo_items, operational_items, taxes_items, margin_mp, margin_mc)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (p_id, json.dumps(mk["mo_items"]), json.dumps(mk["operational_items"]), json.dumps(mk["tax_items"]), mk["margin_mp"], mk["margin_mc"]))
    
    # Criar config padrão de caixa
    cur.execute("""
    INSERT INTO box_configs (project_id, length, width, height, flap_type, sheet_type, quantity)
    VALUES (?, 880.0, 130.0, 350.0, 2, 2, 1.0)
    """, (p_id,))

    conn.commit()
    conn.close()
    return {"id": p_id, "message": "Projeto criado com sucesso"}


@app.get("/api/source-folders/jose-vitor")
def jose_vitor_source_folders():
    """List individual project folders in this historical collection."""
    base=Path(DADOS_DIR)/'JOSÉ VITOR'
    if not base.is_dir(): return []
    folders=[]
    for drawings in base.rglob('PROJETO'):
        if not drawings.is_dir(): continue
        project=drawings.parent
        if not any(p.is_file() and p.suffix.lower()=='.pdf' for p in drawings.rglob('*')):
            continue
        folders.append({'name':project.name,'client':project.parent.name,
                        'path':str(project)})
    return sorted(folders,key=lambda x:(x['client'].casefold(),x['name'].casefold()))

@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    return get_project_full_data(project_id)

@app.post("/api/projects/{project_id}/import-folder")
def import_project_folder(project_id: int, folder_path: str = Form(...),
                          background_tasks: BackgroundTasks = None):
    if not os.path.isdir(folder_path):
        raise HTTPException(status_code=400, detail="Pasta não encontrada no disco.")
    if not any(p.is_file() and p.suffix.lower()=='.pdf' for p in Path(folder_path).rglob('*')):
        raise HTTPException(status_code=400, detail='A pasta não contém PDFs.')
    
    conn = get_connection()
    if not conn.execute('SELECT 1 FROM projects WHERE id=?',(project_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail='Projeto não encontrado.')
    rules = get_rules_dict(conn)
    
    # Import never writes to the source folder.
    pdata = process_complete_project(folder_path, rules)

    # Reimports refresh parser output without discarding edits the user made
    # to the same physical drawing. Keep a history link only when its drawing,
    # source page and assembly path still identify one parsed item uniquely.
    history_rows = [dict(row) for row in conn.execute(
        'SELECT material_id,before_json,after_json FROM material_changes '
        'WHERE project_id=? ORDER BY id', (project_id,)).fetchall()]
    preserved_edits, unpreserved_edits = preserve_manual_values(
        pdata['materials'], history_rows)
    
    cur = conn.cursor()
    cur.execute("""
    UPDATE projects 
    SET folder_path = ?,
        code = COALESCE(NULLIF(?, ''), code),
        nominal_weight_pdf = ?,
        nominal_area_pdf = ?, status = 'PRELIMINAR',
        updated_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (folder_path, pdata.get("code", ""), pdata.get("nominal_weight_pdf", 0.0), pdata.get("nominal_area_pdf", 0.0), project_id))

    # Limpar materiais antigos se houver
    cur.execute("DELETE FROM materials WHERE project_id = ?", (project_id,))
    cur.execute("DELETE FROM pending_decisions WHERE project_id = ?", (project_id,))
    cur.execute("DELETE FROM wire_variants WHERE project_id = ?", (project_id,))

    # Inserir novos materiais
    new_material_ids = {}
    for material_index, m in enumerate(pdata["materials"]):
        if not (m.get('length') or 0):
            m['length']=porta_linear_length_mm(m) or m.get('length',0)
        if (m['group_name']=='Polímero/PSAI' and m['item_type']=='comprado'
                and not (m['unit_area'] or 0) and (m['width'] or 0)>0 and (m['length'] or 0)>0):
            m['unit_area']=m['width']*m['length']/1_000_000
        m['total_weight']=ceil_kg(float(m.get('unit_weight') or 0)*float(m.get('quantity') or 0))
        m['finished_total_weight']=(ceil_kg(float(m['finished_unit_weight'])*float(m.get('quantity') or 0))
                                    if m.get('finished_unit_weight') is not None else None)
        m['total_area']=round(float(m.get('unit_area') or 0)*float(m.get('quantity') or 0),4)
        cur.execute("""
        INSERT INTO materials (
            project_id, item_num, description, group_name, material,
            thickness, radius_diam, width, depth, length,
            drawing_length, wire_allowance_mm, quantity, unit, unit_weight,
            total_weight, finished_unit_weight, finished_total_weight, unit_area, total_area,
            drawing_id, raw_code, finish, printing, unit_price, total_price,
            price_source, source_page, confidence, parent_assembly, mirrored_assembly,
            is_consolidated, is_inferred, pending_issue, observation, item_type
        ) VALUES (
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?
        )
        """, (
            project_id, m["item_num"], m["description"], m["group_name"], m["material"],
            m["thickness"], m["radius_diam"], m["width"], m["depth"], m["length"],
            m.get("drawing_length"), m.get("wire_allowance_mm",0), m["quantity"], m["unit"],
            m["unit_weight"], m["total_weight"], m.get("finished_unit_weight"),
            m.get("finished_total_weight"), m["unit_area"], m["total_area"],
            m["drawing_id"], m["raw_code"], m["finish"], m["printing"], m["unit_price"], m["total_price"],
            m["price_source"], m["source_page"], m["confidence"], m["parent_assembly"], m.get("mirrored_assembly"),
            m["is_consolidated"], m["is_inferred"], m["pending_issue"], m["observation"], m["item_type"]
        ))
        for old_material_id, matched_index in preserved_edits.items():
            if matched_index == material_index:
                new_material_ids[old_material_id] = cur.lastrowid
        
        # Se item tiver pendência ou confiança baixa, registrar decisão pendente
        if m.get("pending_issue") or m.get("confidence", 1.0) < 0.85:
            cur.execute("""
            INSERT INTO pending_decisions (project_id, item_id, title, description, impact_level, proposed_action)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (
                project_id, cur.lastrowid, 
                f"Confirmação: {m['description']}",
                m.get("pending_issue") or f"Confiança de extração {m['confidence']*100:.0f}%.",
                "MEDIO",
                f"Revisar origem {m['source_page']} e completar medidas/peso quando necessário."
            ))

    for issue in pdata.get('pending_decisions', []):
        cur.execute("""INSERT INTO pending_decisions
            (project_id,title,description,impact_level,proposed_action)
            VALUES (?,?,?,?,?)""",(project_id,issue['title'],issue['description'],
                                  issue.get('impact_level','ALTO'),'Revisar arquivo de origem'))
    for old_material_id, new_material_id in new_material_ids.items():
        cur.execute('UPDATE material_changes SET material_id=? WHERE project_id=? AND material_id=?',
                    (new_material_id, project_id, old_material_id))
    for issue in unpreserved_edits:
        cur.execute("""INSERT INTO pending_decisions
            (project_id,title,description,impact_level,proposed_action)
            VALUES (?,?,?,?,?)""",(
                project_id, 'Reaplicar edição manual após reimportação',
                f"A edição manual de '{issue['description']}' não foi aplicada automaticamente "
                f"porque encontrou {issue['match_count']} correspondência(s) na nova leitura. "
                'O histórico original foi mantido; conferir a nova BOM antes de reaplicar.',
                'ALTO', 'Vincular a edição ao item correto e revisar medidas/peso.'))
    insert_wire_variants(conn, project_id, pdata.get('wire_variants', []))
    reprice_project(conn,project_id)

    conn.commit()
    conn.close()
    ai_pages = 0
    if background_tasks is not None:
        ai_pages = enqueue_project(project_id)['pages']
        background_tasks.add_task(start_worker)

    return {"message": f"Importação concluída: {len(pdata['materials'])} itens catalogados. "
                       f"Conferência IA de {ai_pages} página(s) iniciada em segundo plano.",
            "materials_count": len(pdata["materials"]), "ai_pages_queued": ai_pages}

def _check_upload_project(project_id):
    conn=get_connection()
    exists=conn.execute('SELECT 1 FROM projects WHERE id=?',(project_id,)).fetchone()
    conn.close()
    if not exists:
        raise HTTPException(status_code=404,detail='Projeto não encontrado.')


@app.post('/api/projects/{project_id}/upload-files')
async def upload_project_files(project_id: int, files: list[UploadFile] = File(...),
                               paths: list[str] = Form(...),
                               background_tasks: BackgroundTasks = None):
    _check_upload_project(project_id)
    if not files or len(files)!=len(paths) or len(files)>MAX_PDFS:
        raise HTTPException(status_code=400,detail='Selecione até 1000 PDFs com caminhos correspondentes.')
    _, source=new_upload_area(project_id)
    total=0
    for file, relative_path in zip(files,paths):
        if not file.filename or not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400,detail='Envie somente arquivos PDF.')
        target=pdf_target(source,relative_path)
        if target.exists():
            raise HTTPException(status_code=400,detail='A pasta contém PDFs com o mesmo caminho.')
        total+=await save_upload(file,target,MAX_BYTES-total)
    result=import_project_folder(project_id,folder_path=str(source),background_tasks=background_tasks)
    result['message']=f'{len(files)} PDF(s) enviados. '+result['message']
    return result


@app.post('/api/projects/{project_id}/upload-archive')
@app.post('/api/projects/{project_id}/upload-zip')
async def upload_project_archive(project_id: int, file: UploadFile = File(...),
                                 background_tasks: BackgroundTasks = None):
    _check_upload_project(project_id)
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.zip','.rar'):
        raise HTTPException(status_code=400,detail='Envie um arquivo ZIP ou RAR.')
    root,source=new_upload_area(project_id)
    archive=root/('import'+suffix)
    size=0
    try:
        with archive.open('xb') as output:
            while chunk := await file.read(1024*1024):
                size+=len(chunk)
                if size>MAX_BYTES:
                    raise HTTPException(status_code=413,detail='Arquivo compactado excede 500 MB.')
                output.write(chunk)
    except Exception:
        archive.unlink(missing_ok=True)
        raise
    if not size:
        raise HTTPException(status_code=400,detail='Arquivo compactado vazio.')
    count=(extract_zip_pdfs(archive,source) if suffix=='.zip'
           else extract_rar_pdfs(archive,source))
    if not count:
        raise HTTPException(status_code=400,detail='Nenhum PDF encontrado no arquivo compactado.')
    result=import_project_folder(project_id,folder_path=str(source),background_tasks=background_tasks)
    result['message']=f'{count} PDF(s) extraídos do {suffix.upper()}. '+result['message']
    return result

@app.post("/api/projects/{project_id}/wire-variants/{variant_id}/material")
def select_wire_variant(project_id: int, variant_id: int, data: WireVariantSelection):
    if not 0 < data.quantity <= 100000:
        raise HTTPException(status_code=400, detail='Informe a quantidade positiva da variante.')
    conn = get_connection()
    variant = conn.execute('''SELECT * FROM wire_variants
        WHERE id=? AND project_id=?''', (variant_id, project_id)).fetchone()
    if not variant:
        conn.close()
        raise HTTPException(status_code=404, detail='Variante não encontrada.')
    variant = dict(variant)
    if variant['material_id'] is not None:
        conn.close()
        raise HTTPException(status_code=409, detail='Variante já adicionada ao orçamento; edite a linha existente.')
    conn.close()
    result = create_material(project_id, MaterialCreate(
        description=f"{variant['description']} · {variant['nominal']} · cód. {variant['code']}",
        group_name='Arame', item_type='materia_prima', material=variant['material'],
        quantity=data.quantity, unit='un', length=variant['cut_length'],
        radius_diam=variant['diameter'],
        parent_assembly=variant['description'],
        source_page=variant['source_page'], drawing_id=variant['description'],
        raw_code=variant['code'],
        confidence=0.95 if variant['ai_agreement_count'] else 0.8,
        observation=(f"Variante do desenho: medida A={variant['measure_a']:g} mm; "
                     f"comprimento desenvolvido={variant['cut_length']:g} mm. "
                     'A e 35h descrevem a dobra, não o corte.'),
        pending_issue=''))
    conn = get_connection()
    conn.execute('UPDATE wire_variants SET quantity=?,material_id=? WHERE id=? AND project_id=?',
                 (data.quantity, result['id'], variant_id, project_id))
    conn.commit()
    conn.close()
    return result

@app.post("/api/projects/{project_id}/ai-discovered-items/{candidate_id}/material")
def select_ai_discovered_item(project_id: int, candidate_id: int,
                              data: WireVariantSelection):
    """A person supplies the total project quantity before an AI-only part is costed."""
    if not 0 < data.quantity <= 100000:
        raise HTTPException(status_code=400, detail='Informe a quantidade total positiva da peça.')
    conn = get_connection()
    try:
        row = conn.execute('''SELECT * FROM ai_discovered_items
            WHERE id=? AND project_id=?''', (candidate_id, project_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='Peça encontrada pela IA não existe.')
        candidate = dict(row)
        if candidate['material_id'] is not None:
            raise HTTPException(status_code=409, detail='Peça já adicionada ao orçamento.')
        if not candidate['ready']:
            raise HTTPException(status_code=409, detail='Cotas ou corte ainda precisam de conferência.')
        from ai_pdf_review import cross_page_matches
        from ai_apply_dimensions import _same_pdf
        same_pdf = [dict(saved) for saved in conn.execute('''SELECT * FROM materials
            WHERE project_id=? AND item_type!=?''', (project_id, 'subconjunto'))
            if _same_pdf(saved['source_page'], candidate['source_page'].split('#page=', 1)[0])]
        ai_shape = {'description': candidate['description'],
                    'item_type': candidate['item_type'],
                    'material': candidate['material'],
                    **json.loads(candidate['dimensions_json'])}
        if cross_page_matches(ai_shape, same_pdf):
            raise HTTPException(status_code=409, detail='Já existe peça correspondente neste PDF.')
    finally:
        conn.close()
    from ai_apply_dimensions import _backup_database

    _backup_database(project_id)
    dimensions = json.loads(candidate['dimensions_json'])
    result = create_material(project_id, MaterialCreate(
        description=candidate['description'], group_name=candidate['group_name'],
        item_type=candidate['item_type'], material=candidate['material'],
        quantity=data.quantity, unit='un', source_page=candidate['source_page'],
        drawing_id=candidate['description'], confidence=.7,
        observation=('Peça encontrada apenas na revisão da IA. '
                     f"Evidência: {candidate['evidence'][:300]}"),
        pending_issue='Conferir vínculo ao conjunto e peso da peça encontrada apenas pela IA.',
        **dimensions))
    conn = get_connection()
    try:
        conn.execute('''UPDATE ai_discovered_items SET material_id=?
            WHERE id=? AND project_id=? AND material_id IS NULL''',
            (result['id'], candidate_id, project_id))
        conn.commit()
    finally:
        conn.close()
    return result


@app.post("/api/projects/{project_id}/materials")
def create_material(project_id: int, data: MaterialCreate):
    if not data.description.strip() or data.quantity <= 0 or data.unit not in ('un','kg','m','m2'):
        raise HTTPException(status_code=400,detail='Informe descrição, quantidade positiva e unidade válida.')
    if data.unit_price is not None and data.unit_price <= 0:
        raise HTTPException(status_code=400,detail='Preço manual deve ser positivo.')
    if any(v is not None and v < 0 for v in (data.length,data.width,data.depth,data.thickness,data.radius_diam,data.unit_weight)):
        raise HTTPException(status_code=400,detail='Dimensões e peso não podem ser negativos.')
    conn=get_connection()
    if not conn.execute('SELECT 1 FROM projects WHERE id=?',(project_id,)).fetchone():
        conn.close()
        raise HTTPException(status_code=404,detail='Projeto não encontrado.')
    item_num=conn.execute('SELECT COALESCE(MAX(item_num),0)+1 FROM materials WHERE project_id=?',(project_id,)).fetchone()[0]
    cur=conn.execute('''INSERT INTO materials
        (project_id,item_num,description,group_name,item_type,quantity,unit,
         source_page,drawing_id,raw_code,confidence)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (project_id,item_num,data.description.strip(),data.group_name,
         data.item_type or infer_item_type(data.description,data.group_name),data.quantity,data.unit,
         data.source_page or 'Entrada manual',data.drawing_id or '',data.raw_code or '',
         data.confidence if data.confidence is not None else 1.0))
    item_id=cur.lastrowid
    conn.commit(); conn.close()
    try:
        result=update_material(project_id,item_id,MaterialUpdate(**data.model_dump(exclude_none=True)))
    except Exception:
        conn=get_connection()
        conn.execute('DELETE FROM materials WHERE id=?',(item_id,))
        conn.commit();conn.close()
        raise
    return {'id':item_id,**result}

@app.put("/api/projects/{project_id}/materials/{item_id}")
def update_material(project_id: int, item_id: int, data: MaterialUpdate):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM materials WHERE id = ? AND project_id = ?", (item_id, project_id))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Material não encontrado")
    
    m = dict(row)
    before = dict(m)
    
    # Atualizar campos recebidos
    if data.description is not None: m["description"] = data.description
    if data.unit is not None: m["unit"] = data.unit
    if data.group_name is not None: m["group_name"] = data.group_name
    if data.item_type is not None:
        if data.item_type not in VALID_TYPES:
            conn.close()
            raise HTTPException(status_code=400,detail='Tipo de item inválido.')
        m['item_type']=data.item_type
    if data.parent_assembly is not None: m['parent_assembly']=data.parent_assembly.strip()
    if data.material is not None: m["material"] = data.material
    if data.thickness is not None: m["thickness"] = data.thickness
    if data.radius_diam is not None: m["radius_diam"] = data.radius_diam
    if data.width is not None: m["width"] = data.width
    if data.depth is not None: m["depth"] = data.depth
    if data.length is not None: m["length"] = data.length
    if data.quantity is not None: m["quantity"] = data.quantity
    if data.printing is not None: m["printing"] = data.printing
    if data.observation is not None: m["observation"] = data.observation
    if data.pending_issue is not None: m["pending_issue"] = data.pending_issue

    if not (m.get('length') or 0):
        m['length']=porta_linear_length_mm(m) or 0

    profile_error=synchronize_tube_profile(m,before)
    if profile_error:
        conn.close()
        raise HTTPException(status_code=400,detail=profile_error)

    # Recálculo Físico Automático Transparente
    grp = m["group_name"]
    qty = m["quantity"]
    thk = m["thickness"]
    diam = m["radius_diam"]
    w = m["width"]
    l = m["length"]

    physical_change = any(name in data.model_fields_set and m[name] != before[name] for name in
                          ('group_name','material','thickness','radius_diam','width','depth','length'))
    if m['item_type']=='subconjunto':
        m['unit_weight']=0.0
        m['unit_area']=0.0
    elif grp == "Arame" and diam>0 and l>0:
        if m.get('wire_allowance_mm'):
            if physical_change:
                nominal=max(0.0,l-m['wire_allowance_mm'])
                rate=mass_per_mm(diam)
                m['drawing_length']=nominal
                m['finished_unit_weight']=round(nominal*rate,6)
                m['unit_weight']=round(l*rate,6)
                m['unit_area']=round(3.141592653589793*diam*l/1_000_000,6)
        elif physical_change:
            apply_wire_allowance(m)
    elif physical_change and grp == "Chapa" and l>0 and w>0 and thk>0:
        res = calc_sheet(l, w, thk, 1.0, m["material"])
        m["unit_area"] = res["area"]
        m["unit_weight"] = res["weight"]
    elif physical_change and grp == "Tubo Quadrado/Retangular" and w>0 and m['depth']>0 and thk>0 and l>0:
        res = calc_tube_rect(w, m["depth"], thk, l, 1.0)
        m["unit_area"] = res["area"]
        m["unit_weight"] = res["weight"]
    elif physical_change and grp == "Tubo Redondo" and diam>0 and thk>0 and l>0:
        res = calc_tube_round(diam, thk, l, 1.0)
        m["unit_area"] = res["area"]
        m["unit_weight"] = res["weight"]
    elif physical_change and grp == "Polímero/PSAI" and l>0 and w>0 and thk>0:
        res = calc_sheet(l, w, thk, 1.0, m['material'] or 'PSAI')
        # Preserve the drawing area used by the established CONTROLV quote.
        # Geometry can supply an area only when the drawing has none.
        if not m['unit_area']:
            m["unit_area"] = res["area"]
        m["unit_weight"] = res["weight"]

    manual_weight_changed=(data.unit_weight is not None and
                           abs(data.unit_weight-float(before['unit_weight'] or 0))>1e-9)
    # Se usuário alterou o peso unitário manualmente:
    if m['item_type']!='subconjunto' and manual_weight_changed:
        m["unit_weight"] = data.unit_weight
        if grp == 'Arame' and m.get('wire_allowance_mm'):
            m['finished_unit_weight']=round(max(0.0,data.unit_weight-
                m['wire_allowance_mm']*mass_per_mm(diam)),6)
        
    if qty <= 0 or m['unit_weight'] < 0 or any((m[k] or 0) < 0 for k in ('length','width','depth','thickness','radius_diam')):
        conn.close()
        raise HTTPException(status_code=400,detail='Quantidade e dimensões devem ser positivas; peso não pode ser negativo.')
    validation=None
    if m['item_type']!='subconjunto':
        geometry_weight=calculated_weight(m)
        must_check=(physical_change or manual_weight_changed or
                    geometry_weight>float(m['unit_weight'] or 0)+1e-9)
        if must_check:
            drawing=linked_drawing(conn,m)
            pdf_weight=float(drawing.get('unit_weight') or 0) if drawing else 0.0
            entered=float(data.unit_weight or 0) if manual_weight_changed else None
            m['observation']=strip_weight_note(m.get('observation'))
            if grp=='Arame' and m.get('wire_allowance_mm'):
                nominal=float(m.get('drawing_length') or max(0,l-m['wire_allowance_mm']))
                finished_item={**m,'length':nominal,
                               'unit_weight':pdf_weight or float(before.get('finished_unit_weight') or 0)}
                if calculated_weight(finished_item)>0:
                    reconcile_item_weight(finished_item,pdf_weight=pdf_weight)
                    m['observation']=finished_item['observation']
                finished=ceil_kg(max(float(finished_item['unit_weight'] or 0),
                                     calculated_weight(finished_item)))
                m['finished_unit_weight']=finished
                extra=max(0,geometry_weight-calculated_weight(finished_item))
                m['unit_weight']=ceil_kg(max(entered or 0,geometry_weight,finished+extra))
            else:
                # The form submits the old weight even when only dimensions
                # changed. Use the actual drawing weight as the reference.
                reference=pdf_weight or (float(before['unit_weight'] or 0)
                                         if drawing is None else 0)
                m['unit_weight']=max(entered or 0,reference)
                if geometry_weight>0:
                    reconcile_item_weight(m,pdf_weight=pdf_weight)
                else:
                    m['unit_weight']=ceil_kg(m['unit_weight'])
            difference=drawing_difference(m,drawing)
            if difference:
                m['observation']=' '.join(x for x in (
                    m.get('observation') or '',
                    f'Medidas manuais diferentes do PDF: {difference}.') if x)
            adjusted=(entered is not None and m['unit_weight']>entered+1e-9)
            validation=dict(pdf_weight=pdf_weight,calculated_weight=geometry_weight,
                            adopted_weight=m['unit_weight'],adjusted=adjusted,
                            drawing_difference=difference,source_linked=bool(drawing),
                            show=bool(physical_change or manual_weight_changed))
        if grp in ('Tubo Quadrado/Retangular','Tubo Redondo') and calculated_weight(m)<=0:
            issue='Perfil ou comprimento do tubo incompleto; peso sem validação geométrica.'
            if issue not in (m.get('pending_issue') or ''):
                m['pending_issue']=' '.join(x for x in (m.get('pending_issue') or '',issue) if x)
        else:
            m['pending_issue']=(m.get('pending_issue') or '').replace(
                'Perfil ou comprimento do tubo incompleto; peso sem validação geométrica.','').strip()
    m["total_weight"] = ceil_kg(m["unit_weight"] * qty)
    m["total_area"] = round(m["unit_area"] * qty, 4)
    if grp == 'Arame' and m.get('wire_allowance_mm'):
        m['finished_total_weight']=ceil_kg((m.get('finished_unit_weight') or 0)*qty)

    # Se alterou preço unitário
    if m['item_type']=='subconjunto':
        m['unit_price'],m['price_source']=None,''
    elif 'unit_price' in data.model_fields_set:
        if data.unit_price is not None and data.unit_price <= 0:
            raise HTTPException(status_code=400,detail='Preço manual deve ser positivo; deixe em branco quando não houver preço aprovado.')
        if data.unit_price is None:
            m['unit_price'],m['price_source']=price_item(m,get_rules_dict(conn),conn)
        else:
            m["unit_price"] = data.unit_price
            m["price_source"] = "Ajuste manual aprovado"
    elif not (m['price_source'] or '').startswith('Ajuste manual aprovado'):
        m['unit_price'],m['price_source']=price_item(m,get_rules_dict(conn),conn)

    m["total_price"] = round(m["unit_price"] * qty, 2) if m['unit_price'] is not None else None

    descendant_changes = []
    if before['item_type'] == 'subconjunto':
        current_materials = [dict(record) for record in cur.execute(
            'SELECT * FROM materials WHERE project_id = ?', (project_id,)).fetchall()]
        has_children = has_detail_children(before, current_materials)
        if has_children and (m['description'] != before['description'] or
                             m['parent_assembly'] != before['parent_assembly'] or
                             m['item_type'] != 'subconjunto'):
            conn.close()
            raise HTTPException(status_code=400, detail=(
                'Este subconjunto já tem peças vinculadas. Altere a quantidade; '
                'para mudar o nome ou a posição, revise antes a estrutura das peças.'))
        if has_children and qty != before['quantity']:
            descendant_changes = scaled_descendants(current_materials, before, qty)

    cur.execute("""
    UPDATE materials SET
        description = ?, group_name = ?, material = ?, unit = ?, thickness = ?,
        radius_diam = ?, width = ?, depth = ?, length = ?, drawing_length = ?,
        wire_allowance_mm = ?, quantity = ?, unit_weight = ?, total_weight = ?,
        finished_unit_weight = ?, finished_total_weight = ?, unit_area = ?, total_area = ?,
        unit_price = ?, total_price = ?, price_source = ?, printing = ?,
        observation = ?, pending_issue = ?, item_type = ?, parent_assembly = ?
    WHERE id = ? AND project_id = ?
    """, (
        m["description"], m["group_name"], m["material"], m["unit"], m["thickness"],
        m["radius_diam"], m["width"], m["depth"], m["length"], m.get('drawing_length'),
        m.get('wire_allowance_mm'), m["quantity"], m["unit_weight"], m["total_weight"],
        m.get('finished_unit_weight'), m.get('finished_total_weight'),m["unit_area"], m["total_area"],
        m["unit_price"], m["total_price"], m["price_source"], m["printing"],
        m["observation"], m["pending_issue"], m['item_type'], m['parent_assembly'], item_id, project_id
    ))
    cur.execute('''UPDATE wire_variants SET quantity=?
        WHERE project_id=? AND material_id=?''', (qty, project_id, item_id))

    for child_before, child_after in descendant_changes:
        cur.execute('''UPDATE materials SET quantity=?, total_weight=?, finished_total_weight=?,
                       total_area=?, total_price=? WHERE id=? AND project_id=?''',
                    (child_after['quantity'], child_after['total_weight'],
                     child_after['finished_total_weight'], child_after['total_area'],
                     child_after['total_price'], child_after['id'], project_id))
        cur.execute('''INSERT INTO material_changes
                       (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
                    (project_id, child_after['id'], json.dumps(child_before, ensure_ascii=False),
                     json.dumps(child_after, ensure_ascii=False)))

    # Atualizar data do projeto
    cur.execute("UPDATE projects SET status='PRELIMINAR', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
    cur.execute("INSERT INTO material_changes (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)",
                (project_id,item_id,json.dumps(before,ensure_ascii=False),json.dumps(m,ensure_ascii=False)))

    conn.commit()
    conn.close()

    return {"message": "Material recalculado e salvo com sucesso", "material": m,
            "validation": validation, "descendants_updated": len(descendant_changes)}

@app.delete("/api/projects/{project_id}/materials/{item_id}")
def delete_material(project_id: int, item_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''UPDATE wire_variants SET quantity=NULL,material_id=NULL
        WHERE project_id=? AND material_id=?''', (project_id, item_id))
    cur.execute("DELETE FROM materials WHERE id = ? AND project_id = ?", (item_id, project_id))
    cur.execute("UPDATE projects SET status='PRELIMINAR', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()
    return {"message": "Item removido com sucesso"}

@app.put("/api/projects/{project_id}/markup")
def update_markup(project_id: int, data: MarkupUpdate):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM markup_configs WHERE project_id = ?", (project_id,))
    row = cur.fetchone()
    
    mo_json = json.dumps(data.mo_items) if data.mo_items is not None else row["mo_items"]
    op_json = json.dumps(data.operational_items) if data.operational_items is not None else row["operational_items"]
    tax_json = json.dumps(data.tax_items) if data.tax_items is not None else row["taxes_items"]
    m_mp = data.margin_mp if data.margin_mp is not None else row["margin_mp"]
    m_mc = data.margin_mc if data.margin_mc is not None else row["margin_mc"]
    try:
        calculate_markup(1,1,1,{'mo_items':json.loads(mo_json),'operational_items':json.loads(op_json),
                                  'tax_items':json.loads(tax_json),'margin_mp':m_mp,'margin_mc':m_mc})
    except ValueError as exc:
        conn.close()
        raise HTTPException(status_code=400,detail=str(exc))

    cur.execute("""
    UPDATE markup_configs
    SET mo_items = ?, operational_items = ?, taxes_items = ?, margin_mp = ?, margin_mc = ?, approved = 0
    WHERE project_id = ?
    """, (mo_json, op_json, tax_json, m_mp, m_mc, project_id))

    cur.execute("UPDATE projects SET status='PRELIMINAR', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()

    return {"message": "Parâmetros de markup atualizados"}

@app.put("/api/projects/{project_id}/box")
def update_box_config(project_id: int, data: BoxConfigUpdate):
    if min(data.length,data.width,data.height,data.quantity) <= 0 or data.flap_type not in (1,2) or data.sheet_type not in (1,2,3):
        raise HTTPException(status_code=400,detail='Dimensões, quantidade ou tipo de caixa inválidos.')
    conn = get_connection()
    rules = get_rules_dict(conn)
    box_calc = calc_cardboard_box(data.length, data.width, data.height, data.flap_type, data.sheet_type, rules, data.quantity)
    box_rule={1:'cx_onda_baixa',2:'cx_folha_simples',3:'cx_folha_dupla'}[data.sheet_type]
    if box_rule not in rules:
        box_calc['sqm_rate']=None
        box_calc['unit_cost']=None
        box_calc['total_cost']=None
    
    cur = conn.cursor()
    cur.execute("""
    UPDATE box_configs SET
        length = ?, width = ?, height = ?, flap_type = ?, sheet_type = ?,
        calculated_area = ?, calculated_cost = ?, quantity = ?
    WHERE project_id = ?
    """, (data.length, data.width, data.height, data.flap_type, data.sheet_type, box_calc["area_m2"], box_calc["total_cost"], data.quantity, project_id))

    # Atualizar linha de embalagem em materials se existir
    cur.execute("""
    UPDATE materials SET
        length = ?, width = ?, depth = ?,
        unit_area = ?, total_area = ?,
        unit_price = ?, total_price = ?,
        price_source = ?
    WHERE project_id = ? AND group_name = 'Embalagem'
    """, (data.length, data.width, data.height, box_calc["area_m2"], box_calc["area_m2"]*data.quantity, box_calc["unit_cost"], box_calc["total_cost"],
          'Regra aprovada: '+box_rule if box_rule in rules else '', project_id))
    cur.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",(project_id,))

    conn.commit()
    conn.close()

    return {"message": "Configuração da caixa de embalagem atualizada", "box_calc": box_calc}

@app.post("/api/projects/{project_id}/pending/{pend_id}/resolve")
def resolve_pending(project_id: int, pend_id: int, status: str = Form(...)):
    if status.upper() not in ('APROVADO','REJEITADO'):
        raise HTTPException(status_code=400,detail='Status inválido.')
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE pending_decisions 
    SET status = ?, resolved_at = CURRENT_TIMESTAMP 
    WHERE id = ? AND project_id = ?
    """, (status.upper(), pend_id, project_id))
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404,detail='Pendência não encontrada.')

    # Resolving a question alone never authorizes final issue.
    cur.execute("SELECT COUNT(*) as cnt FROM pending_decisions WHERE project_id = ? AND status = 'PENDENTE'", (project_id,))
    remaining = cur.fetchone()["cnt"]
    cur.execute("UPDATE projects SET status = 'PRELIMINAR' WHERE id = ?",(project_id,))

    conn.commit()
    conn.close()
    return {"message": f"Pendência marcada como {status}", "remaining_pending": remaining}

# --- EXPORTAÇÕES ---
@app.get("/api/projects/{project_id}/export/modelos/{kind}")
def get_template_export(project_id: int, kind: str):
    if kind not in ("calculo", "custos", "planilhas"):
        raise HTTPException(status_code=404, detail="Formato de exportação não encontrado")
    try:
        path = export_template_reports(get_project_full_data(project_id), project_id, kind)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    media_type = {".zip": "application/zip", ".xls": XLS_MIME, ".xlsx": XLSX_MIME}[path.suffix.lower()]
    return FileResponse(path, media_type=media_type, filename=path.name)

@app.get("/api/projects/{project_id}/export/pdf")
def get_pdf_export(project_id: int):
    full_data = get_project_full_data(project_id)
    pdf_path = export_budget_pdf(
        full_data["project"],
        full_data["materials"],
        full_data["markup_result"],
        full_data["weight_result"],
        pending_decisions=full_data["pending_decisions"]
    )
    return FileResponse(pdf_path, media_type="application/pdf", filename=os.path.basename(pdf_path))

@app.get("/api/projects/{project_id}/export/xlsx")
def get_xlsx_export(project_id: int):
    full_data = get_project_full_data(project_id)
    xlsx_path = export_budget_xlsx(
        full_data["project"],
        full_data["materials"],
        full_data["markup_result"],
        full_data["weight_result"],
        pending_decisions=full_data["pending_decisions"]
    )
    return FileResponse(xlsx_path, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=os.path.basename(xlsx_path))

@app.get("/api/projects/{project_id}/export/csv")
def get_csv_export(project_id: int):
    full_data = get_project_full_data(project_id)
    csv_path = export_budget_csv(full_data["materials"])
    return FileResponse(csv_path, media_type="text/csv", filename=os.path.basename(csv_path))

@app.get("/api/rules")
def get_rules():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM price_rules ORDER BY category, name")
    rules = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rules

@app.put("/api/rules/{rule_key}")
def update_rule(rule_key: str, data: RuleUpdate):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
    UPDATE price_rules 
    SET value = ?, is_active = ?, approved = ?, notes = COALESCE(?, notes),
        effective_date = CURRENT_DATE, source='Ajuste manual no app'
    WHERE rule_key = ?
    """, (data.value, data.is_active, data.approved, data.notes, rule_key))
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=404,detail='Regra não encontrada')
    for row in cur.execute('SELECT id FROM projects').fetchall():
        reprice_project(conn,row['id'])
    cur.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP")
    conn.commit()
    conn.close()
    return {"message": "Regra de preço atualizada"}

@app.post('/api/seed-historical')
def seed_historical_projects(background_tasks: BackgroundTasks = None):
    """Import three actual folders, with no fixed BOM or historic numbers."""
    import glob
    folders=[glob.glob(os.path.join(DADOS_DIR,'PA00000250*')),
             glob.glob(os.path.join(DADOS_DIR,'ILHA CASH RECKITT')),
             glob.glob(os.path.join(DADOS_DIR,'E03704167*','PG - OP01*'))]
    imported=[]
    for options in folders:
        if not options: continue
        path=options[0]
        name=os.path.basename(path)+' (leitura real)'
        conn=get_connection()
        row=conn.execute('SELECT id FROM projects WHERE name=?',(name,)).fetchone()
        conn.close()
        if row: continue
        pid=create_project(ProjectCreate(name=name,folder_path=path))['id']
        result=import_project_folder(pid,path,background_tasks=background_tasks)
        imported.append({'id':pid,'name':name,'items':result['materials_count']})
    return {'imported':imported}


@app.get('/api/projects/{project_id}/source')
def get_source(project_id:int,path:str):
    conn=get_connection()
    row=conn.execute('SELECT folder_path FROM projects WHERE id=?',(project_id,)).fetchone()
    conn.close()
    if not row or not row['folder_path']:
        raise HTTPException(status_code=404,detail='Projeto sem pasta de origem')
    root=os.path.realpath(row['folder_path'])
    target=os.path.realpath(os.path.join(root,path))
    if os.path.commonpath([root,target])!=root or not os.path.isfile(target) or not target.lower().endswith('.pdf'):
        raise HTTPException(status_code=400,detail='PDF de origem inválido')
    return FileResponse(target,media_type='application/pdf')


@app.get('/api/projects/{project_id}/pdfs')
def get_project_pdfs(project_id:int):
    conn=get_connection()
    project=conn.execute('SELECT folder_path FROM projects WHERE id=?',(project_id,)).fetchone()
    if project is None:
        conn.close()
        raise HTTPException(status_code=404,detail='Projeto não encontrado')
    materials=[dict(row) for row in conn.execute(
        'SELECT source_page,item_type,group_name,length,width,depth,thickness,radius_diam,pending_issue '
        'FROM materials WHERE project_id=?',(project_id,))]
    conn.close()
    return list_project_pdfs(project['folder_path'] or '',materials)


@app.get('/api/ai-pdf-review/status')
def ai_pdf_review_status():
    return {'configured': bool(configured_key()), 'model': AUTO_MODEL,
            'models': [{'id': name, **details} for name, details in MODEL_OPTIONS.items()],
            'mode': 'automatic_all_pages', 'auto_models': list(AUTO_MODELS),
            'automatic_changes': True}


@app.get('/api/projects/{project_id}/ai-review-jobs')
def get_ai_review_jobs(project_id: int):
    conn = get_connection()
    try:
        if not conn.execute('SELECT 1 FROM projects WHERE id=?', (project_id,)).fetchone():
            raise HTTPException(status_code=404, detail='Projeto não encontrado')
    finally:
        conn.close()
    return {'configured': bool(configured_key()),
            'paused_until_by_model': {model: pause_until(model) for model in MODEL_OPTIONS},
            'jobs': job_status(project_id)}


@app.get('/api/projects/{project_id}/ai-pending-dimensions')
def get_ai_pending_dimensions(project_id: int):
    try:
        return preview_pending_ai_dimensions(project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get('/api/projects/{project_id}/quote-views')
def get_quote_views(project_id: int):
    try:
        return build_quote_views(project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post('/api/projects/{project_id}/ai-pending-dimensions')
def import_ai_pending_dimensions(project_id: int):
    try:
        return apply_pending_ai_dimensions(project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.post('/api/projects/{project_id}/ai-review-pdf')
def review_all_pdf_pages(project_id: int, request: AiPdfReviewAllRequest):
    try:
        chosen = AUTO_MODEL if request.model == 'auto' else request.model
        count = enqueue_pdf(project_id, request.path, chosen, request.force)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    start_worker()
    return {'queued_pages': count, 'configured': bool(configured_key())}


@app.get('/api/projects/{project_id}/ai-review-pdf')
def get_all_pdf_reviews(project_id: int, path: str, model: str = AUTO_MODEL):
    try:
        if model != 'auto':
            validate_model(model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    allowed = AUTO_MODELS if model == 'auto' else (model,)
    matching = [job for job in job_status(project_id)
                if job['path'].casefold() == path.casefold() and job['model'] in allowed]
    if model == 'auto':
        by_page = {}
        for job in matching:
            by_page.setdefault(job['page'], []).append(job)
        matching = []
        for page_jobs in by_page.values():
            finished = [job for job in page_jobs if job['state'] == 'done']
            if finished:
                matching.append(min(finished, key=lambda job: AUTO_MODELS.index(job['model'])))
            else:
                matching.append(max(page_jobs, key=lambda job: AUTO_MODELS.index(job['model'])))
        matching.sort(key=lambda job: job['page'])
    pages = []
    for job in matching:
        pdf_path, items, sibling_items = _review_project_source(
            project_id, job['path'], job['page'])
        review = (load_review(project_id, job['path'], job['page'], pdf_path, job['model'])
                  if job['state'] == 'done' else None)
        pages.append({'page': job['page'], 'model': job['model'],
                      'state': job['state'], 'error': job['error'],
                      'next_attempt_at': job['next_attempt_at'],
                      'result': ({'available': True, 'review': review,
                                  **compare_review(review, items, sibling_items)} if review else None)})
    return {'path': path, 'model': model, 'pages': pages}


def _review_project_source(project_id, relative_path, page):
    conn = get_connection()
    try:
        project = conn.execute('SELECT folder_path FROM projects WHERE id=?', (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail='Projeto não encontrado')
        try:
            pdf_path = resolve_pdf(project['folder_path'] or '', relative_path)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        normalized = relative_path.replace('\\', '/')
        same_pdf = [dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=?', (project_id,))
            if (row['source_page'] or '').replace('\\', '/').split('#page=', 1)[0].casefold()
            == normalized.casefold()]
        items = [item for item in same_pdf
                 if '#page=' not in (item['source_page'] or '') or
                 item['source_page'].rsplit('#page=', 1)[1] == str(page)]
        siblings = [item for item in same_pdf
                    if item not in items and item['item_type'] != 'subconjunto']
        return pdf_path, items, siblings
    finally:
        conn.close()


@app.get('/api/projects/{project_id}/ai-review')
def get_ai_pdf_review(project_id: int, path: str, page: int = 1, model: str = MODEL):
    try:
        validate_model(model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    pdf_path, items, sibling_items = _review_project_source(project_id, path, page)
    review = load_review(project_id, path, page, pdf_path, model)
    if review is None:
        return {'available': False}
    return {'available': True, 'review': review,
            **compare_review(review, items, sibling_items)}


@app.post('/api/projects/{project_id}/ai-review')
def run_ai_pdf_review(project_id: int, request: AiPdfReviewRequest):
    try:
        validate_model(request.model)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    pdf_path, items, sibling_items = _review_project_source(
        project_id, request.path, request.page)
    review = None if request.force else load_review(project_id, request.path, request.page,
                                                    pdf_path, request.model)
    if review is None:
        key = configured_key()
        if not key:
            raise HTTPException(status_code=503, detail='Configure GEMINI_API_KEY ou data/private/google_api_key.txt no servidor.')
        try:
            pdf_bytes, page_count = page_payload(pdf_path, request.page)
            result = request_google(pdf_bytes, key, model=request.model)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        review = save_review(project_id, request.path, request.page, pdf_path, result,
                             request.model)
        review['page_count'] = page_count
    applied = apply_review(project_id, request.path, request.page,
                           review['result'], request.model)
    if applied:
        _, items, sibling_items = _review_project_source(
            project_id, request.path, request.page)
    return {'available': True, 'review': review, 'dimensions_applied': applied,
            **compare_review(review, items, sibling_items)}


@app.post('/api/projects/{project_id}/markup/approve')
def approve_markup(project_id:int):
    conn=get_connection()
    updated=conn.execute('UPDATE markup_configs SET approved=1 WHERE project_id=?',(project_id,)).rowcount
    conn.commit(); conn.close()
    if not updated: raise HTTPException(status_code=404,detail='Projeto não encontrado')
    return {'approved':True}


@app.get('/api/catalog')
def list_catalog(q:str='',limit:int=50):
    conn=get_connection()
    rows=conn.execute('SELECT * FROM catalog_prices WHERE normalized LIKE ? ORDER BY approved DESC,id LIMIT ?',
                      ('%'+__import__('pricing').norm(q)+'%',min(max(limit,1),100))).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post('/api/catalog/{catalog_id}/approve')
def approve_catalog(catalog_id:int):
    conn=get_connection()
    count=conn.execute('UPDATE catalog_prices SET approved=1 WHERE id=?',(catalog_id,)).rowcount
    if not count:
        conn.close(); raise HTTPException(status_code=404,detail='Preço não encontrado')
    for row in conn.execute('SELECT id FROM projects').fetchall():
        reprice_project(conn,row['id'])
    conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP")
    conn.commit(); conn.close()
    return {'approved':True}


@app.get('/api/projects/{project_id}/versions')
def list_versions(project_id:int):
    conn=get_connection()
    rows=conn.execute('SELECT id,version_num,name,status,created_at FROM budget_versions WHERE project_id=? ORDER BY version_num DESC',
                      (project_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.post('/api/projects/{project_id}/versions')
def create_version(project_id:int,data:VersionCreate):
    full=get_project_full_data(project_id)
    if data.final and not full['can_finalize']:
        reasons=[]
        if full['missing_price_ids']: reasons.append(f'{len(full["missing_price_ids"])} itens sem preço')
        if full['missing_unit_ids']: reasons.append(f'{len(full["missing_unit_ids"])} itens sem unidade')
        if full['missing_weight_ids']: reasons.append(f'{len(full["missing_weight_ids"])} itens sem peso')
        if any(p['status']=='PENDENTE' for p in full['pending_decisions']): reasons.append('pendências abertas')
        if not full['materials']: reasons.append('lista vazia')
        if full['weight_result']['status_pdf_compare']=='DIVERGENCIA': reasons.append('peso divergente do PDF')
        raise HTTPException(status_code=409,detail='Versão final bloqueada: '+', '.join(reasons))
    if data.final_price is not None and data.final_price<=0:
        raise HTTPException(status_code=400,detail='Preço final deve ser positivo')
    conn=get_connection()
    next_num=conn.execute('SELECT COALESCE(MAX(version_num),0)+1 FROM budget_versions WHERE project_id=?',
                          (project_id,)).fetchone()[0]
    rules=[dict(row) for row in conn.execute('SELECT * FROM price_rules WHERE approved=1')]
    catalog=[dict(row) for row in conn.execute('SELECT * FROM catalog_prices WHERE approved=1')]
    final_price=data.final_price if data.final else None
    summary={'project':full['project'],'materials':full['materials'],
             'markup_config':full['markup_config'],'markup_result':full['markup_result'],
             'weight_result':full['weight_result'],'pending_decisions':full['pending_decisions'],
             'final_price':final_price}
    status='FINAL' if data.final else 'PRELIMINAR'
    summary['project']={**summary['project'],'status':status,'final_price':final_price}
    conn.execute('''INSERT INTO budget_versions
        (project_id,version_num,name,status,summary_json,prices_snapshot_json,rules_snapshot_json)
        VALUES (?,?,?,?,?,?,?)''',(project_id,next_num,data.name or f'Versão {next_num}',status,
        json.dumps(summary,ensure_ascii=False),json.dumps(catalog,ensure_ascii=False),
        json.dumps(rules,ensure_ascii=False)))
    conn.execute('UPDATE projects SET status=?,final_price=?,updated_at=CURRENT_TIMESTAMP WHERE id=?',
                 (status,final_price,project_id))
    conn.commit(); conn.close()
    return {'version':next_num,'status':status}


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host=HOST, port=PORT)
