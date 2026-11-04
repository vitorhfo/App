"""Revise the photo quote with the construction described by the customer."""

from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import shutil
import sqlite3

from app import get_project_full_data
from calc_engine import DENSIDADE_ACO_CARBONO
from config import DATA_DIR, DB_PATH
from database import get_connection
from mass_math import ceil_kg
from pricing import approved_rules, price_item
from template_reports import export_template_reports


PROJECT_ID = 31
CODE = "FOTO-HELLMANNS-20261016"
REVISION = "HELLMANNS-FOTO-ARAME4-CHAPA075-20261016"
PHOTO_FILES = (
    Path(r"C:\Users\Luis\AppData\Local\Temp\codex-clipboard-2a6ca573-3186-44f4-8aa8-f29d40a2b7cd.png"),
    Path(r"C:\Users\Luis\AppData\Local\Temp\codex-clipboard-761adf5e-64c7-4cce-9120-22f4e8fe4771.png"),
)

# Seven individual sheets. Blanks are photo estimates, in millimetres.
SHEETS = (
    ("Lateral direita", 200, 150),
    ("Lateral esquerda", 200, 150),
    ("Tampa superior", 250, 75),
    ("Fundo traseiro", 250, 150),
    ("Base inferior", 250, 150),
    ("Divisória interna esquerda", 150, 100),
    ("Divisória interna direita", 150, 100),
)

# Finished geometry, in millimetres. Each separate cut receives +20 mm.
WIRES = (
    ("Contorno superior", 800, 1),
    ("Contorno frontal", 700, 1),
    ("Contorno inferior", 800, 1),
    ("União lateral do contorno", 200, 2),
)


def add_item(conn, rules, number, description, group, item_type, material,
             quantity, unit, unit_weight, unit_area, source_page, observation,
             pending_issue, unit_price=None, price_source="", **geometry):
    values = dict(
        project_id=PROJECT_ID, item_num=number, description=description,
        group_name=group, item_type=item_type, material=material,
        quantity=quantity, unit=unit, unit_weight=unit_weight,
        total_weight=ceil_kg(quantity * unit_weight), unit_area=unit_area,
        total_area=round(quantity * unit_area, 6), unit_price=unit_price,
        total_price=round(quantity * unit_price, 2) if unit_price is not None else None,
        price_source=price_source, source_page=source_page,
        drawing_id=f"{CODE}-{number:02d}", confidence=0.4,
        parent_assembly="DISPLAY DE SACHÊS HELLMANN’S", is_inferred=1,
        pending_issue=pending_issue, observation=observation,
        thickness=geometry.get("thickness", 0),
        width=geometry.get("width", 0),
        length=geometry.get("length", 0),
        radius_diam=geometry.get("radius_diam", 0),
        drawing_length=geometry.get("drawing_length"),
        wire_allowance_mm=geometry.get("wire_allowance_mm", 0),
        finished_unit_weight=geometry.get("finished_unit_weight"),
        finished_total_weight=geometry.get("finished_total_weight"),
    )
    if unit_price is None:
        values["unit_price"], values["price_source"] = price_item(values, rules, conn)
        if values["unit_price"] is not None:
            values["total_price"] = round(quantity * values["unit_price"], 2)
    columns = tuple(values)
    conn.execute(
        f"INSERT INTO materials ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        tuple(values.values()),
    )


