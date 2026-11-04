"""Compare the pre-audit SQLite snapshot with the present saved projects."""

from collections import Counter
from pathlib import Path
import sqlite3

from config import DB_PATH


def run():
    backups=sorted((Path(DB_PATH).parent/'backups').glob('before_all_collapsed_cuts_*.db'))
    if not backups: raise FileNotFoundError('Backup inicial da auditoria não encontrado')
    before=sqlite3.connect(backups[0]); before.row_factory=sqlite3.Row
    after=sqlite3.connect(DB_PATH); after.row_factory=sqlite3.Row
    try:
        # Automated test projects are disposable fixtures, not saved customer work.
        fixtures={'Teste de upload','Estrutura de teste'}
        original={row['id']:dict(row) for row in before.execute(
            'SELECT m.* FROM materials m JOIN projects p ON p.id=m.project_id')
            if before.execute('SELECT name FROM projects WHERE id=?',
                              (row['project_id'],)).fetchone()['name'] not in fixtures}
        current={row['id']:dict(row) for row in after.execute(
            'SELECT m.* FROM materials m JOIN projects p ON p.id=m.project_id')
            if after.execute('SELECT name FROM projects WHERE id=?',
                             (row['project_id'],)).fetchone()['name'] not in fixtures}
        deleted=set(original)-set(current)
        inserted=set(current)-set(original)
        changes=Counter()
        changed_ids=[]
        for item_id,row in original.items():
            newer=current.get(item_id)
            if newer is None: continue
            fields=[key for key in row if row[key]!=newer[key]]
            if fields:
                changed_ids.append(item_id)
                changes.update(fields)
        baseline_change=before.execute('SELECT COALESCE(MAX(id),0) FROM material_changes').fetchone()[0]
        audited={row[0] for row in after.execute(
            'SELECT DISTINCT material_id FROM material_changes WHERE id>?',(baseline_change,))}
        unaudited=set(changed_ids)-audited
        print('backup',backups[0])
        print('original',len(original),'current',len(current),'added',len(inserted),
              'deleted',len(deleted),'changed',len(changed_ids))
        print('changed_fields',dict(changes))
        print('changed_without_history',sorted(unaudited))
        print('changed_project_id',[i for i in changed_ids
                                    if original[i]['project_id']!=current[i]['project_id']])
        print('changed_source_page',[i for i in changed_ids
                                     if original[i]['source_page']!=current[i]['source_page']])
        print('changed_quantity',[i for i in changed_ids
                                  if original[i]['quantity']!=current[i]['quantity']])
        changed_manual_prices=[i for i,row in original.items()
                               if i in current and 'manual' in (row['price_source'] or '').lower()
                               and row['unit_price']!=current[i]['unit_price']]
        print('changed_manual_prices',changed_manual_prices)
        if deleted or unaudited or any(original[i]['project_id']!=current[i]['project_id']
                                       or original[i]['source_page']!=current[i]['source_page']
                                       for i in changed_ids) or changed_manual_prices:
            raise AssertionError('Migração alterou identidade/origem ou perdeu auditoria')
    finally:
        before.close(); after.close()


if __name__=='__main__': run()
