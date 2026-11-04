"""Restore the three OP01 lateral BOM components in both saved project copies."""

from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys

from config import DB_PATH
from database import get_connection
from pricing import approved_rules, price_item
from reader_v3 import process_complete_project


PROJECT_IDS = (3, 20)
NAMES = {'QUADRO COMUNICAÇÃO LATERAL', 'CHAPA COMUNICAÇÃO LATERAL',
         'CANALETA COMUNICAÇÃO LATERAL'}


def run(apply=False):
    conn = get_connection()
    try:
        additions = []
        cache = {}
        for project_id in PROJECT_IDS:
            project = conn.execute('SELECT folder_path FROM projects WHERE id=?',
                                   (project_id,)).fetchone()
            if not project or not Path(project['folder_path']).is_dir():
                raise ValueError(f'Fonte OP01 indisponível: projeto {project_id}')
            root = project['folder_path']
            if root not in cache:
                cache[root] = process_complete_project(root)['materials']
            source = [item for item in cache[root] if item['description'] in NAMES]
            if {item['description'] for item in source} != NAMES or any(
                    item['quantity'] != 2 or '#page=7' not in item['source_page']
                    for item in source):
                raise ValueError('Lista lateral e dois lados não confirmados na página 7')
            existing = {row['description'] for row in conn.execute(
                'SELECT description FROM materials WHERE project_id=?', (project_id,))}
            for item in source:
                if item['description'] not in existing:
                    additions.append((project_id, item))
        print(f'{len(additions)} componentes físicos faltando em {len(PROJECT_IDS)} projetos; '
              + ('aplicando' if apply else 'nenhuma alteração gravada'))
        if not apply or not additions:
            return len(additions)

        backup = Path(DB_PATH).parent / 'backups' / f'before_op01_lateral_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        print('Backup:', backup)
        columns = [row[1] for row in conn.execute('PRAGMA table_info(materials)') if row[1] != 'id']
        rules = approved_rules(conn)
        next_num = {project_id: conn.execute(
            'SELECT COALESCE(MAX(item_num),0) FROM materials WHERE project_id=?',
            (project_id,)).fetchone()[0] + 1 for project_id in PROJECT_IDS}
        conn.execute('BEGIN IMMEDIATE')
        try:
            for project_id, source_item in additions:
                item = {**source_item, 'project_id': project_id,
                        'item_num': next_num[project_id]}
                next_num[project_id] += 1
                # 445 × 1050 is the outside envelope of the assembled lateral,
                # not the cut length of its tube or developed sheet size.
                item['observation'] = (item.get('observation', '').rstrip(' .') +
                                       '. Desenho da lateral: contorno externo 445×1050 mm; '
                                       'não substitui cotas de corte da peça.').lstrip(' .')
                item['unit_price'], item['price_source'] = price_item(item, rules, conn)
                item['total_price'] = (round(item['unit_price'] * item['quantity'], 2)
                                       if item['unit_price'] is not None else None)
                cursor = conn.execute('INSERT INTO materials (' + ','.join(columns) +
                                      ') VALUES (' + ','.join('?' for _ in columns) + ')',
                                      tuple(item.get(key) for key in columns))
                item['id'] = cursor.lastrowid
                conn.execute('INSERT INTO material_changes '
                             '(project_id,material_id,before_json,after_json) VALUES (?,?,?,?)',
                             (project_id, item['id'], '{}', json.dumps(item, ensure_ascii=False)))
                conn.execute("UPDATE projects SET status='PRELIMINAR',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                             (project_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        print('Componentes cadastrados:', len(additions))
        return len(additions)
    finally:
        conn.close()


if __name__ == '__main__':
    run(apply='--apply' in sys.argv)
