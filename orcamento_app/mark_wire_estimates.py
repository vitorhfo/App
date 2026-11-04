"""Flag previously estimated wire lengths for drawing review."""

from datetime import datetime
from pathlib import Path
import sqlite3

from config import DATA_DIR
from database import get_connection


def mark():
    conn=get_connection()
    rows=conn.execute('''SELECT * FROM materials WHERE group_name='Arame'
        AND observation LIKE '%Comprimento nominal estimado%'
        AND COALESCE(pending_issue,'') NOT LIKE '%Comprimento de corte estimado%' ''').fetchall()
    if not rows:
        conn.close()
        return {'marked':0,'backup':None}
    backup_dir=Path(DATA_DIR)/'backups'
    backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/f'before_wire_review_flags_{datetime.now():%Y%m%d_%H%M%S}.sqlite'
    with sqlite3.connect(backup) as target:
        conn.backup(target)
    issue='Comprimento de corte estimado pelo peso; confirmar no desenho.'
    conn.execute('BEGIN IMMEDIATE')
    try:
        for row in rows:
            conn.execute('''UPDATE materials SET confidence=MIN(COALESCE(confidence,1),0.75),
                pending_issue=? WHERE id=?''',
                (' '.join(x for x in (row['pending_issue'] or '',issue) if x),row['id']))
            conn.execute('''INSERT INTO pending_decisions
                (project_id,item_id,title,description,impact_level,proposed_action)
                VALUES (?,?,?,?,?,?)''',
                (row['project_id'],row['id'],f'Conferir comprimento: {row["description"]}',
                 issue,'MEDIO',f'Verificar {row["source_page"]}'))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {'marked':len(rows),'backup':str(backup)}


if __name__=='__main__':
    print(mark())
