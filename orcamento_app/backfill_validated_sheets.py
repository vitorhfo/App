"""Fill saved blank sheet dimensions when the part drawing's mass proves them.

Only an exact linked part PDF is eligible. Other geometry, quantities, and
manual prices are retained. Dry run by default; --apply backs up SQLite.
"""

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


def validated_blank_dimensions(item,drawing):
    if (item.get('group_name')!='Chapa' or item.get('item_type')!='materia_prima'
            or not drawing or drawing.get('cut_table_rows')):
        return {}
    if not all(float(drawing.get(field) or 0)>0 for field in ('length','width','thickness','unit_weight')):
        return {}
    for field in ('length','width','thickness'):
        old=float(item.get(field) or 0)
        expected=float(drawing[field])
        if old>0 and abs(old-expected)>max(0.05,expected*0.005):
            return {}
    trial={**item,'length':drawing['length'],'width':drawing['width'],
           'thickness':drawing['thickness']}
    ratio=calculated_weight(trial)/drawing['unit_weight']
    if not 0.98<=ratio<=1.10:
        return {}
    return {field:drawing[field] for field in ('length','width','thickness')
            if float(item.get(field) or 0)<=0}


def proposals(conn):
    projects={row['id']:dict(row) for row in conn.execute('SELECT * FROM projects')
              if row['folder_path'] and not row['name'].startswith(('Teste de upload','Estrutura de teste'))}
    result=[]
    for row in conn.execute('''SELECT * FROM materials WHERE group_name='Chapa'
        AND item_type='materia_prima' AND (length<=0 OR width<=0 OR thickness<=0)''').fetchall():
        item=dict(row)
        if item['project_id'] not in projects:
            continue
        drawing=linked_drawing(conn,item)
        fields=validated_blank_dimensions(item,drawing)
        if fields:
            result.append((item,fields,drawing))
    return result


def run(apply=False):
    conn=get_connection()
    try:
        found=proposals(conn)
        for item,fields,_ in found:
            print(f'{item["project_id"]}/{item["id"]} {item["description"]}: '+
                  ', '.join(f'{key} {item[key]} -> {value:g}' for key,value in fields.items()))
        print(f'{len(found)} chapas validadas; '+('aplicando' if apply else 'nenhuma alteração gravada'))
        if not apply or not found:
            return len(found)
        backup=Path(DB_PATH).parent/'backups'/f'before_validated_sheets_{datetime.now():%Y%m%d_%H%M%S}.db'
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
                if not (before.get('price_source') or '').startswith('Ajuste manual aprovado'):
                    price,source=price_item(after,rules,conn)
                    if price is not None:
                        after['unit_price']=price
                        after['total_price']=round(price*after['quantity'],2)
                        after['price_source']=source
                changed=[*fields,'unit_weight','total_weight','observation',
                         'unit_price','total_price','price_source']
                conn.execute('UPDATE materials SET '+','.join(f'{key}=?' for key in changed)+
                             ' WHERE id=?',(*(after.get(key) for key in changed),before['id']))
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
