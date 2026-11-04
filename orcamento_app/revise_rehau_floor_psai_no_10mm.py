"""Apply the user's no-10-mm-plate correction to saved REHAU project #99.

Aborts if another material or a manual edit differs from the original quote.
Keeps material IDs and previously saved photo quotes intact.
"""

from datetime import datetime
from pathlib import Path
import json
import sqlite3

from config import DATA_DIR
from database import get_connection
from quote_rehau_floor_psai import CODE, build_items


def apply_revision():
    conn = get_connection()
    project = conn.execute('SELECT id,notes FROM projects WHERE code=?', (CODE,)).fetchone()
    if not project:
        raise RuntimeError('Projeto PSAI de dez rolos não encontrado.')
    project_id = project['id']
    if conn.execute('SELECT COUNT(*) FROM material_changes WHERE project_id=?',
                    (project_id,)).fetchone()[0]:
        raise RuntimeError('Há edições manuais; reconciliar antes de alterar.')
    existing = list(conn.execute('SELECT * FROM materials WHERE project_id=? '
                                 'ORDER BY item_num,id', (project_id,)))
    forbidden = [r for r in existing if r['thickness'] == 10]
    if not forbidden:
        conn.close()
        return {'project_id': project_id, 'status': 'already_updated'}
    if len(forbidden) != 1 or forbidden[0]['description'] != (
            'lastro metálico baixo dentro do quadro tubular — 400×100×10 mm'):
        raise RuntimeError('Chapa de 10 mm não corresponde à hipótese original.')
    desired = build_items(conn, project_id)
    old_kept = [r for r in existing if r['id'] != forbidden[0]['id']]
    if len(old_kept) != len(desired):
        raise RuntimeError('Quantidade de itens diferente; revisar o projeto salvo.')
    for old, new in zip(old_kept, desired):
        for key, value in new.items():
            if key in ('description', 'item_num', 'drawing_id'):
                continue
            if old[key] != value:
                raise RuntimeError(f'Item {old["id"]} alterado no campo {key}; '
                                   'migração interrompida.')
        if old['group_name'] == 'Tubo Quadrado/Retangular':
            valid_old = '—' in old['description'] and 'corte' in old['description']
        elif old['group_name'] == 'Polímero/PSAI':
            valid_old = 'PSAI preto 2 mm —' in old['description']
        elif old['group_name'] == 'Chapa':
            valid_old = 'chapas de reforço e fixação dos rodízios' in old['description']
        else:
            valid_old = old['description'] == new['description']
        if not valid_old:
            raise RuntimeError(f'Descrição manual ou inesperada no item {old["id"]}.')
    before_old = {id_: conn.execute(
        'SELECT COUNT(*),ROUND(SUM(total_price),2) FROM materials WHERE project_id=?',
        (id_,)).fetchone()[:] for id_ in (97, 98)}
    backup_path = (Path(DATA_DIR) / 'backups' /
                   f'before_rehau_psai_no_10mm_{datetime.now():%Y%m%d_%H%M%S}.db')
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(backup_path) as backup:
        conn.backup(backup)
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute('DELETE FROM materials WHERE id=?', (forbidden[0]['id'],))
        for old, new in zip(old_kept, desired):
            conn.execute('''UPDATE materials SET item_num=?,drawing_id=?,description=?
                            WHERE id=?''',
                         (new['item_num'], new['drawing_id'],
                          new['description'], old['id']))
        old_note = 'com grade interna, lastro baixo e tampa de PSAI'
        if old_note not in (project['notes'] or ''):
            raise RuntimeError('Nota do projeto não corresponde à versão anterior.')
        conn.execute('UPDATE projects SET notes=REPLACE(notes, ?, ?) WHERE id=?',
                     (old_note, 'com grade interna e tampa de PSAI, sem chapa de lastro',
                      project_id))
        conn.execute('''UPDATE pending_decisions
                        SET description=description ||
                          ' Após retirar a chapa de 10 mm, confirmar anti-tombo em protótipo.'
                        WHERE project_id=? AND title='Estabilidade e uso público' ''',
                     (project_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    after = list(conn.execute('SELECT * FROM materials WHERE project_id=? '
                              'ORDER BY item_num,id', (project_id,)))
    if len(after) != len(desired) or any(
            any(row[key] != value for key, value in target.items())
            for row, target in zip(after, desired)):
        raise RuntimeError('A conferência após a migração não fechou.')
    after_old = {id_: conn.execute(
        'SELECT COUNT(*),ROUND(SUM(total_price),2) FROM materials WHERE project_id=?',
        (id_,)).fetchone()[:] for id_ in (97, 98)}
    if before_old != after_old:
        raise RuntimeError('Outra variante REHAU foi alterada.')
    result = {'project_id': project_id, 'status': 'updated',
              'removed_material_id': forbidden[0]['id'],
              'backup': str(backup_path), 'materials': len(after),
              'material_total': round(sum(r['total_price'] for r in after), 2),
              'other_variants': after_old}
    conn.close()
    return result


if __name__ == '__main__':
    print(json.dumps(apply_revision(), ensure_ascii=False, indent=2))
