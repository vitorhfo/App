"""Update saved tube profiles from their own linked drawings, with backup."""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import pymupdf

from config import DB_PATH
from database import get_connection
from mass_math import calculated_weight, reconcile_item_weight
from pricing import approved_rules, price_item
from reader_v3 import details, norm


def proposals(conn, project_id):
    project=conn.execute('SELECT folder_path FROM projects WHERE id=?',(project_id,)).fetchone()
    if not project or not project['folder_path']:
        return []
    root=Path(project['folder_path']).resolve()
    if not root.is_dir(): return []
    result=[]
    query=("SELECT * FROM materials WHERE project_id=? AND "
           "group_name IN ('Tubo Quadrado/Retangular','Tubo Redondo') "
           "AND item_type!='subconjunto'")
    for row in conn.execute(query,(project_id,)):
        before=dict(row)
        source=before.get('source_page') or ''
        if '#page=' not in source: continue
        relative,page_text=source.rsplit('#page=',1)
        try: page=int(page_text)-1
        except ValueError: continue
        pdf=(root/relative).resolve()
        if (not pdf.is_relative_to(root) or not pdf.is_file() or
                pdf.suffix.lower()!='.pdf' or
                norm(pdf.stem)!=norm(before.get('drawing_id'))):
            continue
        with pymupdf.open(pdf) as document:
            if not 0<=page<len(document): continue
            found=details(document[page].get_text())
        if not found['length'] or not found['thickness'] or not found['width']:
            continue
        after=dict(before)
        incomplete=not (before['width'] and before['depth'] and before['thickness'])
        if incomplete:
            for key in ('width','depth','thickness'):
                after[key]=found[key]
        if not before['length']:
            after['length']=found['length']
        # Preserve a manually selected variant with a different length.
        if abs(float(after['length'])-found['length'])>0.001:
            continue
        if incomplete or not before['material'] or 'x' not in before['material'].lower():
            after['material']=found['material']
        if not all(after[key]>0 for key in ('width','depth','thickness','length')):
            continue
        calculated=calculated_weight(after)
        if calculated<=0: continue
        changed=any(after[key]!=before[key] for key in
                    ('material','width','depth','thickness','length'))
        if not changed and before['unit_weight']>=calculated-1e-9:
            shape='quadrado' if abs(after['width']-after['depth'])<1e-6 else 'retangular'
            old=f"Tubo {after['width']:g}x{after['depth']:g}x{after['thickness']:g} mm;"
            new=f"Tubo {shape} {after['width']:g}x{after['depth']:g}x{after['thickness']:g} mm;"
            if (before.get('observation') or '').startswith(old):
                after['observation']=before['observation'].replace(old,new,1)
                result.append((before,after,pdf))
            continue
        after['unit_weight']=max(float(before['unit_weight'] or 0),found['unit_weight'])
        reconcile_item_weight(after)
        if before.get('pending_issue')=='Comprimento desenvolvido do tubo não identificado; conferir desenho.':
            after['pending_issue']=''
        result.append((before,after,pdf))
    return result


def run(project_ids,apply=False):
    conn=get_connection()
    try:
        changes=[(project_id,*proposal) for project_id in project_ids
                 for proposal in proposals(conn,project_id)]
        for pid,before,after,pdf in changes:
            print(f'{pid}/{before["id"]} {before["description"]}: '
                  f'{after["material"]}, {after["length"]:g} mm, '
                  f'{before["unit_weight"]*1000:.3f} -> {after["unit_weight"]*1000:.3f} g')
        if not apply:
            print(f'{len(changes)} itens propostos; nenhuma alteração gravada.')
            return len(changes)
        if not changes: return 0
        backup=Path(DB_PATH).parent/'backups'/f'before_tube_profiles_{datetime.now():%Y%m%d_%H%M%S}.sqlite'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        print(f'Backup: {backup}')
        rules=approved_rules(conn)
        fields=('material','width','depth','thickness','length','unit_weight',
                'total_weight','observation','pending_issue','unit_price',
                'total_price','price_source')
        for pid,before,after,_ in changes:
            if before['unit_price'] is None:
                price,source=price_item(after,rules,conn)
                if price is not None:
                    after['unit_price']=price
                    after['total_price']=round(price*after['quantity'],2)
                    after['price_source']=source
            conn.execute('UPDATE materials SET '+','.join(f'{key}=?' for key in fields)+
                         ' WHERE id=? AND project_id=?',
                         [after[key] for key in fields]+[before['id'],pid])
            conn.execute('''INSERT INTO material_changes
                (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
                (pid,before['id'],json.dumps(before,ensure_ascii=False),
                 json.dumps(after,ensure_ascii=False)))
        for pid in set(x[0] for x in changes):
            conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",(pid,))
        conn.commit()
        print(f'{len(changes)} itens atualizados.')
        return len(changes)
    finally:
        conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('project_ids',nargs='+',type=int)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    run(args.project_ids,args.apply)
