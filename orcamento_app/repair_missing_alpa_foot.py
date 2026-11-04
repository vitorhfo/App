"""Restore the two 420 mm ALPA 5x5 feet proven by both lateral BOMs."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from config import DB_PATH
from database import get_connection
from pricing import approved_rules, price_item
from reader_v3 import process_complete_project


PROJECT_ID=14


def run(apply=False):
    conn=get_connection()
    try:
        project=conn.execute('SELECT folder_path FROM projects WHERE id=?',(PROJECT_ID,)).fetchone()
        if not project or not Path(project['folder_path']).is_dir():
            raise ValueError('Pasta ALPA 5x5 indisponível')
        source=[item for item in process_complete_project(project['folder_path'])['materials']
                if item['description']=='TUBO PEZINHOS']
        if len(source)!=1 or source[0]['quantity']!=2 or source[0]['length']!=420:
            raise ValueError('PDF não confirma dois pés de 420 mm')
        existing=conn.execute("SELECT * FROM materials WHERE project_id=? AND description='TUBO PEZINHOS'",
                              (PROJECT_ID,)).fetchall()
        if existing:
            print('Pés já cadastrados; nenhuma alteração gravada.')
            return 0
        print('Dois pés em uma linha; 420 mm, tubo 25×25×0,9 mm; '+
              ('aplicando' if apply else 'nenhuma alteração gravada'))
        if not apply:
            return 1
        backup=Path(DB_PATH).parent/'backups'/f'before_alpa_feet_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        print('Backup:',backup)
        rules=approved_rules(conn)
        item={**source[0],'project_id':PROJECT_ID,'item_num':2}
        item['unit_price'],item['price_source']=price_item(item,rules,conn)
        item['total_price']=(round(item['unit_price']*item['quantity'],2)
                             if item['unit_price'] is not None else None)
        columns=[row[1] for row in conn.execute('PRAGMA table_info(materials)') if row[1]!='id']
        conn.execute('BEGIN IMMEDIATE')
        try:
            for row in conn.execute('''SELECT * FROM materials WHERE project_id=? AND item_num>=2
                ORDER BY item_num DESC''',(PROJECT_ID,)).fetchall():
                before=dict(row)
                after={**before,'item_num':before['item_num']+1}
                conn.execute('UPDATE materials SET item_num=? WHERE id=?',
                             (after['item_num'],after['id']))
                conn.execute('''INSERT INTO material_changes
                    (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
                    (PROJECT_ID,before['id'],json.dumps(before,ensure_ascii=False),
                     json.dumps(after,ensure_ascii=False)))
            cursor=conn.execute('INSERT INTO materials ('+','.join(columns)+') VALUES ('+
                                ','.join('?' for _ in columns)+')',
                                tuple(item.get(key) for key in columns))
            item['id']=cursor.lastrowid
            conn.execute('''INSERT INTO material_changes
                (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
                (PROJECT_ID,item['id'],'{}',json.dumps(item,ensure_ascii=False)))
            conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (PROJECT_ID,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        print('Item cadastrado:',item['id'])
        return item['id']
    finally:
        conn.close()


if __name__=='__main__':
    run(apply='--apply' in sys.argv)