def revise():
    photo_dir = Path(DATA_DIR) / "photo_sources"
    photo_dir.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(PHOTO_FILES, 1):
        if not source.is_file():
            raise FileNotFoundError(source)
        shutil.copy2(source, photo_dir / f"{REVISION}-{index}.png")

    conn = get_connection()
    project = conn.execute("SELECT * FROM projects WHERE id=? AND code=?",
                           (PROJECT_ID, CODE)).fetchone()
    if project is None:
        raise RuntimeError("Projeto fotográfico Hellmann's não encontrado")
    if conn.execute("SELECT value FROM app_meta WHERE key=?", (REVISION,)).fetchone():
        conn.execute("UPDATE projects SET client='HELLMANN' WHERE id=?", (PROJECT_ID,))
        conn.commit()
        conn.close()
        return

    backup_dir = Path(DATA_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"orcamento_antes_{REVISION}.db"
    if backup_path.exists():
        raise RuntimeError(f"Backup já existe sem marca de revisão: {backup_path}")
    with sqlite3.connect(backup_path) as backup:
        conn.backup(backup)

    rules = approved_rules(conn)
    required = {"mp_chapa_aco", "mp_arame", "mp_arame_fator_liquido",
                "mp_tinta_po", "taxa_consumo_tinta"}
    if required - rules.keys():
        raise RuntimeError(f"Regras de preço ausentes: {required - rules.keys()}")
    old = [dict(row) for row in conn.execute(
        "SELECT * FROM materials WHERE project_id=? ORDER BY item_num", (PROJECT_ID,))]
    now = datetime.now().isoformat(timespec="seconds")
    reference = "; ".join(f"{REVISION}-{i}.png" for i in (1, 2))
    rho = DENSIDADE_ACO_CARBONO
    one_face_area = 0.0
    wire_outer_area = 0.0
    try:
        conn.execute("BEGIN")
        conn.execute("DELETE FROM materials WHERE project_id=?", (PROJECT_ID,))
        conn.execute("DELETE FROM pending_decisions WHERE project_id=?", (PROJECT_ID,))
        number = 1
        for label, nominal, quantity in WIRES:
            cut = nominal + 20
            unit_weight = ceil_kg(math.pi * 2**2 * cut * rho / 1_000_000)
            finished = ceil_kg(math.pi * 2**2 * nominal * rho / 1_000_000)
            area = math.pi * 4 * cut / 1_000_000
            wire_outer_area += area * quantity
            add_item(
                conn, rules, number, label, "Arame", "materia_prima",
                "ARAME BTC Ø4 mm", quantity, "un", unit_weight, area,
                reference,
                f"Contorno inferido da foto: {nominal} mm na peça; corte de {cut} mm inclui 20 mm para solda.",
                "Confirmar percurso, número de cortes e raio das curvas no desenho técnico.",
                length=cut, radius_diam=4, drawing_length=nominal,
                wire_allowance_mm=20, finished_unit_weight=finished,
                finished_total_weight=ceil_kg(finished * quantity),
            )
            number += 1

        for label, length, width in SHEETS:
            area = length * width / 1_000_000
            one_face_area += area
            weight = ceil_kg(length * width * 0.75 * rho / 1_000_000)
            add_item(
                conn, rules, number, label, "Chapa", "materia_prima",
                "CHAPA DE AÇO SAE 1008 0,75 mm", 1, "un", weight, area,
                reference,
                f"Peça individual em chapa 0,75 mm; corte estimado {length} × {width} mm pela foto. Peso bruto antes dos vazados.",
                "Confirmar planificação, medidas, furos e eventual perfuração no desenho técnico.",
                length=length, width=width, thickness=0.75,
            )
            number += 1

        paint_kg = ceil_kg((2 * one_face_area + wire_outer_area) * rules["taxa_consumo_tinta"])
        add_item(
            conn, rules, number, "Pintura a pó azul escuro", "Pintura a Pó", "materia_prima",
            "TINTA PÓ AZUL ESCURO", paint_kg, "kg", 1, 0, reference,
            "Consumo sobre duas faces das sete chapas e superfície externa do arame.",
            "Confirmar acabamento, área efetiva e consumo de tinta.",
            unit_price=rules["mp_tinta_po"],
            price_source=f"Tinta pó: modelo vazio, R$ {rules['mp_tinta_po']:.2f}/kg",
        )
        number += 1
        add_item(
            conn, rules, number, "Ventosa 55 mm com botão", "Outros Comprados", "comprado",
            "VENTOSA 55 MM C/BOTÃO", 2, "un", 0, 0, reference,
            "Duas ventosas indicadas na imagem original.",
            "Confirmar modelo, diâmetro e preço atual do fornecedor.",
            unit_price=6.86,
            price_source="Referência preliminar: catálogo de comprados, R$ 6,86/un, não aprovado",
        )
        number += 1
        logo_area = 130 * 55 / 1_000_000
        logo_rate = rules["pl_adesivo_vinil_010"] + rules["imp_digital_face"]
        add_item(
            conn, rules, number, "Adesivo vinil impresso HELLMANN’S 130 × 55 mm",
            "Outros Comprados", "comprado", "ADESIVO VINIL IMPRESSO 4x0",
            1, "un", 0, logo_area, reference,
            "Tamanho do logo estimado pela proporção da foto.",
            "Confirmar arte, tamanho e custo mínimo de impressão.",
            unit_price=round(logo_area * logo_rate, 4),
            price_source="Estimativa por área: vinil + impressão 4x0 do modelo vigente",
        )

        notes = (
            "Revisão de orçamento fotográfico: contorno em arame BTC Ø4 mm; sete chapas "
            "SAE 1008 de 0,75 mm (duas laterais, tampa superior, fundo traseiro, "
            "base inferior e duas divisórias); duas ventosas e logo adesivo. "
            "Medidas externas informadas: 250 × 150 × 200 mm; três compartimentos de "
            "aproximadamente 75 mm. Peso final de cerca de 0,9 kg informado na imagem, "
            "sem desenho técnico para conferir a massa real. Comprimentos do arame e "
            "planos de corte das chapas foram estimados da foto. Cada corte de arame "
            "inclui 20 mm adicionais para solda. Pesos de metal são brutos, antes "
            "dos vazados e da dobra. Ventosa usa preço de catálogo não aprovado. "
            "Sem mão de obra, perdas, embalagem ou markup."
        )
        conn.execute(
            "UPDATE projects SET notes=?, client='HELLMANN', status='PRELIMINAR', updated_at=? WHERE id=?",
            (notes, now, PROJECT_ID),
        )
        for title, description in (
            ("Confirmar geometria e peso", "Cortes e comprimentos inferidos da foto; validar desenho, perfurações, soldas e massa acabada de cerca de 0,9 kg."),
            ("Confirmar itens comprados", "Preço da ventosa não aprovado; logo pode ter custo mínimo de impressão."),
        ):
            conn.execute(
                "INSERT INTO pending_decisions (project_id,title,description,impact_level,proposed_action) VALUES (?,?,?,?,?)",
                (PROJECT_ID, title, description, "ALTO", "Conferir desenho técnico e cotação do fornecedor."),
            )
        conn.execute(
            "INSERT INTO app_meta (key,value) VALUES (?,?)",
            (REVISION, json.dumps({"date": now, "previous_materials": old,
                                   "backup": str(backup_path)}, ensure_ascii=False)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    revise()
    full = get_project_full_data(PROJECT_ID)
    path = export_template_reports(full, PROJECT_ID, "planilhas")
    print(f"PROJECT_ID={PROJECT_ID}")
    print(f"EXPORT_DIR={path.parent}")
    for group in ("Arame", "Chapa", "Pintura a Pó", "Outros Comprados"):
        items = [m for m in full["materials"] if m["group_name"] == group]
        print(f"{group}: qty={sum(m['quantity'] for m in items):g}, "
              f"weight={sum(m['total_weight'] for m in items):.6f}, "
              f"cost={sum(m['total_price'] or 0 for m in items):.2f}")
