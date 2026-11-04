"""Read cached historical totals; never use them as approved prices."""
from pathlib import Path
import re
import json
import openpyxl
import xlrd

BASE=Path(__file__).resolve().parents[2]/'DADOS'
KEY=re.compile(r'PESO|CUSTO|TOTAL|PRE[ÇC]O|MARK|VALOR FINAL',re.I)

def xlsx_summary(path):
    wb=openpyxl.load_workbook(path,read_only=True,data_only=True)
    result=[]
    for ws in wb:
        hits=[]
        for row in ws.iter_rows(max_col=min(ws.max_column,12),max_row=min(ws.max_row,120)):
            for cell in row:
                if isinstance(cell.value,str) and KEY.search(cell.value):
                    neighbors=[f'{ws.cell(cell.row,c).column_letter}:{str(ws.cell(cell.row,c).value)[:55]}'
                               for c in range(max(1,cell.column-1),min(ws.max_column,cell.column+4)+1)
                               if ws.cell(cell.row,c).value is not None]
                    hits.append(f'{cell.row} '+ ' | '.join(neighbors))
                    break
            if len(hits)>=18: break
        result.append({'sheet':ws.title,'hits':hits})
    wb.close()
    return result

def main():
    for project in sorted(BASE.iterdir()):
        if not project.is_dir() or not any(t in project.name for t in ('VEJA','RECKITT','E03704167')): continue
        files=[p for p in project.rglob('*.xlsx') if not p.name.startswith('~$') and
               ('CUSTO' in p.name.upper() or 'MARCKUP' in p.name.upper())]
        for path in files[:6]:
            print(json.dumps({'project':project.name,'file':str(path.relative_to(project)),
                              'sheets':xlsx_summary(path)},ensure_ascii=False))

if __name__=='__main__': main()
