"""One-time, guarded repair of saved BRAHMA project #93.

Keeps its AI-edited seal and all unrelated material IDs. The obsolete acrylic
charge is removed only when it is linked to the known AI candidate.
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from database import DB_PATH, get_connection
from pricing import approved_rules, price_item
from reader_v3 import process_complete_project


PROJECT_ID = 93
PDF = Path(__file__).parent / 'data' / 'brahma_fixture' / 'AMB_2239_25_BRAHMA_ILHA.pdf'
EXISTING = {
    'AMB_2239_25_03_PRT_09',
    'AMB_2239_25_03_PRT_12',
    'AMB_2239_25_03_PRT_21',
    'AMB_2239_25_03_PRT_22',
}


def repair():
    if not PDF.is_file():
        raise RuntimeError('PDF BRAHMA de conferência indisponível')
    fresh = process_complete_project(PDF.parent)
    changed = [row.copy() for row in fresh['materials']
               if row['drawing_id'] in EXISTING or
               ': componente ' in row['drawing_id'] and any(
                   code in row['drawing_id'] for code in ('PRT_12', 'PRT_21', 'PRT_22')) or
               row['drawing_id'].startswith('BRAHMA_ORCAMENTO_MANUAL:')]
    if len(changed) != 14:
        raise RuntimeError(f'Esperados 14 itens visados; encontrados {len(changed)}')
    backup_dir = Path(DB_PATH).parent / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f'before_brahma_quote_p93_{datetime.now():%Y%m%d_%H%M%S}.db'
    conn = get_connection()
    try:
        project = conn.execute('SELECT folder_path FROM projects WHERE id=?',
                               (PROJECT_ID,)).fetchone()
        if not project or 'AMB_2239_25_BRAHMA_ILHA' not in project['folder_path']:
            raise RuntimeError('Projeto salvo não corresponde ao BRAHMA')
        actual_parent = os.path.basename(project['folder_path'].rstrip('\\/'))
        copies = conn.execute('SELECT id FROM projects WHERE folder_path=?',
                              (project['folder_path'],)).fetchall()
        if [row['id'] for row in copies] != [PROJECT_ID]:
            raise RuntimeError('Há outra cópia da mesma origem; revisar todas antes de migrar')
        prior = {row['id']: dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=?', (PROJECT_ID,))}
        existing = {row['drawing_id']: row for row in prior.values()
                    if row['drawing_id'] in EXISTING}
        if set(existing) != EXISTING:
            raise RuntimeError('Itens base mudaram desde a análise')
        candidate = conn.execute('''SELECT * FROM ai_discovered_items
            WHERE project_id=? AND description='LOGO BRAHMA FRONTAL' AND material_id IS NOT NULL''',
            (PROJECT_ID,)).fetchone()
        if not candidate or candidate['material_id'] not in prior:
            raise RuntimeError('Linha extra do logo não é o candidato IA esperado')
        duplicate = prior[candidate['material_id']]
        if (duplicate['drawing_id'] != 'LOGO BRAHMA FRONTAL' or
                duplicate['parent_assembly'] is not None or
                duplicate['item_type'] != 'materia_prima'):
            raise RuntimeError('Linha extra do logo foi alterada; não apagar')
        changes = conn.execute('SELECT before_json,after_json FROM material_changes '
                               'WHERE project_id=? AND material_id=?',
                               (PROJECT_ID, duplicate['id'])).fetchall()
        if len(changes) != 1 or 'Peça encontrada apenas' not in json.loads(changes[0]['after_json'])['observation']:
            raise RuntimeError('Histórico da linha extra não é exclusivamente automático')
        with sqlite3.connect(backup_path) as backup:
            conn.backup(backup)
        columns = [row[1] for row in conn.execute('PRAGMA table_info(materials)')]
        editable = [key for key in columns if key not in ('id', 'project_id', 'item_num')]
        target_ids = set()
        added_ids = []
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('DELETE FROM ai_discovered_items WHERE id=?', (candidate['id'],))
        conn.execute('DELETE FROM pending_decisions WHERE project_id=? AND item_id=?',
                     (PROJECT_ID, duplicate['id']))
        conn.execute('DELETE FROM materials WHERE id=?', (duplicate['id'],))
        next_num = max(row['item_num'] or 0 for row in prior.values()) + 1
        for item in changed:
            item['parent_assembly'] = (item['parent_assembly'] or '').replace(
                PDF.parent.name, actual_parent, 1)
            row_values = [item.get(key) for key in editable]
            old = existing.get(item['drawing_id'])
            if old:
                target_ids.add(old['id'])
                conn.execute('UPDATE materials SET ' + ','.join(f'{key}=?' for key in editable)
                             + ' WHERE id=?', (*row_values, old['id']))
                item_id = old['id']
            else:
                inserted = conn.execute('INSERT INTO materials (project_id,item_num,'
                    + ','.join(editable) + ') VALUES (?,?, '
                    + ','.join('?' for _ in editable) + ')',
                    (PROJECT_ID, next_num, *row_values))
                item_id = inserted.lastrowid
                added_ids.append(item_id)
                next_num += 1
            conn.execute('DELETE FROM pending_decisions WHERE project_id=? AND item_id=?',
                         (PROJECT_ID, item_id))
            if item.get('pending_issue') or item.get('confidence', 1) < .85:
                conn.execute('''INSERT INTO pending_decisions
                    (project_id,item_id,title,description,impact_level,proposed_action)
                    VALUES (?,?,?,?,?,?)''',
                    (PROJECT_ID,item_id,f"Confirmação: {item['description']}",
                     item.get('pending_issue') or 'Confiança de extração abaixo de 85%.',
                     'MEDIO',f"Revisar origem {item['source_page']}"))
            saved = dict(conn.execute('SELECT * FROM materials WHERE id=?', (item_id,)).fetchone())
            if saved['item_type'] == 'subconjunto':
                value, source = None, ''
            else:
                value, source = price_item(saved, approved_rules(conn), conn)
            conn.execute('UPDATE materials SET unit_price=?,total_price=?,price_source=? WHERE id=?',
                         (value,round(value*saved['quantity'],2) if value is not None else None,
                          source,item_id))
        # Only these rows and the automatic duplicate may change.
        after = {row['id']: dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=?', (PROJECT_ID,))}
        untouched = set(prior) - target_ids - {duplicate['id']}
        if any(after.get(item_id) != prior[item_id] for item_id in untouched):
            raise RuntimeError('A migração alterou uma peça não visada')
        if len(after) != len(prior) - 1 + len(added_ids):
            raise RuntimeError('Quantidade de linhas inesperada após migração')
        total = sum(row['total_weight'] or 0 for row in after.values()
                    if row['item_type'] != 'subconjunto')
        conn.execute('''UPDATE pending_decisions SET description=?
            WHERE project_id=? AND title='Peso do conjunto não fecha' ''',
            (f'Soma dos pesos de consumo {total:.3f} kg; carimbo do pacote 151,510 kg. '
             'Conferir cortes, quantidades e peças confirmadas no orçamento manual.', PROJECT_ID))
        conn.commit()
        return {'backup': str(backup_path), 'before': len(prior), 'after': len(after),
                'added': len(added_ids), 'removed_ai_duplicate': duplicate['id'],
                'weight_kg': round(total,3), 'preserved_seal': after[1995] == prior[1995]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def repair_sheet_cut():
    """Backfill the PRT_06 tab dimensions after visual confirmation of page 24."""
    fresh = process_complete_project(PDF.parent)
    code = 'AMB_2239_25_03_PRT_06: corte 3'
    item = next(row.copy() for row in fresh['materials'] if row['drawing_id'] == code)
    conn = get_connection()
    try:
        before = {row['id']: dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=?', (PROJECT_ID,))}
        old = next((row for row in before.values() if row['drawing_id'] == code), None)
        if not old or old['material'] != 'Sheet' or old['length'] != 0:
            raise RuntimeError('A aba da testeira já foi alterada; revisar manualmente')
        backup_dir = Path(DB_PATH).parent / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f'before_brahma_sheet_p93_{datetime.now():%Y%m%d_%H%M%S}.db'
        with sqlite3.connect(backup_path) as backup:
            conn.backup(backup)
        columns = [row[1] for row in conn.execute('PRAGMA table_info(materials)')]
        editable = [key for key in columns if key not in ('id','project_id','item_num')]
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE materials SET ' + ','.join(f'{key}=?' for key in editable)
                     + ' WHERE id=?', (*[item.get(key) for key in editable], old['id']))
        conn.execute('DELETE FROM pending_decisions WHERE project_id=? AND item_id=?',
                     (PROJECT_ID, old['id']))
        saved = dict(conn.execute('SELECT * FROM materials WHERE id=?', (old['id'],)).fetchone())
        value, source = price_item(saved, approved_rules(conn), conn)
        conn.execute('UPDATE materials SET unit_price=?,total_price=?,price_source=? WHERE id=?',
                     (value,round(value*saved['quantity'],2) if value is not None else None,
                      source,old['id']))
        after = {row['id']: dict(row) for row in conn.execute(
            'SELECT * FROM materials WHERE project_id=?', (PROJECT_ID,))}
        if any(after[item_id] != row for item_id,row in before.items()
               if item_id != old['id']):
            raise RuntimeError('A correção da aba alterou outra peça')
        total = sum(row['total_weight'] or 0 for row in after.values()
                    if row['item_type'] != 'subconjunto')
        conn.execute('''UPDATE pending_decisions SET description=?
            WHERE project_id=? AND title='Peso do conjunto não fecha' ''',
            (f'Soma dos pesos de consumo {total:.3f} kg; carimbo do pacote 151,510 kg. '
             'Conferir cortes, quantidades e peças confirmadas no orçamento manual.', PROJECT_ID))
        conn.commit()
        return {'backup': str(backup_path), 'item_id': old['id'],
                'weight_kg': round(total,3), 'unit_weight': after[old['id']]['unit_weight'],
                'price': after[old['id']]['unit_price']}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    print(repair_sheet_cut())
