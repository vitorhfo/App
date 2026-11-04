"""Restore cut dimensions and 1x0 printing on both RECKITT saved copies."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from config import DB_PATH
from database import get_connection
from manual_validation import linked_drawing
from pricing import approved_rules, price_item


ITEM_IDS=(72,96,104,112,537,590,638,686,1077,1130,1178,1226)
ISSUE='Impressão 1x0 consta no PDF, mas a tabela CONTROLV não tem tarifa aprovada para esse processo.'


def run(apply=False):
    conn=get_connection()
    try:
        rules=approved_rules(conn)
        planned=[]
        for item_id in ITEM_IDS:
            before=dict(conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone())
            if before['project_id'] not in (2,10,19) or not before['description'].startswith('PSAI INF TESTEIRA'):
                raise ValueError(f'Item {item_id} não é o painel esperado')
            drawing=linked_drawing(conn,before)
            if not drawing or (drawing['length'],drawing['width'],drawing['thickness'],drawing['printing'])!=(700,700,1,'1x0'):
                raise ValueError(f'PDF não confirma cotas e impressão do item {item_id}')
            if (before['price_source'] or '').startswith('Ajuste manual aprovado'):
                raise ValueError(f'Preço manual no item {item_id}; conferir antes de alterar')
            after=dict(before)
            if not before['length']: after['length']=700
            if not before['width']: after['width']=700
            after['material']=drawing['material']
            after['printing']='1x0'
            quote,_=price_item(after,rules,conn)
            if quote is not None:
                raise ValueError('Regra de preço 1x0 encontrada sem aprovação explícita')
            if before['unit_price'] is not None:
                note=f"Preço anterior R$ {before['unit_price']:.4f} considerava impressão 0x0; desconsiderado até confirmar 1x0."
                if note not in after['observation']:
                    after['observation']=' '.join(filter(None,(after['observation'],note)))
            after['unit_price']=None
            after['total_price']=None
            after['price_source']=''
            if ISSUE not in (after['pending_issue'] or ''):
                after['pending_issue']=' '.join(filter(None,(after['pending_issue'],ISSUE)))
            if after!=before: planned.append((before,after))
        print(f'{len(planned)} painéis a corrigir; '+('aplicando' if apply else 'sem alterações'))
        if not apply or not planned: return len(planned)
        backup=Path(DB_PATH).parent/'backups'/f'before_reckitt_psai_1x0_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target: conn.backup(target)
        print('Backup:',backup)
        conn.execute('BEGIN IMMEDIATE')
        try:
            for before,after in planned:
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
        return len(planned)
    finally:
        conn.close()


if __name__=='__main__': run(apply='--apply' in sys.argv)
