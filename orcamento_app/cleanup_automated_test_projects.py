"""Remove only the upload/assembly fixtures accidentally saved to the live DB."""

from datetime import datetime
from pathlib import Path
import sqlite3
import sys

from config import DB_PATH
from database import get_connection


def run(apply=False):
    conn = get_connection()
    try:
        root = (Path(DB_PATH).parent / 'test_runs').resolve()
        fixtures = []
        for row in conn.execute("SELECT id,name,folder_path FROM projects WHERE name IN "
                                "('Teste de upload','Estrutura de teste') ORDER BY id"):
            path = row['folder_path'] or ''
            if row['name'] == 'Teste de upload':
                if not path or not Path(path).resolve().is_relative_to(root):
                    raise ValueError(f'Projeto {row["id"]} não é fixture de upload')
            elif path:
                raise ValueError(f'Projeto {row["id"]} não é fixture de montagem')
            fixtures.append(row['id'])
        if not fixtures:
            print('Nenhuma fixture no banco principal')
            return 0
        ids = ','.join('?' for _ in fixtures)
        count = conn.execute(f'SELECT COUNT(*) FROM materials WHERE project_id IN ({ids})',
                             fixtures).fetchone()[0]
        print(f'{len(fixtures)} projetos de teste e {count} itens: IDs {fixtures}')
        if not apply:
            return len(fixtures)
        backup = Path(DB_PATH).parent / 'backups' / f'before_test_cleanup_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        print('Backup:', backup)
        conn.execute('BEGIN IMMEDIATE')
        try:
            conn.execute(f'DELETE FROM material_changes WHERE project_id IN ({ids})', fixtures)
            conn.execute(f'DELETE FROM projects WHERE id IN ({ids})', fixtures)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        remaining = conn.execute("SELECT COUNT(*) FROM projects WHERE name IN "
                                 "('Teste de upload','Estrutura de teste')").fetchone()[0]
        if remaining:
            raise AssertionError(f'{remaining} fixtures restantes')
        return len(fixtures)
    finally:
        conn.close()


if __name__ == '__main__':
    run(apply='--apply' in sys.argv)
