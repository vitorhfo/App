"""Correct a hole-location dimension used as width in all RECKITT copies."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

import pymupdf

from config import DB_PATH
from database import get_connection
from manual_validation import linked_drawing
from mass_math import calculated_weight, ceil_kg
from pricing import approved_rules, price_item


FIX_IDS=(46,505,553,606,654,1045,1093,1146,1194)
BAR_IDS=(88,582,1122)


def run(apply=False):
    conn=get_connection()
    try:
        rules=approved_rules(conn)
        changes=[]
        for item_id in FIX_IDS+BAR_IDS:
            before=dict(conn.execute('SELECT * FROM materials WHERE id=?',(item_id,)).fetchone())
            if before['project_id'] not in (2,10,19) or (before['price_source'] or '').startswith('Ajuste manual aprovado'):
                raise ValueError(f'Item inesperado ou preço manual protegido: {item_id}')
            drawing=linked_drawing(conn,before)
            if not drawing: raise ValueError(f'PDF exato indisponível: {item_id}')
            if item_id in FIX_IDS:
                if not before['description'].startswith('FIX BATEDOR BASE') or (
                        drawing['length'],drawing['width'],drawing['thickness'])!=(130,20,3):
                    raise ValueError(f'Cota FIX BATEDOR não confirmada: {item_id}')
                length,width,thickness=130,20,3
            else:
                if not before['description'].startswith('CH BARRA DE CARGA') or drawing['thickness']!=2:
                    raise ValueError(f'Cota CH BARRA não confirmada: {item_id}')
                project=conn.execute('SELECT folder_path FROM projects WHERE id=?',(before['project_id'],)).fetchone()
                rel,page=before['source_page'].rsplit('#page=',1)
                with pymupdf.open(Path(project['folder_path'])/rel) as document:
                    body=document[int(page)-1].get_text()
                if not body.startswith('1') or not all(
                        f'  {dimension}  ' in body for dimension in (60,70)) \
                        or abs(drawing['unit_weight']-0.047825)>1e-5:
                    raise ValueError(f'Vista CH BARRA não confirmada: {item_id}')
                # The page's main view explicitly marks outside 60 × 70; its
                # diagonal, notch and holes explain the larger blank mass.
                length,width,thickness=70,60,2
            after=dict(before)
            after.update(material=drawing['material'],length=length,width=width,
                         thickness=thickness)
            gross=calculated_weight(after)
            if gross<=0 or gross<drawing['unit_weight']:
                raise ValueError(f'Geometria e peso incompatíveis: {item_id}')
            after['unit_weight']=ceil_kg(max(gross,drawing['unit_weight']))
            after['total_weight']=ceil_kg(after['unit_weight']*after['quantity'])
            after['unit_price'],after['price_source']=price_item(after,rules,conn)
            after['total_price']=(round(after['unit_price']*after['quantity'],2)
                                  if after['unit_price'] is not None else None)
            note=(f"Cotas conferidas no PDF: {length:g}×{width:g}×{thickness:g} mm; "
                  f"peso anterior {before['unit_weight']*1000:.3f} g; "
                  f"carimbo {drawing['unit_weight']*1000:.3f} g e bruto {gross*1000:.3f} g.")
            if 'Cotas conferidas no PDF:' not in (after['observation'] or ''):
                after['observation']=' '.join(filter(None,(after['observation'],note)))
            if after!=before: changes.append((before,after))
        print(f'{len(changes)} chapas a corrigir; '+('aplicando' if apply else 'sem alterações'))
        if not apply or not changes: return len(changes)
        backup=Path(DB_PATH).parent/'backups'/f'before_reckitt_hole_width_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target: conn.backup(target)
        print('Backup:',backup)
        conn.execute('BEGIN IMMEDIATE')
        try:
            for before,after in changes:
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
        return len(changes)
    finally:
        conn.close()


if __name__=='__main__': run(apply='--apply' in sys.argv)
