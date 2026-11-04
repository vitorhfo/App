"""Price saved tubes using the nearest higher approved catalog gauge."""

from datetime import datetime
from pathlib import Path
import json
import sqlite3

from config import DATA_DIR
from database import get_connection
from pricing import approved_rules, price_item


def apply():
    conn=get_connection()
    rules=approved_rules(conn)
    pending=[dict(row) for row in conn.execute('''SELECT * FROM materials
        WHERE group_name IN ('Tubo Quadrado/Retangular','Tubo Redondo')
          AND unit_price IS NULL''')]
    changes=[]
    for before in pending:
        value,source=price_item(before,rules,conn)
        if value is not None and '→' in source:
            after={**before,'unit_price':value,
                   'total_price':round(value*before['quantity'],2),
                   'price_source':source}
            changes.append((before,after))
    if not changes:
        conn.close()
        return 'Nenhum tubo pendente com espessura superior disponível.'
    backup_dir=Path(DATA_DIR)/'backups'
    backup_dir.mkdir(exist_ok=True)
    backup=backup_dir/f'before_rounded_tube_prices_{datetime.now():%Y%m%d_%H%M%S}.sqlite'
    with sqlite3.connect(backup) as target:
        conn.backup(target)
    conn.execute('BEGIN IMMEDIATE')
    try:
        for before,after in changes:
            conn.execute('''UPDATE materials SET unit_price=?,total_price=?,price_source=?
                WHERE id=? AND unit_price IS NULL''',
                (after['unit_price'],after['total_price'],after['price_source'],before['id']))
            conn.execute('''INSERT INTO material_changes
                (project_id,material_id,before_json,after_json) VALUES (?,?,?,?)''',
                (before['project_id'],before['id'],json.dumps(before,ensure_ascii=False),
                 json.dumps(after,ensure_ascii=False)))
        for project_id in {before['project_id'] for before,_ in changes}:
            conn.execute('UPDATE projects SET updated_at=CURRENT_TIMESTAMP WHERE id=?',
                         (project_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return f'{len(changes)} tubos precificados; backup: {backup}'


if __name__=='__main__':
    print(apply())
