"""Fix evidenced raw/bought categories in saved PDFs, including manual rows."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from config import DB_PATH
from database import get_connection
from mass_math import reconcile_item_weight
from pricing import approved_rules, price_item
from reader_v3 import material_cell_spec, norm


def corrected_fields(item):
    description=norm(item.get('description'))
    material=norm(item.get('material'))
    fields={}
    if 'FERRO CHATO' in material:
        spec=material_cell_spec(item['material'])
        if spec['width']<=0 or spec['thickness']<=0:
            return {}
        fields.update(group_name='Chapa',item_type='materia_prima')
        for key in ('width','thickness'):
            if float(item.get(key) or 0)<=0:
                fields[key]=spec[key]
    elif 'PONTEIRA INTERNA' in description and 'PVC' in material:
        fields.update(group_name='Polímero/PSAI',item_type='comprado')
    elif 'BOLSA PVC' in description and 'CHAPA DE PVC' in material:
        fields.update(group_name='Polímero/PSAI',item_type='comprado')
    return {key:value for key,value in fields.items() if item.get(key)!=value}


def run(apply=False):
    conn=get_connection()
    try:
        planned=[(dict(row),corrected_fields(dict(row))) for row in
                 conn.execute('SELECT * FROM materials').fetchall()]
        planned=[entry for entry in planned if entry[1]]
        for item,fields in planned:
            print(item['project_id'],item['id'],item['description'],fields)
        print(f'{len(planned)} classificações/cotas corrigíveis; '+
              ('aplicando' if apply else 'nenhuma alteração gravada'))
        if not apply or not planned:
            return len(planned)
        backup=Path(DB_PATH).parent/'backups'/f'before_material_categories_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        print('Backup:',backup)
        rules=approved_rules(conn)
        conn.execute('BEGIN IMMEDIATE')
        try:
            for before,fields in planned:
                after={**before,**fields}
                if after['item_type']=='materia_prima' and after['group_name']=='Chapa':
                    reconcile_item_weight(after,pdf_weight=before['unit_weight'])
                    if not after.get('length'):
                        issue=after.get('pending_issue') or ''
                        after['pending_issue']=' '.join(x for x in (issue,
                            'Ferro chato: comprimento de corte ainda não localizado.') if x)
                if not (before.get('price_source') or '').startswith('Ajuste manual aprovado'):
                    after['unit_price'],after['price_source']=price_item(after,rules,conn)
                    after['total_price']=(round(after['unit_price']*after['quantity'],2)
                                          if after['unit_price'] is not None else None)
                columns=list(dict.fromkeys([*fields,'unit_weight','total_weight','observation',
                                            'pending_issue','unit_price','total_price','price_source']))
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
        return len(planned)
    finally:
        conn.close()


if __name__=='__main__':
    run(apply='--apply' in sys.argv)
