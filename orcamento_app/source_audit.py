"""Read-only inventory of the source workbooks and historical project folders."""
from pathlib import Path
import json
import openpyxl
import xlrd
from odf.opendocument import load
from odf.table import Table, TableRow, TableCell
from odf.text import P

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'arquivos_raw'
DADOS = ROOT / 'DADOS'

def sample_xlsx(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=False)
    out = []
    for ws in wb.worksheets:
        sample = []
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 35), max_col=min(ws.max_column, 20)):
            cells = [f'{c.column_letter}{c.row}:{str(c.value)[:65]}' for c in row if c.value is not None]
            if cells:
                sample.append(' | '.join(cells[:8]))
            if len(sample) >= 12:
                break
        out.append({'sheet': ws.title, 'rows': ws.max_row, 'cols': ws.max_column, 'sample': sample})
    wb.close()
    return out

def sample_xls(path):
    wb = xlrd.open_workbook(path)
    out = []
    for ws in wb.sheets():
        sample = []
        for r in range(min(ws.nrows, 35)):
            vals = [f'{c+1}:{str(ws.cell_value(r,c))[:65]}' for c in range(min(ws.ncols,20)) if ws.cell_value(r,c) != '']
            if vals:
                sample.append(' | '.join(vals[:8]))
            if len(sample) >= 12:
                break
        out.append({'sheet':ws.name,'rows':ws.nrows,'cols':ws.ncols,'sample':sample})
    return out

def sample_ods(path):
    doc=load(str(path)); out=[]
    for table in doc.spreadsheet.getElementsByType(Table):
        sample=[]
        for row in table.getElementsByType(TableRow)[:35]:
            vals=[]
            for i,cell in enumerate(row.getElementsByType(TableCell)[:20]):
                value=' '.join(t.firstChild.data for p in cell.getElementsByType(P) for t in p.childNodes if t.firstChild)
                if value: vals.append(f'{i+1}:{value[:65]}')
            if vals: sample.append(' | '.join(vals[:8]))
            if len(sample)>=12: break
        out.append({'sheet':table.getAttribute('name'),'sample':sample})
    return out

def main():
    for path in sorted(RAW.iterdir()):
        try:
            if path.suffix.lower()=='.xlsx': data=sample_xlsx(path)
            elif path.suffix.lower()=='.xls': data=sample_xls(path)
            elif path.suffix.lower()=='.ods': data=sample_ods(path)
            else: continue
            print(json.dumps({'file':path.name,'sheets':data},ensure_ascii=False))
        except Exception as exc:
            print(json.dumps({'file':path.name,'error':str(exc)},ensure_ascii=False))
    for project in sorted(DADOS.iterdir()):
        if not project.is_dir(): continue
        files=[p for p in project.rglob('*') if p.is_file()]
        print(json.dumps({'project':project.name,'pdfs':len([p for p in files if p.suffix.lower()=='.pdf']),
                          'workbooks':[str(p.relative_to(project)) for p in files if p.suffix.lower() in ('.xls','.xlsx','.ods')]},ensure_ascii=False))

if __name__=='__main__': main()
