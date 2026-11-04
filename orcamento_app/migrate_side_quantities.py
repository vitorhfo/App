"""Consolidate verified mirrored components in existing project budgets."""

from datetime import datetime
from pathlib import Path
import json
import sqlite3

from config import DATA_DIR
from database import get_connection, init_db
from reader_v3 import consolidate_mirrored_materials


def migrate():
    init_db()
    conn=get_connection()
    changes=[]
    for (project_id,) in conn.execute('SELECT id FROM projects'):
        original=[dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=? ORDER BY item_num',(project_id,))]
        merged=consolidate_mirrored_materials([dict(item) for item in original])
        retained={item['id'] for item in merged}
        by_id={item['id']:item for item in original}
        for item in merged:
            old=by_id[item['id']]
            if old and item.get('mirrored_assembly') and not old.get('mirrored_assembly'):
                mirrors=[row for row in original if row['id'] not in retained
                         and row['parent_assembly']==item['mirrored_assembly']
                         and row['description']==item['description']]
                if len(mirrors)!=1:
                    raise ValueError(f'Contraparte ambígua para o item {item["id"]}')
                mirror=mirrors[0]
                old_weight=(old['total_weight'] or 0)+(mirror['total_weight'] or 0)
                old_cost=(old['total_price'] or 0)+(mirror['total_price'] or 0)
                # Two formerly rounded lines can differ by one cent after merging.
                if abs(item['total_weight']-old_weight)>0.0001 or abs((item.get('total_price') or 0)-old_cost)>0.011:
                    raise ValueError(f'Total alterado no item {item["id"]}; revisar manualmente')
                changes.append((project_id,old,item,mirror))
    if not changes:
        conn.close()
        return {'pairs':0,'backup':None}
    backup_dir=Path(DATA_DIR)/'backups'
    backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/f'before_side_quantities_{datetime.now():%Y%m%d_%H%M%S}.sqlite'
    with sqlite3.connect(backup) as backup_conn:
        conn.backup(backup_conn)
    conn.execute('BEGIN IMMEDIATE')
    try:
        for project_id,old,item,mirror in changes:
            conn.execute('''UPDATE materials SET quantity=?,total_weight=?,total_area=?,
                total_price=?,mirrored_assembly=?,is_consolidated=1,observation=?
                WHERE id=? AND project_id=?''',
                (item['quantity'],item['total_weight'],item['total_area'],
                 item.get('total_price'),item['mirrored_assembly'],item['observation'],
                 item['id'],project_id))
            conn.execute('''INSERT INTO material_changes
                (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
                (project_id,item['id'],json.dumps(old,ensure_ascii=False),
                 json.dumps(item,ensure_ascii=False)))
            conn.execute('DELETE FROM materials WHERE id=? AND project_id=?',
                         (mirror['id'],project_id))
            conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (project_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {'pairs':len(changes),'backup':str(backup)}


if __name__=='__main__':
    print(migrate())
