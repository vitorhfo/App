"""Flag the verified title-area conflict on the saved DURACELL drawer."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3

from config import DB_PATH
from database import get_connection


def run():
    conn=get_connection()
    try:
        row=conn.execute('SELECT * FROM materials WHERE id=765 AND project_id=12').fetchone()
        if row is None:
            raise ValueError('Gaveta DURACELL salva nao encontrada')
        before=dict(row)
        if (before['length'],before['width'],before['thickness'])!=(281.2,246.2,1.0):
            raise ValueError('Cotas da gaveta mudaram; conferir antes de sinalizar')
        envelope=before['length']*before['width']/1_000_000
        if before['unit_area']<=envelope*1.05:
            raise ValueError('Divergencia de area nao confirmada')
        note=(f'Área do carimbo {before["unit_area"]:.6f} m² excede o envelope '
              f'{envelope:.6f} m²; conferir se é área de superfície ou de corte '
              'antes de aprovar o preço.')
        if note in (before.get('pending_issue') or ''):
            print('Pendencia ja registrada.')
            return
        backup=(Path(DB_PATH).parent/'backups'/
                f'duracell_gaveta_area_before_{datetime.now():%Y%m%d_%H%M%S}.db')
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(DB_PATH) as source,sqlite3.connect(backup) as target:
            source.backup(target)
        after={**before,'pending_issue':' '.join(
            x for x in (before.get('pending_issue') or '',note) if x)}
        conn.execute('UPDATE materials SET pending_issue=? WHERE id=765',
                     (after['pending_issue'],))
        conn.execute('''INSERT INTO material_changes
            (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
            (12,765,json.dumps(before,ensure_ascii=False),
             json.dumps(after,ensure_ascii=False)))
        conn.commit()
        print(f'Backup: {backup}')
        print(after['pending_issue'])
    finally:
        conn.close()


if __name__=='__main__':
    run()
