"""Fill the original company spreadsheets through LibreOffice UNO.

This is a headless fallback for Windows machines where Excel COM cannot start.
It edits only the copies named in the generated payload.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue


def prop(name: str, value):
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def connect(port: int):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    address = f"uno:socket,host=localhost,port={port};urp;StarOffice.ComponentContext"
    last_error = None
    for _ in range(60):
        try:
            return resolver.resolve(address)
        except Exception as exc:  # LO may take a few seconds to initialize.
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"LibreOffice não iniciou a ponte UNO: {last_error}")


def set_cell(sheet, address: str, value):
    cell = sheet.getCellRangeByName(address)
    if value is None:
        cell.clearContents(1 | 2 | 4 | 16)
    elif isinstance(value, str):
        if value.startswith("="):
            cell.setFormula(value)
        else:
            cell.setString(value)
    else:
        cell.setValue(float(value))


def fill_section(sheet, first: int, last: int, subtotal: int, items, kind: str) -> int:
    items = list(items or [])
    extra = max(0, len(items) - (last - first + 1))
    if extra:
        sheet.getRows().insertByIndex(last - 1, extra)
        source_row = last + extra - 1
        for row in range(last - 1, last - 1 + extra):
            source = sheet.getCellRangeByPosition(1, source_row, 6, source_row)
            target = sheet.getCellRangeByPosition(1, row, 6, row)
            sheet.copyRange(target.getCellByPosition(0, 0).getCellAddress(), source.getRangeAddress())

    end = last + extra
    sheet.getCellRangeByPosition(1, first - 1, 6, end - 1).clearContents(1 | 2 | 4 | 16)
    for offset, item in enumerate(items):
        row = first + offset
        set_cell(sheet, f"B{row}", item.get("description", ""))
        if kind == "comprado":
            set_cell(sheet, f"C{row}", item.get("quantity"))
            if item.get("unit_price") is not None:
                set_cell(sheet, f"D{row}", item["unit_price"])
                set_cell(sheet, f"G{row}", f"=ROUND(C{row}*D{row};2)")
            continue

        cost_weight = item.get("cost_weight")
        total_weight = item.get("total_weight")
        if cost_weight is not None and cost_weight > 0:
            set_cell(sheet, f"C{row}", cost_weight)
        elif total_weight is not None and total_weight > 0:
            set_cell(sheet, f"C{row}", total_weight)

        if item.get("aggregate_total_price") is not None:
            rate, factor = item.get("rate"), item.get("factor")
            cost_weight = item.get("cost_weight") or total_weight
            if cost_weight is not None and cost_weight > 0:
                effective_rate = float(item["aggregate_total_price"]) / float(cost_weight)
                if kind != "chapa" and item.get("unit_price") is not None and rate is not None and factor is not None:
                    gross = float(rate) * (1 + float(item.get("ipi_pct") or 0) / 100)
                    set_cell(sheet, f"D{row}", gross)
                    set_cell(sheet, f"F{row}", effective_rate)
                    set_cell(sheet, f"E{row}", f"=D{row}-F{row}")
                else:
                    set_cell(sheet, f"F{row}", effective_rate)
                set_cell(sheet, f"G{row}", f"=ROUND(C{row}*F{row};2)")
            elif item.get("unit_price") is not None and rate is not None and factor is not None:
                gross = float(rate) * (1 + float(item.get("ipi_pct") or 0) / 100)
                if kind == "chapa":
                    set_cell(sheet, f"F{row}", gross * float(factor))
                else:
                    set_cell(sheet, f"D{row}", gross)
                    set_cell(sheet, f"F{row}", f"=D{row}*{float(factor):.10f}")
                    set_cell(sheet, f"E{row}", f"=D{row}-F{row}")
                set_cell(sheet, f"G{row}", item["aggregate_total_price"])
            else:
                set_cell(sheet, f"G{row}", item["aggregate_total_price"])
            continue

        if item.get("unit_price") is None:
            continue
        rate, factor = item.get("rate"), item.get("factor")
        if rate is not None and factor is not None:
            gross = float(rate) * (1 + float(item.get("ipi_pct") or 0) / 100)
            if kind == "chapa":
                set_cell(sheet, f"F{row}", gross * float(factor))
            else:
                set_cell(sheet, f"D{row}", gross)
                set_cell(sheet, f"F{row}", f"=D{row}*{float(factor):.10f}")
                set_cell(sheet, f"E{row}", f"=D{row}-F{row}")
            if total_weight is not None and total_weight > 0:
                quantity = float(item.get("quantity") or 0)
                if quantity > 0:
                    formula = f"=ROUND(ROUND(C{row}*F{row}/{quantity:.10f};4)*{quantity:.10f};2)"
                else:
                    formula = f"=ROUND(C{row}*F{row};2)"
                set_cell(sheet, f"G{row}", formula)
            else:
                set_cell(sheet, f"G{row}", item.get("total_price"))
        elif total_weight is not None and total_weight > 0:
            if item.get("total_price") is not None:
                set_cell(sheet, f"F{row}", float(item["total_price"]) / float(total_weight))
                set_cell(sheet, f"G{row}", f"=ROUND(C{row}*F{row};2)")
        else:
            set_cell(sheet, f"G{row}", item.get("total_price"))

    total_row = subtotal + extra
    if kind == "comprado":
        set_cell(sheet, f"G{total_row}", f"=SUM(G{first}:G{end})")
    else:
        set_cell(sheet, f"C{total_row}", f"=SUM(C{first}:C{end})")
        set_cell(sheet, f"G{total_row}", f"=SUM(G{first}:G{end})")
    return extra


def fill(payload_path: Path, port: int):
    data = json.loads(payload_path.read_text(encoding="utf-8"))
    context = connect(port)
    desktop = context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", context
    )
    opened = []
    try:
        for page in data["calculations"]:
            url = uno.systemPathToFileUrl(str(Path(page["path"]).resolve()))
            book = desktop.loadComponentFromURL(
                url, "_blank", 0,
                (prop("Hidden", True), prop("ReadOnly", False), prop("UpdateDocMode", 3)),
            )
            if book is None:
                raise RuntimeError(f"Não foi possível abrir {page['path']}")
            opened.append(book)
            sheet = book.Sheets.getByName("Total")
            for address, value in page["cells"].items():
                set_cell(sheet, address, value)
            book.calculateAll()
            book.store()
            book.close(True)
            opened.remove(book)

        cost_path = data.get("cost_path")
        if cost_path:
            url = uno.systemPathToFileUrl(str(Path(cost_path).resolve()))
            book = desktop.loadComponentFromURL(
                url, "_blank", 0,
                (prop("Hidden", True), prop("ReadOnly", False), prop("UpdateDocMode", 3)),
            )
            if book is None:
                raise RuntimeError(f"Não foi possível abrir {cost_path}")
            opened.append(book)
            mp, bought = book.Sheets.getByIndex(0), book.Sheets.getByIndex(1)
            sections = data["sections"]
            paint_extra = fill_section(mp, 37, 39, 40, sections["paint"], "tinta")
            sheet_extra = fill_section(mp, 25, 29, 32, sections["sheet"], "chapa")
            wire_extra = fill_section(mp, 18, 21, 22, sections["wire"], "arame")
            tube_extra = fill_section(mp, 9, 13, 15, sections["tube"], "tubo")
            total_row = 42 + tube_extra + wire_extra + sheet_extra + paint_extra
            tube_total = 15 + tube_extra
            wire_total = 22 + tube_extra + wire_extra
            sheet_total = 32 + tube_extra + wire_extra + sheet_extra
            paint_total = 40 + tube_extra + wire_extra + sheet_extra + paint_extra
            set_cell(mp, f"C{total_row}", f"=SUM(C{tube_total};C{wire_total};C{sheet_total})")
            set_cell(mp, f"G{total_row}", f"=SUM(G{tube_total};G{wire_total};G{sheet_total};G{paint_total})")
            fill_section(bought, 9, 29, 30, sections["bought"], "comprado")
            set_cell(mp, "E5", data.get("client", ""))
            set_cell(mp, "B7", f"DESCRIÇÃO DO ITEM: {data.get('project_name') or 'Projeto'}")
            set_cell(mp, "E7", f"Data Orçamento: {data.get('project_date') or ''}")
            set_cell(bought, "E5", data.get("client", ""))
            book.calculateAll()
            book.store()
            book.close(True)
            opened.remove(book)
    finally:
        for book in opened:
            try:
                book.close(True)
            except Exception:
                pass
        try:
            desktop.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        fill(Path(sys.argv[1]), int(sys.argv[2]))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
