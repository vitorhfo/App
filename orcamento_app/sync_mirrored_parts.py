"""Acrescenta montagens espelhadas a projetos já importados, sem reimportar tudo."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
import sys

from config import DATA_DIR
from database import get_connection
from reader_v3 import norm, process_complete_project, side_and_base


FIELDS = ("item_num", "description", "group_name", "material", "thickness", "radius_diam",
          "width", "depth", "length", "quantity", "unit", "unit_weight", "total_weight",
          "unit_area", "total_area", "drawing_id", "raw_code", "finish", "printing",
          "unit_price", "total_price", "price_source", "source_page", "confidence",
          "parent_assembly", "is_consolidated", "is_inferred", "pending_issue",
          "observation", "item_type")


def _fingerprint(item):
    return (norm(item.get("parent_assembly")), norm(item.get("description")),
            norm(item.get("drawing_id")))


def _insert(conn, project_id, item, number):
    record = {key: item.get(key) for key in FIELDS}
    record["item_num"] = number
    columns = ", ".join(("project_id", *FIELDS))
    placeholders = ", ".join("?" for _ in range(len(FIELDS) + 1))
    cursor = conn.execute(f"INSERT INTO materials ({columns}) VALUES ({placeholders})",
                          (project_id, *(record[key] for key in FIELDS)))
    if record["pending_issue"] or (record["confidence"] or 1) < 0.85:
        conn.execute("""INSERT INTO pending_decisions
            (project_id,item_id,title,description,impact_level,proposed_action)
            VALUES (?,?,?,?,?,?)""",
            (project_id,cursor.lastrowid,f"Confirmação: {record['description']}",
             record["pending_issue"] or "Conferir componente espelhado.","MEDIO",
             f"Conferir origem {record['source_page']}"))
    return cursor.lastrowid


def sync_project(project_id: int):
    conn=get_connection()
    row=conn.execute("SELECT folder_path FROM projects WHERE id=?",(project_id,)).fetchone()
    if not row:
        conn.close(); raise ValueError("Projeto não encontrado")
    source=Path(row["folder_path"] or "")
    if not source.is_dir():
        conn.close(); raise ValueError("Pasta de origem do projeto não encontrada")
    parsed=process_complete_project(source)
    fresh=parsed["materials"]
    mirrored_parents=[m for m in fresh if m["item_type"]=="subconjunto"
                      and m["is_inferred"] and "espelhad" in norm(m["observation"]).lower()]
    if not mirrored_parents:
        conn.close(); return {"added":0,"updated":0,"backup":None}
    current=[dict(r) for r in conn.execute(
        "SELECT * FROM materials WHERE project_id=?",(project_id,)).fetchall()]
    existing={_fingerprint(m):m for m in current}
    next_number=max((m["item_num"] for m in current),default=0)
    additions=[]; updates=[]
    for target_parent in mirrored_parents:
        side,base=side_and_base(target_parent["description"])
        source_parent=next((m for m in fresh if m["item_type"]=="subconjunto"
            and not m["is_inferred"] and m["parent_assembly"]==target_parent["parent_assembly"]
            and side_and_base(m["description"])[1]==base
            and side_and_base(m["description"])[0]!=side),None)
        if not source_parent: continue
        source_path=source_parent["parent_assembly"]+" / "+source_parent["description"]
        target_path=target_parent["parent_assembly"]+" / "+target_parent["description"]
        if _fingerprint(source_parent) not in existing:
            additions.append(source_parent)
        old_parent=existing.get(_fingerprint(target_parent))
        if old_parent:
            if (not old_parent["is_inferred"] or old_parent["observation"]!=target_parent["observation"]
                    or old_parent["pending_issue"]):
                updates.append((old_parent,target_parent))
        else:
            additions.append(target_parent)
        for target in (m for m in fresh if m["parent_assembly"]==target_path):
            if _fingerprint(target) in existing: continue
            source_item=next((m for m in current if m["parent_assembly"]==source_path
                and norm(m["description"])==norm(target["description"])
                and norm(m["drawing_id"])==norm(target["drawing_id"])),None)
            candidate=dict(target)
            if source_item:
                # Alterações manuais feitas na peça desenhada valem para seu par espelhado.
                for field in ("group_name","material","thickness","radius_diam","width",
                              "depth","length","unit","unit_weight","unit_area","raw_code",
                              "finish","printing","unit_price","price_source","item_type",
                              "pending_issue"):
                    candidate[field]=source_item[field]
                candidate["total_weight"]=round((candidate["unit_weight"] or 0)*candidate["quantity"],4)
                candidate["total_area"]=round((candidate["unit_area"] or 0)*candidate["quantity"],4)
                candidate["total_price"]=(round(candidate["unit_price"]*candidate["quantity"],2)
                                          if candidate["unit_price"] is not None else None)
            additions.append(candidate)
    if not additions and not updates:
        conn.close(); return {"added":0,"updated":0,"backup":None}
    backup_dir=Path(DATA_DIR)/"backups"
    backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/f"before_mirror_project_{project_id}_{datetime.now():%Y%m%d_%H%M%S}.sqlite"
    with sqlite3.connect(backup) as backup_conn:
        conn.backup(backup_conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        for old,new in updates:
            conn.execute("""UPDATE materials SET is_inferred=1, observation=?, pending_issue='',
                confidence=MAX(confidence,0.9) WHERE id=? AND project_id=?""",
                (new["observation"],old["id"],project_id))
            conn.execute("""DELETE FROM pending_decisions WHERE project_id=? AND item_id=?
                AND status='PENDENTE' AND description LIKE '%Subconjunto sem lista detalhada%'""",
                (project_id,old["id"]))
        for item in additions:
            next_number+=1
            _insert(conn,project_id,item,next_number)
        conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (project_id,))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
    return {"added":len(additions),"updated":len(updates),"backup":str(backup)}


if __name__=="__main__":
    if len(sys.argv)!=2 or not sys.argv[1].isdigit():
        raise SystemExit("Uso: python sync_mirrored_parts.py ID_DO_PROJETO")
    print(sync_project(int(sys.argv[1])))
