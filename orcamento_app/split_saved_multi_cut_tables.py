"""Separate cut-table rows already imported as one piece in MOVEL PONTA.

The PDF is read again for every affected drawing. Existing unrelated rows
remain intact, and every changed row is recorded in material_changes.
"""

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
ITEM_IDS=(866,873,880,895,902,909,923,935,971)


def record(conn,before,after):
    conn.execute('''INSERT INTO material_changes
        (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
        (PROJECT_ID,after['id'],json.dumps(before,ensure_ascii=False),
         json.dumps(after,ensure_ascii=False)))


def read_pieces(root,old):
    source,page_number=old['source_page'].rsplit('#page=',1)
    pdf=(root/source).resolve()
    if not pdf.is_relative_to(root) or not pdf.is_file():
        raise ValueError(f'PDF do item {old["id"]} não encontrado no projeto.')
    with pymupdf.open(pdf) as document:
        page=document[int(page_number)-1]
        body=page.get_text()
        cuts=cut_table_rows(body,page)
    if len(cuts)<2:
        raise ValueError(f'Quadro de corte do item {old["id"]} não tem várias linhas.')
    detail=details(body,cuts)
    pieces=finish_materials({'materials':cut_table_materials(
        old['description'],old['quantity'],old['source_page'],
        old['parent_assembly'],pdf.stem,detail,old['raw_code'])})['materials']
    if (len(pieces)!=len(cuts) or
            any(not item['length'] or not item['unit_weight'] or item['pending_issue']
                for item in pieces) or
            sum(item['total_weight'] for item in pieces)+0.0001<old['total_weight']):
        raise ValueError(f'Item {old["id"]}: corte ou peso incompleto; nenhuma alteração aplicada.')
    return pieces


def repair():
    conn=get_connection()
    project=conn.execute('SELECT folder_path FROM projects WHERE id=?',
                         (PROJECT_ID,)).fetchone()
    root=Path(project['folder_path']).resolve()
    candidates=[]
    for item_id in ITEM_IDS:
        row=conn.execute('SELECT * FROM materials WHERE id=? AND project_id=?',
                         (item_id,PROJECT_ID)).fetchone()
        if not row: raise ValueError(f'Item {item_id} não encontrado.')
        old=dict(row)
        if ': corte ' in old['drawing_id']:
            continue
        if (old['price_source'] or '').startswith('Ajuste manual aprovado'):
            raise ValueError(f'Item {item_id} tem preço manual; revisar antes de separar.')
        candidates.append((old,read_pieces(root,old)))
    if not candidates:
        conn.close()
        return 'Todas as linhas de corte já estão separadas.'
    backup_dir=Path(DATA_DIR)/'backups'
    backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/f'before_multi_cut_split_{datetime.now():%Y%m%d_%H%M%S}.sqlite'
    with sqlite3.connect(backup) as target:
        conn.backup(target)
    columns=[row[1] for row in conn.execute('PRAGMA table_info(materials)')
             if row[1]!='id']
    rules=approved_rules(conn)
    conn.execute('BEGIN IMMEDIATE')
    try:
        inserted=0
        for original,pieces in sorted(candidates,key=lambda pair:pair[0]['item_num']):
            old=dict(conn.execute('SELECT * FROM materials WHERE id=?',
                                  (original['id'],)).fetchone())
            extra=len(pieces)-1
            later=[dict(row) for row in conn.execute(
                'SELECT * FROM materials WHERE project_id=? AND item_num>? ORDER BY item_num DESC',
                (PROJECT_ID,old['item_num']))]
            for before in later:
                after={**before,'item_num':before['item_num']+extra}
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
                    values['id']=old['id']
                    conn.execute('UPDATE materials SET '+', '.join(f'{key}=?' for key in columns)+
                                 ' WHERE id=?',(*(values.get(key) for key in columns),old['id']))
                    record(conn,old,values)
                else:
                    cursor=conn.execute('INSERT INTO materials ('+','.join(columns)+') VALUES ('+
                        ','.join('?' for _ in columns)+')',
                        tuple(values.get(key) for key in columns))
                    values['id']=cursor.lastrowid
                    record(conn,{},values)
                    inserted+=1
            conn.execute("DELETE FROM pending_decisions WHERE project_id=? AND item_id=? AND status='PENDENTE'",
                         (PROJECT_ID,old['id']))
        conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (PROJECT_ID,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return f'{len(candidates)} itens separados; {inserted} linhas adicionadas; backup: {backup}'


if __name__=='__main__':
    print(repair())
