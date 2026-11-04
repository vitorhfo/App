"""Restore three omitted VEJA packaging BOM rows, preserving manual tape quantities."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from config import DB_PATH
from database import get_connection
from pricing import approved_rules, price_item
from reader_v3 import process_complete_project


def run(apply=False):
    conn=get_connection()
    try:
        root=Path(conn.execute('SELECT folder_path FROM projects WHERE id=1').fetchone()[0])
        fresh={item['item_num']:item for item in process_complete_project(root)['materials']}
        expected={37:20,38:0.08,39:1}
        additions=[]
        for number,quantity in expected.items():
            item=fresh.get(number)
            if not item or item['quantity']!=quantity or item['item_type']!='comprado' or '#page=6' not in item['source_page']:
                raise ValueError(f'Item VEJA {number} não confirmado na página 6')
            saved=conn.execute('SELECT id FROM materials WHERE project_id=1 AND item_num=?',(number,)).fetchone()
            if not saved: additions.append(item)
        print(f'{len(additions)} itens ausentes; '+('aplicando' if apply else 'sem alterações'))
        if not apply or not additions: return len(additions)
        backup=Path(DB_PATH).parent/'backups'/f'before_veja_packaging_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target: conn.backup(target)
        print('Backup:',backup)
        columns=[r[1] for r in conn.execute('PRAGMA table_info(materials)') if r[1]!='id']
        rules=approved_rules(conn)
        conn.execute('BEGIN IMMEDIATE')
        try:
            for source in additions:
                item={**source,'project_id':1}
                item['unit_price'],item['price_source']=price_item(item,rules,conn)
                item['total_price']=(round(item['unit_price']*item['quantity'],2)
                                     if item['unit_price'] is not None else None)
                cur=conn.execute('INSERT INTO materials ('+','.join(columns)+') VALUES ('+
                                 ','.join('?' for _ in columns)+')',
                                 tuple(item.get(key) for key in columns))
                item['id']=cur.lastrowid
                conn.execute('INSERT INTO material_changes '
                             '(project_id,material_id,before_json,after_json) VALUES (?,?,?,?)',
                             (1,item['id'],'{}',json.dumps(item,ensure_ascii=False)))
            conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=1")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return len(additions)
    finally:
        conn.close()


if __name__=='__main__':
    run(apply='--apply' in sys.argv)
