"""Refresh only metal prices from the user's selected cost-model rules."""
from datetime import datetime
from pathlib import Path
import sqlite3

from config import DB_PATH
from database import get_connection, init_db
from pricing import approved_rules, price_item


def refresh():
    db=Path(DB_PATH)
    if db.exists():
        backup=db.parent/'backups'/f'metal_before_{datetime.now():%Y%m%d_%H%M%S}.db'
        backup.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(db) as source, sqlite3.connect(backup) as target:
            source.backup(target)
        print(f'Backup: {backup}')
    init_db()
    conn=get_connection()
    changed=0
    affected=set()
    try:
        rules=approved_rules(conn)
        rows=conn.execute("""SELECT * FROM materials WHERE item_type='materia_prima'
            AND group_name IN ('Chapa','Arame','Tubo Quadrado/Retangular','Tubo Redondo')""").fetchall()
        for row in rows:
            item=dict(row)
            if (item.get('price_source') or '').startswith('Ajuste manual aprovado'):
                continue
            value,source=price_item(item,rules,conn)
            if value is None:
                continue  # Ambiguous or unknown profiles remain pending as they are.
            total=round(value*(item['quantity'] or 0),2)
            if (value, total, source)!=(item['unit_price'],item['total_price'],item['price_source']):
                conn.execute('''UPDATE materials SET unit_price=?,total_price=?,price_source=?
                    WHERE id=?''',(value,total,source,item['id']))
                changed+=1
                affected.add(item['project_id'])
        for project_id in affected:
            conn.execute("UPDATE projects SET status='PRELIMINAR' WHERE id=? AND status='FINAL'",(project_id,))
        conn.commit()
    finally:
        conn.close()
    print(f'Preços de metal atualizados: {changed}; projetos afetados: {len(affected)}')


if __name__=='__main__':
    refresh()
