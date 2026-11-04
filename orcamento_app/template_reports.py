"""Preenche os dois modelos originais da empresa sem redesenhar suas abas."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import socket
import shutil
import subprocess
import sys
import unicodedata
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from config import EXPORTS_DIR


TEMPLATES = Path(__file__).resolve().parent / "templates" / "spreadsheets"
CALC_TEMPLATE = TEMPLATES / "CÁLCULO+N. -1.xls"
COST_TEMPLATE = TEMPLATES / "PLANILHA DE CUSTO -.xlsx"
FILL_SCRIPT = Path(__file__).resolve().parent / "fill_company_templates.ps1"
UNO_FILL_SCRIPT = Path(__file__).resolve().parent / "fill_company_templates_uno.py"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS_MIME = "application/vnd.ms-excel"

CALC_SECTIONS = {
    "wire": (17, ("A", "B", "C"), ("radius_diam", "length", "quantity")),
    "sheet": (29, ("A", "B", "C", "D"), ("length", "width", "thickness", "quantity")),
    "tube": (17, ("I", "J", "K", "L", "M"), ("width", "depth", "thickness", "length", "quantity")),
    "round": (29, ("J", "K", "L", "M"), ("radius_diam", "thickness", "length", "quantity")),
}


def _slug(name: str) -> str:
    value = re.sub(r"[^\w-]+", "_", name or "orcamento", flags=re.UNICODE).strip("_")
    return value[:55] or "orcamento"


def _number(value):
    if value is None or value == "":
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _section(item: dict) -> str:
    group = item.get("group_name") or ""
    if group == "Arame":
        return "wire"
    if group == "Chapa":
        return "sheet"
    if group == "Tubo Quadrado/Retangular":
        return "tube"
    if group == "Tubo Redondo":
        return "round"
    if group in ("Impressão", "Pintura a Pó", "Tinta"):
        return "paint"
    raise ValueError(f"Matéria-prima sem seção no modelo CÁLCULO: {group} — {item.get('description')}")


def _is_psai(item: dict) -> bool:
    return item.get("group_name") == "Polímero/PSAI" or "PSAI" in (item.get("material") or "").upper()


def _split_items(materials: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {key: [] for key in (*CALC_SECTIONS, "paint", "bought")}
    for item in materials:
        if item.get("item_type") == "subconjunto":
            continue
        if item.get("item_type") == "comprado" or _is_psai(item):
            groups["bought"].append(item)
        else:
            groups[_section(item)].append(item)
    return groups


def _calc_pages(groups: dict[str, list[dict]]) -> list[dict[str, float]]:
    page_count = max(1, *(math.ceil(len(groups[key]) / 8) for key in CALC_SECTIONS))
    pages = []
    for page in range(page_count):
        cells: dict[str, float] = {}
        for key, (start, columns, fields) in CALC_SECTIONS.items():
            for offset, item in enumerate(groups[key][page * 8:(page + 1) * 8]):
                for col, field in zip(columns, fields):
                    value = _number(item.get(field))
                    if value is not None and (value > 0 or field == "quantity"):
                        cells[f"{col}{start + offset}"] = value
        pages.append(cells)
    return pages


def _cost_item(item: dict) -> dict:
    basis = item.get("price_basis") or {}
    if (not basis and item.get("group_name") in ("Pintura a Pó", "Tinta")
            and item.get("unit") == "kg" and _number(item.get("unit_price")) is not None
            and _number(item.get("total_weight")) is not None):
        basis = {"rate": item["unit_price"], "factor": 1.0, "ipi_pct": 0}
    quantity = _number(item.get("quantity"))
    basis_weight = _number(basis.get("weight"))
    return {
        "description": item.get("description") or "",
        "material": item.get("material") or "",
        "group_name": item.get("group_name") or "",
        "length": _number(item.get("length")),
        "width": _number(item.get("width")),
        "depth": _number(item.get("depth")),
        "thickness": _number(item.get("thickness")),
        "radius_diam": _number(item.get("radius_diam")),
        "printing": item.get("printing") or "",
        "unit": item.get("unit") or "",
        "quantity": quantity,
        "total_weight": _number(item.get("total_weight")),
        "cost_weight": basis_weight * quantity if basis_weight is not None and quantity is not None else None,
        "unit_price": _number(item.get("unit_price")),
        "total_price": _number(item.get("total_price")),
        "rate": _number(basis.get("rate")),
        "ipi_pct": _number(basis.get("ipi_pct")) or 0,
        "factor": _number(basis.get("factor")),
    }


def _normal_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", value).strip().upper()


def _clean_stock_material(value: str) -> str:
    """Remove catalog/record suffixes while retaining the stock specification."""
    value = re.sub(r"\s+-\s+\[[^]]*\].*$", "", value or "")
    value = re.sub(r"\s+-\s+\{MP[^}]*\}.*$", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip(" -")


def _cost_material_identity(item: dict, section: str):
    material = _normal_text(item.get("material") or "")
    if not material:
        # Without an explicit stock/SKU identity, don't merge distinct physical
        # parts merely because the parser assigned them to the same broad group.
        return ("part", _normal_text(item.get("description") or ""))
    unit = _normal_text(item.get("unit") or "")
    # Aggregate by actual stock identity; if repeated records carry different
    # approved line prices, their total price is preserved in the aggregate.
    rate_signature = ()
    if section == "tube":
        # The stock/SKU material field is the procurement profile. Piece-level
        # dimensions stay in CÁLCULO and may differ when a BOM cell was mapped
        # incorrectly; don't split the same stock by cut geometry.
        spec = ()
    elif section == "round":
        spec = tuple(item.get(key) for key in ("radius_diam", "thickness"))
    elif section == "wire":
        # Piece descriptions (REFORÇO, TRAVESSA, etc.) are cut names; stock is
        # the wire family and diameter. Ignore BOM/catalog IDs in the key.
        stock = _normal_text(_clean_stock_material(item.get("material") or ""))
        stock = re.sub(r"\s+ARTEFATO\s*[Ø⌀].*$", "", stock)
        if stock:
            material = stock
        spec = (item.get("radius_diam"),)
    elif section == "sheet":
        # Sheet commercial blank dimensions do not distinguish the same steel
        # grade/gauge. For flat bar, retain thickness and stock width instead.
        stock = _normal_text(_clean_stock_material(item.get("material") or ""))
        if stock.startswith("CHAPA "):
            stock = re.split(r"\s+E:\s*", stock, maxsplit=1)[0]
        elif stock.startswith("BARRA CHATA "):
            stock = re.sub(r"\s+X\s+C:\s*[\d.,]+\s*MM.*$", "", stock)
        if stock:
            material = stock
        spec = (item.get("thickness"),)
    elif section == "bought" and "PSAI" in material:
        # A PSAI piece's dimensions, print and color/grade determine its buy price.
        spec = tuple(item.get(key) for key in ("length", "width", "thickness", "printing"))
    else:
        spec = ()
    return (_normal_text(item.get("group_name") or ""), section, material,
            unit, spec, rate_signature)


def _cost_material_label(item: dict, section: str) -> str:
    description = (item.get("description") or "").strip()
    # Drop part/drawing identifiers from the representative stock name.
    description = re.sub(r"\s+-\s+(?:HEI|[A-Z]{2,}\d|\[).*$", "", description, flags=re.I)
    if section == "wire" and _number(item.get("radius_diam")) is not None:
        diameter = f"{float(item['radius_diam']):.1f}".replace(".", ",")
        return f"ARAME Ø{diameter}MM"
    if section == "tube":
        stock = item.get("material") or ""
        match = re.search(
            r"E:\s*([\d.,]+)\s*MM\s*X\s*L:\s*([\d.,]+)\s*MM\s*X\s*L:\s*([\d.,]+)\s*MM",
            stock, re.I,
        )
        if match:
            gauge, side_a, side_b = (float(value.replace(",", ".")) for value in match.groups())
            profile = "QUADRADO" if abs(side_a - side_b) < 0.001 else "RETANGULAR"
            return (f"TUBO {profile} {side_a:g}X{side_b:g}X{gauge:g}MM"
                    .replace(".", ","))
    if section == "sheet":
        stock = _clean_stock_material(item.get("material") or "")
        stock_normal = _normal_text(stock)
        thickness = _number(item.get("thickness"))
        if stock_normal.startswith("CHAPA ") and thickness is not None:
            gauge = f"{thickness:.2f}".replace(".", ",")
            if "ACO CARBONO" in stock_normal:
                return f"CHAPA DE AÇO CARBONO #{gauge}MM"
            if "INOX" in stock_normal:
                return f"CHAPA DE AÇO INOX #{gauge}MM"
        if stock_normal.startswith("BARRA CHATA "):
            stock = re.sub(r"\s+X\s+C:\s*[\d.,]+\s*MM.*$", "", stock, flags=re.I)
            return stock
        match = re.match(r"^(.*?\b\d+(?:[.,]\d+)?\s*MM)\s+\d+(?:[.,]\d+)?\s*[X×]\s*\d+(?:[.,]\d+)?\b", description, re.I)
        if match:
            return match.group(1).strip()
    if section == "wire" and re.search(r"PECA METALICA|ITEM GENERICO", _normal_text(description)):
        material = (item.get("material") or "").strip()
        material = re.sub(r"\s+-\s+\[[^]]*\].*$", "", material)
        return material or description
    return description


def _aggregate_cost_items(items: list[dict], section: str) -> list[dict]:
    """Consolidate identical stock material in cost only; physical cuts stay in CÁLCULO."""
    aggregated: dict[tuple, dict] = {}
    for source in items:
        item = _cost_item(source)
        key = _cost_material_identity(item, section)
        if key not in aggregated:
            item["description"] = _cost_material_label(item, section)
            item["aggregate_total_price"] = item["total_price"]
            item["aggregate_count"] = 1
            if section != "bought":
                item["quantity"] = 1.0
            aggregated[key] = item
            continue
        target = aggregated[key]
        target["aggregate_count"] += 1
        for field in ("quantity", "total_weight", "cost_weight", "total_price"):
            values = (target.get(field), item.get(field))
            if any(value is None for value in values):
                target[field] = None
            else:
                target[field] = sum(values)
        if target["aggregate_total_price"] is None or item["total_price"] is None:
            target["aggregate_total_price"] = None
        else:
            target["aggregate_total_price"] += item["total_price"]

        # The MP cost sheet's quantity column is weight; all cut lengths are
        # represented by the summed weight in one line.
        if section != "bought":
            target["quantity"] = 1.0
        elif target.get("total_price") is not None and target.get("quantity"):
            target["unit_price"] = target["total_price"] / target["quantity"]
        else:
            target["unit_price"] = None
    return list(aggregated.values())


def _run_excel_com(payload_path: Path):
    if sys.platform != "win32":
        raise RuntimeError("Os modelos originais .xls exigem Excel instalado no Windows.")
    command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
               "-File", str(FILL_SCRIPT), str(payload_path)]
    try:
        process = subprocess.run(command, capture_output=True, text=True, timeout=300,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("Não foi possível executar o Excel para preencher os modelos originais.") from exc
    if process.returncode:
        message = (process.stderr or process.stdout).strip()
        if "80080005" in message or "CO_E_SERVER_EXEC_FAILURE" in message:
            raise RuntimeError(
                "O Microsoft Excel não iniciou a instância de automação para preencher "
                "as planilhas. Salve e feche as outras janelas do Excel, confira se o "
                "Office está conectado/ativado e tente exportar novamente. Nenhuma "
                "planilha foi concluída. " + message[-500:]
            )
        raise RuntimeError(f"Falha ao preencher modelos no Excel: {message[-1200:]}")


def _run_libreoffice(payload_path: Path, program_dir: Path):
    soffice = program_dir / "soffice.exe"
    lo_python = program_dir / "python.exe"
    if not soffice.is_file() or not lo_python.is_file():
        raise RuntimeError("LibreOffice está instalado, mas falta o runtime UNO para preencher as planilhas.")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    profile_dir = payload_path.parent / f".libreoffice_{uuid4().hex[:8]}"
    profile_dir.mkdir()
    command = [
        str(soffice), "--headless", "--nologo", "--nodefault", "--norestore",
        "--nofirststartwizard", "--invisible",
        f"--accept=socket,host=localhost,port={port};urp;StarOffice.ServiceManager",
        f"-env:UserInstallation={profile_dir.as_uri()}",
    ]
    office = None
    try:
        office = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            process = subprocess.run(
                [str(lo_python), str(UNO_FILL_SCRIPT), str(payload_path), str(port)],
                capture_output=True, text=True, timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("O LibreOffice excedeu o tempo para preencher as planilhas.") from exc
        if process.returncode:
            message = (process.stderr or process.stdout).strip()
            raise RuntimeError(f"Falha ao preencher os modelos pelo LibreOffice: {message[-1200:]}")
        try:
            office.wait(timeout=20)
        except subprocess.TimeoutExpired:
            office.terminate()
            office.wait(timeout=10)
    finally:
        if office is not None and office.poll() is None:
            office.terminate()
            try:
                office.wait(timeout=10)
            except subprocess.TimeoutExpired:
                office.kill()
                office.wait(timeout=5)
        shutil.rmtree(profile_dir, ignore_errors=True)


def _run_excel(payload_path: Path):
    """Prefer isolated headless LibreOffice; retain Excel COM where LO is absent."""
    if sys.platform == "win32":
        program_dir = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "LibreOffice" / "program"
        if (program_dir / "soffice.exe").is_file() and (program_dir / "python.exe").is_file():
            _run_libreoffice(payload_path, program_dir)
            return
    _run_excel_com(payload_path)


def export_template_reports(full: dict, project_id: int, kind: str = "planilhas") -> Path:
    """Retorna CÁLCULO .xls, CUSTO .xlsx ou ZIP com ambos; pagina CÁLCULO sem alterar abas."""
    if kind not in ("calculo", "custos", "planilhas"):
        raise ValueError(f"Tipo de planilha inválido: {kind}")
    groups = _split_items(full["materials"])
    folder = Path(EXPORTS_DIR) / f"modelos_{project_id}_{uuid4().hex[:12]}"
    folder.mkdir(parents=True, exist_ok=True)
    suffix = _slug(full["project"].get("name"))
    payload = {
        "project_name": full["project"].get("name") or "Projeto",
        "project_date": full["project"].get("date") or "",
        "client": full["project"].get("client") or "",
        "calculations": [],
        "cost_path": None,
        "sections": {
            "tube": _aggregate_cost_items([*groups["tube"], *groups["round"]], "tube"),
            "wire": _aggregate_cost_items(groups["wire"], "wire"),
            "sheet": _aggregate_cost_items(groups["sheet"], "sheet"),
            "paint": _aggregate_cost_items(groups["paint"], "paint"),
            "bought": _aggregate_cost_items(groups["bought"], "bought"),
        },
    }
    paths: list[Path] = []
    if kind in ("calculo", "planilhas"):
        pages = _calc_pages(groups)
        for index, cells in enumerate(pages, 1):
            part = f" PARTE {index:02d}" if len(pages) > 1 else ""
            path = folder / f"CÁLCULO+N. -1 {suffix}{part}.xls"
            shutil.copy2(CALC_TEMPLATE, path)
            payload["calculations"].append({"path": str(path), "cells": cells})
            paths.append(path)
    if kind in ("custos", "planilhas"):
        path = folder / f"PLANILHA DE CUSTO - {suffix}.xlsx"
        shutil.copy2(COST_TEMPLATE, path)
        payload["cost_path"] = str(path)
        paths.append(path)
    payload_path = folder / "preenchimento.json"
    payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    try:
        _run_excel(payload_path)
    except Exception:
        # Não deixar cópias ainda vazias dos modelos parecerem exportações prontas.
        shutil.rmtree(folder, ignore_errors=True)
        raise

    if kind == "custos" or (kind == "calculo" and len(paths) == 1):
        return paths[0]
    archive = folder / f"ORÇAMENTO_{suffix}.zip"
    with ZipFile(archive, "w", ZIP_DEFLATED) as bundle:
        for path in paths:
            bundle.write(path, path.name)
    return archive
