"""Safely split every saved multi-row cut table verified by its own PDF.

Dry run by default. The source workbook/PDF is never changed. Each database
write has a complete SQLite backup and a material_changes audit record.
"""

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

import pymupdf

from config import DB_PATH
from database import get_connection
from pricing import approved_rules, price_item
from reader_v3 import cut_table_rows, norm
from split_saved_multi_cut_tables import read_pieces


def proposals(conn):
    projects={row['id']:dict(row) for row in conn.execute('SELECT * FROM projects')
              if row['folder_path'] and not row['name'].startswith(('Teste de upload','Estrutura de teste'))}
    cache={}
    result=[]
    for row in conn.execute('SELECT * FROM materials ORDER BY project_id,item_num').fetchall():
        old=dict(row)
        project=projects.get(old['project_id'])
        source=old.get('source_page') or ''
        if not project or ': corte ' in (old['drawing_id'] or '') or '#page=' not in source:
            continue
        relative,page=source.rsplit('#page=',1)
        root=Path(project['folder_path']).resolve()
        pdf=(root/relative).resolve()
        if not pdf.is_relative_to(root) or not pdf.is_file() or norm(pdf.stem)!=norm(old['drawing_id']):
            continue
        key=(str(pdf),page)
        if key not in cache:
            with pymupdf.open(pdf) as document:
                sheet=document[int(page)-1]
                cache[key]=cut_table_rows(sheet.get_text(),sheet)
        if len(cache[key])<2:
            continue
        if (old.get('price_source') or '').startswith('Ajuste manual aprovado'):
            raise ValueError(f'Item {old["id"]} tem preço manual impossível de distribuir entre cortes.')
        pieces=read_pieces(root,old)
        result.append((old,pieces))
    return result


def record(conn,before,after):
    conn.execute('''INSERT INTO material_changes
        (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
        (after['project_id'],after['id'],json.dumps(before,ensure_ascii=False),
         json.dumps(after,ensure_ascii=False)))


def run(apply=False):
    conn=get_connection()
    try:
        planned=proposals(conn)
        by_project=Counter(old['project_id'] for old,_ in planned)
        added=sum(len(pieces)-1 for _,pieces in planned)
        print(f'{len(planned)} linhas agregadas; {added} linhas de corte a acrescentar; projetos {dict(by_project)}')
        if not apply or not planned:
            return len(planned),added
        backup=Path(DB_PATH).parent/'backups'/f'before_all_collapsed_cuts_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        print('Backup:',backup)
        columns=[row[1] for row in conn.execute('PRAGMA table_info(materials)') if row[1]!='id']
        rules=approved_rules(conn)
        conn.execute('BEGIN IMMEDIATE')
        try:
            for original,pieces in planned:
                old=dict(conn.execute('SELECT * FROM materials WHERE id=?',(original['id'],)).fetchone())
                extra=len(pieces)-1
                later=[dict(row) for row in conn.execute('''SELECT * FROM materials
                    WHERE project_id=? AND item_num>? ORDER BY item_num DESC''',
                    (old['project_id'],old['item_num'])).fetchall()]
                for before in later:
                    after={**before,'item_num':before['item_num']+extra}
                    conn.execute('UPDATE materials SET item_num=? WHERE id=?',
                                 (after['item_num'],before['id']))
                    record(conn,before,after)
                for index,piece in enumerate(pieces):
                    after={**old,**piece,'item_num':old['item_num']+index,
                           'unit_price':None,'total_price':None,'price_source':''}
                    after['unit_price'],after['price_source']=price_item(after,rules,conn)
                    if after['unit_price'] is not None:
                        after['total_price']=round(after['unit_price']*after['quantity'],2)
                    if 'FERRO LAMINADO' in norm(after['material']) and after['unit_price'] is None:
                        after['pending_issue']='Ferro chato sem tarifa por kg aprovada; conferir custo.'
                    if index==0:
                        after['id']=old['id']
                        conn.execute('UPDATE materials SET '+','.join(f'{key}=?' for key in columns)+
                                     ' WHERE id=?',(*(after.get(key) for key in columns),old['id']))
                        record(conn,old,after)
                    else:
                        cursor=conn.execute('INSERT INTO materials ('+','.join(columns)+') VALUES ('+
                                            ','.join('?' for _ in columns)+')',
                                            tuple(after.get(key) for key in columns))
                        after['id']=cursor.lastrowid
                        record(conn,{},after)
                conn.execute('''DELETE FROM pending_decisions WHERE project_id=? AND item_id=?
                    AND status='PENDENTE' AND title LIKE 'Confirmação:%' ''',
                    (old['project_id'],old['id']))
                conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (old['project_id'],))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        print('Atualização concluída.')
        return len(planned),added
    finally:
        conn.close()


if __name__=='__main__':
    run(apply='--apply' in sys.argv)
