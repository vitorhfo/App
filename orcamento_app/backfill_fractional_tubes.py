"""Reconcile saved round-tube inch profiles with exact linked part drawings."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from config import DB_PATH
from database import get_connection
from manual_validation import linked_drawing
from mass_math import calculated_weight, reconcile_item_weight
from pricing import approved_rules, price_item


def candidate_changes(item,drawing):
    if (item.get('group_name')!='Tubo Redondo' or not drawing or
            not all(float(drawing.get(key) or 0)>0 for key in
                    ('length','diameter','thickness','unit_weight')) or
            not ('TUBO' in (drawing.get('material') or '').upper() and
                 '/' in (drawing.get('material') or ''))):
        return {}
    trial={**item,'material':drawing['material'],'length':drawing['length'],
           'radius_diam':drawing['diameter'],'thickness':drawing['thickness']}
    gross=calculated_weight(trial)
    ratio=gross/drawing['unit_weight']
    if not 0.95<=ratio<=1.05 and (item.get('length') or 0)>0 and (item.get('radius_diam') or 0)>0:
        # Conflicting measured dimensions require corroboration by title mass.
        return {}
    changes={}
    for key,source in (('length','length'),('radius_diam','diameter'),('thickness','thickness')):
        expected=float(drawing[source])
        if abs(float(item.get(key) or 0)-expected)>max(0.05,expected*0.002):
            changes[key]=expected
    material=item.get('material') or ''
    if 'mm/8"' in material or material.count('Ø')>1:
        changes['material']=drawing['material']
    return changes


def proposals(conn):
    result=[]
    for row in conn.execute("SELECT * FROM materials WHERE group_name='Tubo Redondo'").fetchall():
        item=dict(row)
        drawing=linked_drawing(conn,item)
        fields=candidate_changes(item,drawing)
        if fields:
            result.append((item,fields,drawing))
    return result


def run(apply=False):
    conn=get_connection()
    try:
        found=proposals(conn)
        for item,fields,_ in found:
            print(f'{item["project_id"]}/{item["id"]}: '+', '.join(
                f'{key} {item.get(key)} -> {value}' for key,value in fields.items()))
        print(f'{len(found)} tubos fracionários; '+('aplicando' if apply else 'nenhuma alteração gravada'))
        if not apply or not found:
            return len(found)
        backup=Path(DB_PATH).parent/'backups'/f'before_fractional_tubes_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        print('Backup:',backup)
        rules=approved_rules(conn)
        conn.execute('BEGIN IMMEDIATE')
        try:
            for before,fields,drawing in found:
                after={**before,**fields}
                reconcile_item_weight(after,pdf_weight=drawing['unit_weight'])
                issue=after.get('pending_issue') or ''
                if 'Comprimento desenvolvido do tubo não identificado' in issue:
                    issue=issue.replace('Comprimento desenvolvido do tubo não identificado; conferir desenho.','').strip()
                gross=calculated_weight(after)
                if gross>drawing['unit_weight']*1.10:
                    issue=' '.join(x for x in (issue,
                        'Peso do tubo calculado acima do carimbo; conferir espessura indicada no desenho.') if x)
                after['pending_issue']=issue
                if not (before.get('price_source') or '').startswith('Ajuste manual aprovado'):
                    price,source=price_item(after,rules,conn)
                    if price is not None:
                        after['unit_price']=price
                        after['total_price']=round(price*after['quantity'],2)
                        after['price_source']=source
                columns=[*fields,'unit_weight','total_weight','observation','pending_issue',
                         'unit_price','total_price','price_source']
                columns=list(dict.fromkeys(columns))
                conn.execute('UPDATE materials SET '+','.join(f'{key}=?' for key in columns)+
                             ' WHERE id=?',(*(after.get(key) for key in columns),before['id']))
                conn.execute('''INSERT INTO material_changes
                    (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
                    (before['project_id'],before['id'],json.dumps(before,ensure_ascii=False),
                     json.dumps(after,ensure_ascii=False)))
                conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (before['project_id'],))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return len(found)
    finally:
        conn.close()


if __name__=='__main__':
    run(apply='--apply' in sys.argv)
