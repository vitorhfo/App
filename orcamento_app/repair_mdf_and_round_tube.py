"""Correct two saved, exact-PDF part dimensions without resetting other edits."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from config import DB_PATH
from database import get_connection
from manual_validation import linked_drawing


def run(apply=False):
    conn=get_connection()
    try:
        updates=[]
        for item_id in (736,989):
            row=conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone()
            if not row:
                raise ValueError(f'Item {item_id} ausente')
            item=dict(row)
            drawing=linked_drawing(conn,item)
            if not drawing:
                raise ValueError(f'PDF da peça {item_id} não encontrado')
            after=dict(item)
            if item_id==736:
                if item['material']!='CHAPA MDF BRANCO' or item['project_id']!=11:
                    raise ValueError('MDF diferente do caso verificado')
                geometry=(drawing['length'],drawing['width'],drawing['thickness'])
                if geometry!=(700,450,9):
                    raise ValueError('Cotas do MDF diferentes do desenho verificado')
                for key in ('length','width','thickness'):
                    if not item[key]: after[key]=drawing[key]
                note='MDF 700×450×9 mm lido no desenho; densidade de compra ainda pendente.'
                if note not in after['observation']:
                    after['observation']=' '.join(filter(None,(after['observation'],note)))
            else:
                if item['project_id']!=17 or item['group_name']!='Tubo Redondo':
                    raise ValueError('Tubo diferente do caso verificado')
                if abs(drawing['diameter']-25.4)>0.01 or abs(drawing['thickness']-1.5)>0.01:
                    raise ValueError('Perfil em polegadas não confirmado no PDF')
                if abs(item['radius_diam']-1)>0.01 or item['thickness'] not in (0,1.5):
                    raise ValueError('Alteração manual posterior do tubo; conferir individualmente')
                after['radius_diam']=25.4
                after['thickness']=1.5
            if after!=item:
                updates.append((item,after))
        print(f'{len(updates)} leituras salvas a corrigir; '+('aplicando' if apply else 'sem alterações'))
        if not apply or not updates:
            return len(updates)
        backup=Path(DB_PATH).parent/'backups'/f'before_mdf_round_tube_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        print('Backup:',backup)
        conn.execute('BEGIN IMMEDIATE')
        try:
            for before,after in updates:
                keys=[key for key in after if key not in ('id','project_id') and after[key]!=before[key]]
                conn.execute('UPDATE materials SET '+','.join(f'{key}=?' for key in keys)+' WHERE id=?',
                             tuple(after[key] for key in keys)+(before['id'],))
                conn.execute('INSERT INTO material_changes '
                             '(project_id,material_id,before_json,after_json) VALUES (?,?,?,?)',
                             (before['project_id'],before['id'],json.dumps(before,ensure_ascii=False),
                              json.dumps(after,ensure_ascii=False)))
                conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (before['project_id'],))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return len(updates)
    finally:
        conn.close()


if __name__=='__main__':
    run(apply='--apply' in sys.argv)
