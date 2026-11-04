"""Read-only inventory of saved rows that conceal multiple PDF cut-table rows."""

from collections import defaultdict
from pathlib import Path
import json
import sqlite3

import pymupdf

from config import DB_PATH
from reader_v3 import cut_table_rows, norm


def audit():
    conn=sqlite3.connect(DB_PATH)
    conn.row_factory=sqlite3.Row
    projects={row['id']:dict(row) for row in conn.execute('SELECT * FROM projects')
              if row['folder_path'] and not row['name'].startswith(('Teste de upload','Estrutura de teste'))}
    changes={row[0] for row in conn.execute('SELECT DISTINCT material_id FROM material_changes')}
    cache={}
    findings=[]
    for row in conn.execute('SELECT * FROM materials ORDER BY project_id,item_num'):
        item=dict(row)
        project=projects.get(item['project_id'])
        if not project or ': corte ' in (item['drawing_id'] or ''):
            continue
        source=item.get('source_page') or ''
        if '#page=' not in source:
            continue
        relative,page=source.rsplit('#page=',1)
        root=Path(project['folder_path']).resolve()
        path=(root/relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or norm(path.stem)!=norm(item['drawing_id']):
            continue
        key=(str(path),page)
        if key not in cache:
            with pymupdf.open(path) as doc:
                sheet=doc[int(page)-1]
                cache[key]=cut_table_rows(sheet.get_text(),sheet)
        cuts=cache[key]
        if len(cuts)<2:
            continue
        findings.append(dict(project_id=item['project_id'],item_id=item['id'],
                             description=item['description'],quantity=item['quantity'],
                             cuts=cuts,manually_edited=item['id'] in changes,
                             manual_price=(item['price_source'] or '').startswith('Ajuste manual aprovado'),
                             source_page=source))
    output=Path(__file__).resolve().parent/'data'/'audits'/'collapsed_cuts.json'
    output.write_text(json.dumps(findings,ensure_ascii=False,indent=2),encoding='utf8')
    counts=defaultdict(int)
    for found in findings:
        counts[found['project_id']]+=1
    print('TOTAL',len(findings),'BY_PROJECT',dict(counts),'REPORT',output)
    for found in findings:
        print(found['project_id'],found['item_id'],found['description'],
              [(row.get('material'),row.get('length'),row.get('quantity')) for row in found['cuts']],
              'edited=',found['manually_edited'],'manual_price=',found['manual_price'])
    conn.close()


if __name__=='__main__':
    audit()
