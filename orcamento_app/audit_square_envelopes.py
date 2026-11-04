"""Read-only inventory of the dominant-square dimension fallback."""

import re
from pathlib import Path

import pymupdf

from database import get_connection
from reader_v3 import num


def run():
    conn=get_connection()
    try:
        roots={row['id']:Path(row['folder_path']) for row in conn.execute('SELECT id,folder_path FROM projects')
               if row['folder_path']}
        found={}
        for item in conn.execute('SELECT id,project_id,description,group_name,source_page FROM materials'):
            if item['group_name'] not in ('Chapa','Polímero/PSAI') or '#page=' not in (item['source_page'] or ''):
                continue
            root=roots.get(item['project_id'])
            if not root: continue
            rel,page=item['source_page'].rsplit('#page=',1)
            pdf=(root/rel).resolve()
            if not pdf.is_relative_to(root.resolve()) or not pdf.is_file(): continue
            key=(str(pdf),int(page))
            found.setdefault(key,[]).append(item['id'])
        matched=[]
        for (pdf,page),ids in found.items():
            with pymupdf.open(pdf) as doc:
                text=doc[page-1].get_text()
            before,marker,_=text.partition('PERSPECTIVA')
            if not marker: continue
            values=sorted([num(line.strip()) for line in before.splitlines()
                           if re.fullmatch(r'\s*\d+(?:[,.]\d+)?\s*',line)
                           and num(line.strip())>=10],reverse=True)
            if len(values)>=3 and values[0]==values[1] and values[2]<values[0]*0.5:
                matched.append((ids,Path(pdf).name,values[:3]))
        for row in matched:
            print(row)
        print('candidate_documents',len(matched))
    finally:
        conn.close()


if __name__=='__main__': run()
