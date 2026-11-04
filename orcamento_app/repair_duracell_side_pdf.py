"""Link the two saved DURACELL side items to their shared part drawing.

Only repairs rows whose drawing measurements are still empty. All other
materials and user edits stay untouched. Run once after reader_v3 is updated.
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from config import DATA_DIR, DB_PATH
from database import get_connection
from pricing import approved_rules, price_item
from reader_v3 import process_complete_project


PROJECT_ID=12
DRAWING='PSAI LAT. Display Balcão DURACELL.PDF#page=1'


def repair(project_id=PROJECT_ID):
    conn=get_connection()
    project=conn.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
    if not project or 'DURACELL' not in project['name'].upper():
        raise RuntimeError('Projeto DURACELL esperado não encontrado')
    originals=[dict(row) for row in conn.execute(
        "SELECT * FROM materials WHERE project_id=? AND description LIKE 'PSAI LAT.%' ORDER BY id",
        (project_id,))]
    eligible=[row for row in originals if not row['length'] and not row['width']
              and not row['thickness'] and not row['material']
              and 'Desenho da peça não localizado' in (row['pending_issue'] or '')]
    if not eligible:
        conn.close()
        return 0
    if len(eligible)!=2 or len(originals)!=2:
        raise RuntimeError('Laterais salvas diferem do estado conhecido; conferir manualmente')
    parsed=process_complete_project(Path(project['folder_path']))
    details={item['description']:item for item in parsed['materials']
             if item['description'].startswith('PSAI LAT.')}
    if len(details)!=2:
        raise RuntimeError('Leitura atual não encontrou as duas laterais')
    for row in eligible:
        item=details[row['description']]
        if ((item['length'],item['width'],item['thickness'])!=(250.0,150.0,1.0)
                or DRAWING not in item['source_page']):
            raise RuntimeError(f'Cota ou PDF inesperado: {row["description"]}')

    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_dir=Path(DATA_DIR)/'backups'
    backup_dir.mkdir(parents=True,exist_ok=True)
    backup_path=backup_dir/f'orcamento_antes_duracell_laterais_p{project_id}_{stamp}.db'
    with sqlite3.connect(backup_path) as backup:
        conn.backup(backup)
    rules=approved_rules(conn)
    try:
        conn.execute('BEGIN')
        for before in eligible:
            source=details[before['description']]
            updated=dict(before)
            for field in ('material','thickness','radius_diam','width','depth','length',
                          'unit_weight','unit_area','printing','source_page','confidence',
                          'pending_issue'):
                updated[field]=source[field]
            updated['drawing_id']=Path(source['source_page'].split('#',1)[0]).stem
            updated['total_weight']=round(source['unit_weight']*before['quantity'],6)
            updated['total_area']=round(source['unit_area']*before['quantity'],9)
            updated['observation']=(
                'Desenho da peça usado para os lados direito e esquerdo: '
                'cota externa 250×150×1 mm. Área no carimbo 0,054665 m²; '
                'conferir a área de compra/ impressão porque difere da caixa externa.'
            )
            updated['unit_price'],updated['price_source']=price_item(updated,rules,conn)
            updated['total_price']=(round(updated['unit_price']*before['quantity'],2)
                                    if updated['unit_price'] is not None else None)
            columns=('material','thickness','radius_diam','width','depth','length',
                     'unit_weight','total_weight','unit_area','total_area','printing',
                     'source_page','confidence','pending_issue','drawing_id',
                     'observation','unit_price','total_price','price_source')
            conn.execute('UPDATE materials SET '+','.join(f'{key}=?' for key in columns)+
                         ' WHERE id=?',tuple(updated[key] for key in columns)+(before['id'],))
            conn.execute('INSERT INTO material_changes (project_id,material_id,before_json,after_json) '
                         'VALUES (?,?,?,?)',
                         (project_id,before['id'],json.dumps(before,ensure_ascii=False),
                          json.dumps(updated,ensure_ascii=False)))
            conn.execute('DELETE FROM pending_decisions WHERE project_id=? AND item_id=? '
                         "AND description LIKE '%Desenho da peça não localizado%'",
                         (project_id,before['id']))
        conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (project_id,))
        conn.execute('UPDATE markup_configs SET approved=0 WHERE project_id=?',(project_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print(f'Backup: {backup_path}')
    return len(eligible)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('project_id',type=int,nargs='?',default=PROJECT_ID)
    args=parser.parse_args()
    print(f'Itens corrigidos: {repair(args.project_id)}')
