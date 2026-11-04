"""Fill named OUTPROMO detail dimensions in an existing project, preserving edits.

Usage: python backfill_outpromo_details.py PROJECT_ID [--apply]
The dry run lists proposed changes. --apply backs up the SQLite database and
uses the app's audited edit path for each still-empty item.
"""
import argparse
from datetime import datetime
from pathlib import Path
import sqlite3

from app import MaterialUpdate, update_material
from config import DB_PATH
from database import get_connection
from reader_v3 import norm, process_complete_project


def proposed(project_id):
    conn=get_connection()
    project=conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
    if not project:
        conn.close()
        raise ValueError(f'Projeto {project_id} não encontrado.')
    root=Path(project['folder_path'] or '')
    if not root.is_dir():
        conn.close()
        raise ValueError('Pasta original do projeto não encontrada.')
    existing=[dict(row) for row in conn.execute(
        'SELECT * FROM materials WHERE project_id=?',(project_id,))]
    conn.close()
    fresh=process_complete_project(root)
    details={norm(item['description']):item for item in fresh['materials']
             if any(marker in item['observation'] for marker in
                    ('Cotas da peça','Cotas de corte','Cotas gerais do desenho'))}
    result=[]
    for old in existing:
        new=details.get(norm(old['description']))
        if not new: continue
        if norm(old['material'])!=norm(new['material']) or old['quantity']!=new['quantity']:
            continue
        if old['thickness'] and abs(float(old['thickness'])-float(new['thickness'] or 0))>1e-6:
            continue
        if old['width'] and new['width'] and abs(old['width']-new['width'])>1e-6:
            continue
        if old['depth'] and new['depth'] and abs(old['depth']-new['depth'])>1e-6:
            continue
        if 'Cotas gerais do desenho' in new['observation']:
            if 'Cotas gerais do desenho' not in (old.get('observation') or ''):
                result.append((old,new,'overall_note'))
            continue
        if old['length'] or old['unit_weight']:
            continue  # Preserva cotas e pesos já editados.
        result.append((old,new,'cut_geometry'))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project_id',type=int)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    changes=proposed(args.project_id)
    for old,new,kind in changes:
        if kind=='cut_geometry':
            print(f"{old['id']} {old['description']}: {old['length']}x{old['width']} -> "
                  f"{new['length']:g}x{new['width']:g} mm (corte)")
        else:
            print(f"{old['id']} {old['description']}: cotas externas visíveis, "
                  'desenvolvimento pendente')
    if not changes:
        print('Nenhuma peça sem cotas elegível para atualização.')
        return
    if not args.apply:
        print('Use --apply para gravar, com cópia de segurança e histórico.')
        return
    backup=Path(DB_PATH).parent/'backups'/(
        f'orcamento_antes_detalhes_{args.project_id}_{datetime.now():%Y%m%d_%H%M%S}.db')
    backup.parent.mkdir(parents=True,exist_ok=True)
    source=sqlite3.connect(DB_PATH)
    destination=sqlite3.connect(backup)
    try: source.backup(destination)
    finally: source.close(); destination.close()
    print('Cópia de segurança:',backup)
    for old,new,kind in changes:
        note=' '.join(x for x in (old.get('observation'),new['observation']) if x)
        update_fields=dict(observation=note,pending_issue=new['pending_issue'])
        for field in ('thickness','width','depth','radius_diam'):
            if not old[field] and new[field]: update_fields[field]=new[field]
        if kind=='cut_geometry':
            update_fields.update(length=new['length'],width=new['width'],
                                 printing=new['printing'])
        update_material(args.project_id,old['id'],MaterialUpdate(**update_fields))
    print(f'{len(changes)} peça(s) atualizada(s).')


if __name__=='__main__':
    main()
