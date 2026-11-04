"""Apply the shared R$ 6.80/m price to saved porta-preço/porta-etiqueta."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from config import DB_PATH
from database import get_connection
from pricing import approved_rules, norm, porta_linear_length_mm, price_item


def proposals(conn):
    rules=approved_rules(conn)
    rows=conn.execute("SELECT * FROM materials WHERE item_type='comprado'").fetchall()
    for row in rows:
        before=dict(row)
        length=porta_linear_length_mm(before)
        if length<=0:
            continue
        after=dict(before)
        if not (after.get('length') or 0):
            after['length']=length
        if 'PORTA PRECO' in norm(after['description']):
            after['group_name']='Acessórios/Outros Comprados'
        if not (after.get('price_source') or '').startswith('Ajuste manual aprovado'):
            value,source=price_item(after,rules,conn)
            after['unit_price']=value
            after['total_price']=round(value*after['quantity'],2) if value is not None else None
            after['price_source']=source
        fields=('length','group_name','unit_price','total_price','price_source')
        changed={field:after[field] for field in fields if after[field]!=before[field]}
        if changed:
            yield before,after,changed


def run(apply=False):
    conn=get_connection()
    try:
        rule=conn.execute("SELECT * FROM price_rules WHERE rule_key='acess_porta_etiqueta'").fetchone()
        if not rule or not rule['approved'] or not rule['is_active'] or abs(rule['value']-6.8)>1e-9:
            raise RuntimeError('A regra aprovada de porta etiqueta precisa ser R$ 6,80/m')
        changes=list(proposals(conn))
        for before,_,fields in changes:
            print(f'{before["id"]} {before["description"]}: '+', '.join(
                f'{key}={value}' for key,value in fields.items()))
        if not apply:
            print(f'{len(changes)} itens encontrados; nenhuma alteração gravada.')
            return
        if not changes and rule['name']=='Porta Preço / Porta Etiqueta':
            print('Nenhuma alteração necessária.')
            return
        path=Path(DB_PATH)
        backup=path.parent/'backups'/f'porta_linear_before_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(path) as source,sqlite3.connect(backup) as target:
            source.backup(target)
        print(f'Backup: {backup}')
        conn.execute("UPDATE price_rules SET name=?,notes=? WHERE rule_key='acess_porta_etiqueta'",
                     ('Porta Preço / Porta Etiqueta','Ambos usam R$ 6,80 por metro linear'))
        for before,after,fields in changes:
            conn.execute('UPDATE materials SET '+','.join(f'{key}=?' for key in fields)+' WHERE id=?',
                         [fields[key] for key in fields]+[before['id']])
            conn.execute('INSERT INTO material_changes '
                         '(project_id,material_id,before_json,after_json) VALUES (?,?,?,?)',
                         (before['project_id'],before['id'],json.dumps(before,ensure_ascii=False),
                          json.dumps(after,ensure_ascii=False)))
        projects={before['project_id'] for before,_,_ in changes}
        for project_id in projects:
            conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                         (project_id,))
        conn.commit()
        print(f'{len(changes)} itens atualizados em {len(projects)} projetos.')
    finally:
        conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    run(parser.parse_args().apply)
