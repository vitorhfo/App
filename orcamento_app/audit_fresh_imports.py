"""Read-only comparison between saved BOM quantities and a new source parse."""

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

from database import get_connection
from reader_v3 import norm, process_complete_project


def grouped(items):
    result=defaultdict(float)
    for item in items:
        if item.get('item_type')=='subconjunto':
            continue
        result[(norm(item.get('description') or ''),item.get('item_type') or '')] += float(item.get('quantity') or 0)
    return result


def audit():
    db=get_connection()
    cache={}
    report=[]
    try:
        projects=[dict(row) for row in db.execute('SELECT * FROM projects ORDER BY id')
                  if row['folder_path'] and not row['name'].startswith(('Teste de upload','Estrutura de teste'))]
        for project in projects:
            project_id=project['id']
            root=Path(project['folder_path'])
            if str(root) not in cache:
                try:
                    cache[str(root)]=process_complete_project(root)
                except Exception as exc:
                    cache[str(root)]={'materials':[],'error':str(exc)}
            fresh=cache[str(root)]
            saved=[dict(row) for row in db.execute('SELECT * FROM materials WHERE project_id=?',(project_id,))]
            before=grouped(saved)
            after=grouped(fresh['materials'])
            differences=[]
            for key in sorted(before.keys()|after.keys()):
                qty_saved=before.get(key,0)
                qty_fresh=after.get(key,0)
                if abs(qty_saved-qty_fresh)>0.0001:
                    differences.append(dict(description=key[0],item_type=key[1],
                                            saved=qty_saved,fresh=qty_fresh))
            entry=dict(project_id=project_id,name=project['name'],saved_rows=len(saved),
                       fresh_rows=len(fresh['materials']),quantity_differences=differences,
                       error=fresh.get('error'))
            report.append(entry)
            print(json.dumps({k:(len(v) if k=='quantity_differences' else v)
                              for k,v in entry.items()},ensure_ascii=False),flush=True)
        path=Path(__file__).resolve().parent/'data'/'audits'/f'fresh_imports_{datetime.now():%Y%m%d_%H%M%S}.json'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(f'REPORT={path}',flush=True)
    finally:
        db.close()


if __name__=='__main__':
    audit()
