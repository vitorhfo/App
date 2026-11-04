"""One-time, audited repair of the saved MOVEL PONTA mixed-material drawing."""

from datetime import datetime
from pathlib import Path
import json
import sqlite3

import pymupdf

from config import DATA_DIR
from database import get_connection
from pricing import approved_rules, price_item
from reader_v3 import cut_table_materials, cut_table_rows, details, finish_materials


PROJECT_ID=16
MATERIAL_ID=954


def record(conn,before,after):
    conn.execute('''INSERT INTO material_changes
        (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
        (PROJECT_ID,after['id'],json.dumps(before,ensure_ascii=False),
         json.dumps(after,ensure_ascii=False)))


def repair():
    conn=get_connection()
    old_row=conn.execute('SELECT * FROM materials WHERE id=? AND project_id=?',
                         (MATERIAL_ID,PROJECT_ID)).fetchone()
    if not old_row:
        conn.close()
        return 'Item original não encontrado.'
    old=dict(old_row)
    if old['drawing_id'].endswith(': corte 1'):
        conn.close()
        return 'Cortes já separados.'
    source,page_number=old['source_page'].rsplit('#page=',1)
    project=conn.execute('SELECT folder_path FROM projects WHERE id=?',
                         (PROJECT_ID,)).fetchone()
    root=Path(project['folder_path']).resolve()
    pdf=(root/source).resolve()
    if not pdf.is_relative_to(root) or not pdf.is_file():
        conn.close()
        raise ValueError('PDF do item salvo não encontrado dentro do projeto.')
    with pymupdf.open(pdf) as document:
        page=document[int(page_number)-1]
        body=page.get_text()
        cuts=cut_table_rows(body,page)
    if len(cuts)!=3 or [row['quantity'] for row in cuts]!=[3,2,1]:
        conn.close()
        raise ValueError('O quadro de corte não corresponde ao desenho verificado.')
    detail=details(body,cuts)
    pieces=finish_materials({'materials':cut_table_materials(
        old['description'],old['quantity'],old['source_page'],
        old['parent_assembly'],pdf.stem,detail,old['raw_code'])})['materials']
    if len(pieces)!=3 or sum(item['total_weight'] for item in pieces)<detail['unit_weight']:
        conn.close()
        raise ValueError('Falha na separação ou na validação do peso.')
    backup_dir=Path(DATA_DIR)/'backups'
    backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/f'before_split_cut_table_{datetime.now():%Y%m%d_%H%M%S}.sqlite'
    with sqlite3.connect(backup) as target:
        conn.backup(target)
    columns=[row[1] for row in conn.execute('PRAGMA table_info(materials)')
             if row[1]!='id']
    rules=approved_rules(conn)
    conn.execute('BEGIN IMMEDIATE')
    try:
        later=[dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=? AND item_num>? ORDER BY item_num DESC',
            (PROJECT_ID,old['item_num']))]
        for before in later:
            after={**before,'item_num':before['item_num']+2}
            conn.execute('UPDATE materials SET item_num=? WHERE id=?',
                         (after['item_num'],before['id']))
            record(conn,before,after)
        for index,piece in enumerate(pieces):
            values={**old,**piece,'item_num':old['item_num']+index,
                    'unit_price':None,'total_price':None,'price_source':''}
            values['unit_price'],values['price_source']=price_item(values,rules,conn)
            if values['unit_price'] is not None:
                values['total_price']=round(values['unit_price']*values['quantity'],2)
            if index==0:
                values['id']=MATERIAL_ID
                conn.execute('UPDATE materials SET '+', '.join(f'{key}=?' for key in columns)+
                             ' WHERE id=?',(*(values.get(key) for key in columns),MATERIAL_ID))
                record(conn,old,values)
            else:
                cursor=conn.execute('INSERT INTO materials ('+','.join(columns)+') VALUES ('+
                    ','.join('?' for _ in columns)+')',
                    tuple(values.get(key) for key in columns))
                values['id']=cursor.lastrowid
                record(conn,{},values)
        conn.execute("DELETE FROM pending_decisions WHERE project_id=? AND item_id=? AND status='PENDENTE'",
                     (PROJECT_ID,MATERIAL_ID))
        conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (PROJECT_ID,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return f'3 cortes separados; backup: {backup}'


if __name__=='__main__':
    print(repair())
