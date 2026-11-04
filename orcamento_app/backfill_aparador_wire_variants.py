"""One-time, audited migration of saved copies of the FLEXVERO drawing."""

import sqlite3
from datetime import datetime
from pathlib import Path

from ai_bulk_dimensions import apply_pending_ai_dimensions
from config import DB_PATH
from database import get_connection, init_db


def main():
    conn = get_connection()
    source = conn.execute('SELECT folder_path FROM projects WHERE id=86').fetchone()
    if not source or not source['folder_path']:
        raise RuntimeError('Projeto #86 sem pasta de origem')
    copies = [row['id'] for row in conn.execute(
        'SELECT id FROM projects WHERE folder_path=? ORDER BY id',
        (source['folder_path'],))]
    before = {project_id: [tuple(row) for row in conn.execute(
        'SELECT * FROM materials WHERE project_id=? ORDER BY id', (project_id,))]
        for project_id in copies}
    backup_dir = Path(DB_PATH).parent / 'backups'
    backup_dir.mkdir(exist_ok=True)
    backups = []
    for project_id in copies:
        backup = backup_dir / (
            f'before_aparador_wire_p{project_id}_{datetime.now():%Y%m%d_%H%M%S_%f}.db')
        with sqlite3.connect(backup) as target:
            conn.backup(target)
        backups.append(str(backup))
    conn.close()

    init_db()
    results = {project_id: apply_pending_ai_dimensions(project_id)
               for project_id in copies}
    conn = get_connection()
    try:
        for project_id in copies:
            after = [tuple(row) for row in conn.execute(
                'SELECT * FROM materials WHERE project_id=? ORDER BY id', (project_id,))]
            if after != before[project_id]:
                raise RuntimeError(f'Materiais da cópia #{project_id} mudaram; auditar backup')
            variants = [tuple(row) for row in conn.execute(
                'SELECT code,measure_a,cut_length,diameter,quantity,ai_agreement_count '
                'FROM wire_variants WHERE project_id=? ORDER BY code', (project_id,))]
            print(f'Projeto #{project_id}: {results[project_id]}; variantes={variants}')
    finally:
        conn.close()
    print('Backups:', *backups, sep='\n')


if __name__ == '__main__':
    main()
