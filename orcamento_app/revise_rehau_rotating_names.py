"""Fix only the four misspelled descriptions in the saved REHAU #100 quote."""

from datetime import datetime
from pathlib import Path
import sqlite3

from config import DATA_DIR
from database import get_connection
from quote_rehau_rotating_psai import CODE, build_items


def main():
    conn = get_connection()
    try:
        project = conn.execute('SELECT id FROM projects WHERE code=?', (CODE,)).fetchone()
        if not project:
            raise RuntimeError('Projeto giratório não encontrado.')
        project_id = project['id']
        if conn.execute('SELECT COUNT(*) FROM material_changes WHERE project_id=?',
                        (project_id,)).fetchone()[0]:
            raise RuntimeError('Projeto contém ajustes manuais: revisar antes da migração.')
        actual = conn.execute('SELECT * FROM materials WHERE project_id=? ORDER BY item_num',
                              (project_id,)).fetchall()
        expected = build_items(conn, project_id)
        if len(actual) != len(expected):
            raise RuntimeError('Contagem de itens mudou: revisar antes da migração.')
        descriptions = []
        stable_fields = ('item_num', 'group_name', 'item_type', 'quantity',
                         'length', 'width', 'depth', 'thickness', 'unit_weight',
                         'unit_price', 'total_price', 'price_source')
        for saved, rebuilt in zip(actual, expected):
            if any(saved[field] != rebuilt[field] for field in stable_fields):
                raise RuntimeError(f'Item {saved["item_num"]} mudou além do nome.')
            old = saved['description']
            new = rebuilt['description']
            if old != new:
                if old.replace('MIÓLO', 'MIOLO') != new:
                    raise RuntimeError(f'Descrição inesperada no item {saved["item_num"]}.')
                descriptions.append((new, saved['id']))
        if len(descriptions) != 4:
            raise RuntimeError(f'Esperados quatro nomes, encontrados {len(descriptions)}.')
        backups = Path(DATA_DIR) / 'backups'
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / ('before_rehau_rotating_names_' +
                            datetime.now().strftime('%Y%m%d_%H%M%S') + '.db')
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        conn.executemany('UPDATE materials SET description=? WHERE id=?', descriptions)
        conn.commit()
        print(f'{project_id}: {len(descriptions)} nomes corrigidos; backup {backup}')
    finally:
        conn.close()


if __name__ == '__main__':
    main()
