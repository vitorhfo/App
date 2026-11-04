"""Fill missing sheet/wire measurements from their linked part drawings."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import pymupdf

from config import DB_PATH
from database import get_connection
from mass_math import reconcile_item_weight
from pricing import approved_rules, price_item
from reader_v3 import details, norm, parameterized_details


FIELDS={'Chapa':{'length':'length','width':'width','thickness':'thickness',
                  'unit_weight':'unit_weight'},
        'Polímero/PSAI':{'length':'length','width':'width','thickness':'thickness',
                         'unit_weight':'unit_weight'},
        'Arame':{'length':'length','radius_diam':'diameter',
                 'unit_weight':'unit_weight'}}


def proposals(conn,project_id,item_id=None):
    project=conn.execute('SELECT folder_path FROM projects WHERE id=?',(project_id,)).fetchone()
    if not project or not project['folder_path']:
        raise ValueError('Projeto sem pasta de desenhos vinculada')
    root=Path(project['folder_path']).resolve()
    query="SELECT * FROM materials WHERE project_id=? AND group_name IN ('Chapa','Polímero/PSAI','Arame')"
    params=[project_id]
    if item_id is not None:
        query+=' AND id=?'
        params.append(item_id)
    for row in conn.execute(query,params):
        item=dict(row)
        source=item.get('source_page') or ''
        if '#page=' not in source:
            continue
        relative,page_text=source.rsplit('#page=',1)
        try:
            page=int(page_text)-1
        except ValueError:
            continue
        pdf=(root/relative).resolve()
        if not pdf.is_relative_to(root) or not pdf.is_file() or pdf.suffix.lower()!='.pdf':
            continue
        # A BOM row may point to its parent drawing when the part sheet is
        # absent. Its title-block weight belongs to the assembly, not the row.
        if norm(pdf.stem)!=norm(item.get('drawing_id')):
            continue
        with pymupdf.open(pdf) as doc:
            if not 0<=page<len(doc):
                continue
            drawing_page=doc[page]
            text=drawing_page.get_text()
            found=(parameterized_details(text,item['description']) or
                   details(text,page=drawing_page))
        changes={field:found[key] for field,key in FIELDS[item['group_name']].items()
                 if (item.get(field) or 0)<=0 and (found[key] or 0)>0}
        if changes:
            yield item,changes,pdf


def run(project_id,item_id=None,apply=False):
    conn=get_connection()
    try:
        changes=list(proposals(conn,project_id,item_id))
        for item,fields,pdf in changes:
            print(f'{item["id"]} {item["description"]}: '+', '.join(
                f'{key} {item[key]} -> {value:g}' for key,value in fields.items()))
        if not apply:
            print(f'{len(changes)} itens encontrados; nenhuma alteração gravada.')
            return
        if changes:
            db=Path(DB_PATH)
            backup=db.parent/'backups'/f'drawing_details_before_{datetime.now():%Y%m%d_%H%M%S}.db'
            backup.parent.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(db) as source, sqlite3.connect(backup) as target:
                source.backup(target)
            print(f'Backup: {backup}')
        rules=approved_rules(conn)
        for before,fields,_ in changes:
            item={**before,**fields}
            reconcile_item_weight(item,pdf_weight=before['unit_weight'])
            if not item.get('total_weight'):
                item['total_weight']=round((item['unit_weight'] or 0)*(item['quantity'] or 0),4)
            if not (item.get('price_source') or '').startswith('Ajuste manual aprovado'):
                price,source=price_item(item,rules,conn)
                if price is not None:
                    item['unit_price']=price
                    item['total_price']=round(price*(item['quantity'] or 0),2)
                    item['price_source']=source
            columns=list(dict.fromkeys([*fields,'unit_weight','total_weight','observation',
                                        'unit_price','total_price','price_source']))
            conn.execute('UPDATE materials SET '+','.join(f'{key}=?' for key in columns)+' WHERE id=?',
                         [item.get(key) for key in columns]+[item['id']])
            conn.execute('''INSERT INTO material_changes
                (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
                (project_id,item['id'],json.dumps(before,ensure_ascii=False),
                 json.dumps(item,ensure_ascii=False)))
        if changes:
            conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (project_id,))
        conn.commit()
        print(f'{len(changes)} itens atualizados.')
    finally:
        conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('project_id',type=int)
    parser.add_argument('--item-id',type=int)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    run(args.project_id,args.item_id,args.apply)
