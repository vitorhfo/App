"""Import the PSAI price cells from the user's CONTROLV workbook."""
from pathlib import Path
import re
import unicodedata

from config import RAW_DIR

FILE_NAME='TABELA DE VALORES - CONTROLV - COMPRADOS + IMPRESSÃO.xlsx'


def _plain(value):
    value=unicodedata.normalize('NFKD',str(value or ''))
    return ''.join(c for c in value if not unicodedata.combining(c)).upper().strip()


def controlv_psai_rows():
    from openpyxl import load_workbook
    path=Path(RAW_DIR)/FILE_NAME
    if not path.exists():
        return {}
    wb=load_workbook(path,read_only=True,data_only=True)
    try:
        ws=wb.active
        if _plain(ws['B2'].value)!='PSAI':
            raise ValueError('Cabeçalho PSAI não encontrado na tabela CONTROLV')
        rows={}
        for row in range(4,11):
            color=_plain(ws.cell(row,1).value).lower()
            thickness=ws.cell(row,3).value
            value=ws.cell(row,4).value
            if color not in ('branco','cristal','leitoso') or not isinstance(value,(int,float)):
                raise ValueError(f'Linha PSAI inválida na CONTROLV: {row}')
            match=re.search(r'\d+(?:[,.]\d+)?',str(thickness))
            if not match:
                raise ValueError(f'Espessura PSAI inválida na CONTROLV: {row}')
            key=f'pl_psai_{color}_{round(float(match.group().replace(",","."))*10):02d}'
            rows[key]=(float(value),f'CONTROLV!D{row}')
        print_rate=ws['N4'].value
        if not isinstance(print_rate,(int,float)) or print_rate<=0:
            raise ValueError('Preço de impressão inválido na CONTROLV!N4')
        rows['imp_digital_face']=(float(print_rate),'CONTROLV!N4')
        formulas=load_workbook(path,read_only=True,data_only=False)
        try:
            colored_formula=str(formulas.active['K4'].value or '')
            match=re.search(r'J4\s*\*\s*(0[.,]\d+)',colored_formula,re.I)
            if not match:
                raise ValueError('Acréscimo para PSAI colorido não identificado em CONTROLV!K4')
            rows['imp_psai_adicional_4x1']=(float(match.group(1).replace(',','.'))*100,
                                             'CONTROLV!K4')
        finally:
            formulas.close()
        return rows
    finally:
        wb.close()


def sync_controlv_rules(cur):
    """Refresh spreadsheet-owned rules; retain any explicit app override."""
    changed=False
    for key,(value,source) in controlv_psai_rows().items():
        current=cur.execute('SELECT value,approved,source FROM price_rules WHERE rule_key=?',(key,)).fetchone()
        if not current or current['source']=='Ajuste manual no app':
            continue
        if (float(current['value']),current['approved'],current['source'])!=(value,1,source):
            cur.execute('''UPDATE price_rules SET value=?,approved=1,source=?,effective_date=CURRENT_DATE
                WHERE rule_key=?''',(value,source,key))
            changed=True
    return changed
