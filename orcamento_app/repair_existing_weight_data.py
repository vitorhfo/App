"""One-time repair of saved wire cuts and parameterized PDF components."""

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
import sqlite3

from app import import_project_folder
from config import DATA_DIR
from database import get_connection, init_db
from pricing import reprice_project
from reader_v3 import norm, process_complete_project
from wire_allowance import apply_wire_allowance


def _record(conn, project_id, before, after):
    conn.execute('''INSERT INTO material_changes
        (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
        (project_id,before['id'],json.dumps(before,ensure_ascii=False),
         json.dumps(after,ensure_ascii=False)))


def _update_wire(conn, project_id, before, item):
    conn.execute('''UPDATE materials SET drawing_length=?,length=?,wire_allowance_mm=?,
        finished_unit_weight=?,finished_total_weight=?,unit_weight=?,total_weight=?,
        unit_area=?,total_area=?,observation=? WHERE id=? AND project_id=?''',
        (item['drawing_length'],item['length'],item['wire_allowance_mm'],
         item['finished_unit_weight'],item['finished_total_weight'],item['unit_weight'],
         item['total_weight'],item['unit_area'],item['total_area'],item['observation'],
         item['id'],project_id))
    _record(conn,project_id,before,item)


def _repair_collapsed_reckitt(conn):
    project_id=2
    row=conn.execute('SELECT folder_path FROM projects WHERE id=?',(project_id,)).fetchone()
    if not row or not Path(row['folder_path'] or '').is_dir():
        return {'filled':0,'added':0}
    fresh=process_complete_project(row['folder_path'])['materials']
    groups=defaultdict(list)
    for item in fresh:
        groups[norm(item['description'])].append(item)
    current=[dict(row) for row in conn.execute(
        'SELECT * FROM materials WHERE project_id=?',(project_id,))]
    existing={norm(item['description']) for item in current}
    filled=added=0
    for old in current:
        matches=groups.get(norm(old['description']),[])
        if old['unit_weight']>0 or not matches:
            continue
        units={round(float(item.get('unit_weight') or 0),6) for item in matches}
        if len(units)!=1 or next(iter(units))<=0:
            continue
        if abs(sum(item['quantity'] for item in matches)-old['quantity'])>0.001:
            continue
        source=matches[0]
        item=dict(old)
        for key in ('group_name','item_type','material','thickness','radius_diam',
                    'width','depth','length','unit_weight','unit_area','drawing_id',
                    'source_page','pending_issue'):
            item[key]=source.get(key)
        item['total_weight']=round(item['unit_weight']*item['quantity'],4)
        item['total_area']=round((item['unit_area'] or 0)*item['quantity'],4)
        conn.execute('''UPDATE materials SET group_name=?,item_type=?,material=?,
            thickness=?,radius_diam=?,width=?,depth=?,length=?,unit_weight=?,
            total_weight=?,unit_area=?,total_area=?,drawing_id=?,source_page=?,
            pending_issue=? WHERE id=? AND project_id=?''',
            (*(item[key] for key in ('group_name','item_type','material','thickness',
               'radius_diam','width','depth','length','unit_weight','total_weight',
               'unit_area','total_area','drawing_id','source_page','pending_issue')),
             item['id'],project_id))
        conn.execute('''DELETE FROM pending_decisions WHERE project_id=? AND item_id=?
            AND status='PENDENTE' AND title LIKE 'Confirmação:%' ''',
            (project_id,item['id']))
        _record(conn,project_id,old,item)
        filled+=1
    next_number=max(item['item_num'] for item in current)
    db_fields={row[1] for row in conn.execute('PRAGMA table_info(materials)')}
    for key,matches in groups.items():
        if key in existing:
            continue
        source=dict(matches[0])
        if len({round(float(item.get('unit_weight') or 0),6) for item in matches})!=1:
            continue
        next_number+=1
        source['item_num']=next_number
        source['quantity']=sum(item['quantity'] for item in matches)
        source['total_weight']=round((source.get('unit_weight') or 0)*source['quantity'],4)
        source['total_area']=round((source.get('unit_area') or 0)*source['quantity'],4)
        source['is_consolidated']=int(len(matches)>1)
        if len(matches)>1:
            source['observation']=' '.join(x for x in (
                source.get('observation') or '',
                f'Quantidade somada de {len(matches)} ocorrências na lista técnica.') if x)
        columns=[key for key in source if key in db_fields and key!='id']
        conn.execute(f'''INSERT INTO materials (project_id,{','.join(columns)})
            VALUES ({','.join('?' for _ in range(len(columns)+1))})''',
            (project_id,*(source[key] for key in columns)))
        added+=1
    return {'filled':filled,'added':added}


def repair():
    conn=get_connection()
    if conn.execute("SELECT 1 FROM app_meta WHERE key='wire_weight_repair_v1'").fetchone():
        conn.close()
        return {'already_applied':True}
    backup_dir=Path(DATA_DIR)/'backups'
    backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/f'before_wire_weight_repair_{datetime.now():%Y%m%d_%H%M%S}.sqlite'
    with sqlite3.connect(backup) as target:
        conn.backup(target)
    conn.close()
    init_db()
    rebuilt={}
    for project_id in (9,10,11):
        conn=get_connection()
        row=conn.execute('SELECT folder_path FROM projects WHERE id=?',(project_id,)).fetchone()
        edits=conn.execute('SELECT 1 FROM material_changes WHERE project_id=? LIMIT 1',
                           (project_id,)).fetchone()
        versions=conn.execute('SELECT 1 FROM budget_versions WHERE project_id=? LIMIT 1',
                              (project_id,)).fetchone()
        decisions=conn.execute("SELECT 1 FROM pending_decisions WHERE project_id=? AND status!='PENDENTE' LIMIT 1",
                               (project_id,)).fetchone()
        conn.close()
        if not row or not Path(row['folder_path'] or '').is_dir() or edits or versions or decisions:
            continue
        rebuilt[project_id]=import_project_folder(project_id,row['folder_path'])['materials_count']
    conn=get_connection()
    conn.execute('BEGIN IMMEDIATE')
    try:
        collapsed=_repair_collapsed_reckitt(conn)
        wires=0
        for row in conn.execute('''SELECT * FROM materials WHERE group_name='Arame'
            AND COALESCE(wire_allowance_mm,0)=0''').fetchall():
            before=dict(row)
            item=dict(before)
            if apply_wire_allowance(item):
                _update_wire(conn,item['project_id'],before,item)
                wires+=1
        for project_id in {2,*rebuilt} | {row[0] for row in conn.execute(
                'SELECT DISTINCT project_id FROM materials WHERE wire_allowance_mm>0')}:
            reprice_project(conn,project_id)
            conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (project_id,))
        conn.execute("INSERT INTO app_meta(key,value) VALUES('wire_weight_repair_v1',?)",
                     (datetime.now().isoformat(),))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {'backup':str(backup),'rebuilt':rebuilt,'collapsed_reckitt':collapsed,'wires':wires}


if __name__=='__main__':
    print(repair())
