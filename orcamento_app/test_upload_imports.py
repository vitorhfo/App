"""Exercise browser folder, single PDF, ZIP, and RAR upload paths."""
import asyncio
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import zipfile

from fastapi import HTTPException
from reportlab.pdfgen import canvas
from starlette.datastructures import UploadFile

test_root=Path(__file__).resolve().parent/'data'/'test_runs'
test_root.mkdir(parents=True,exist_ok=True)
db_file=test_root/'test_upload_imports.db'
if db_file.exists(): db_file.unlink()
previous_db_env=os.environ.get('ORCAMENTO_DB_PATH')
os.environ['ORCAMENTO_DB_PATH']=str(db_file)

import upload_imports
import database
previous_db_path=database.DB_PATH
database.DB_PATH=str(db_file)
previous_uploads_dir=upload_imports.UPLOADS_DIR
upload_imports.UPLOADS_DIR=str(test_root/'uploaded_projects')
from database import init_db
from app import (ProjectCreate, create_project, get_project_full_data, get_source,
                 upload_project_files, upload_project_archive)

buffer=BytesIO()
pdf=canvas.Canvas(buffer)
pdf.drawString(50,750,'Desenho tecnico unico sem lista de materiais')
pdf.save()
pdf_data=buffer.getvalue()

def pdf_upload(name='desenho.pdf'):
    return UploadFile(file=BytesIO(pdf_data),filename=name)

def project():
    return create_project(ProjectCreate(name='Teste de upload'))['id']

init_db()

folder_id=project()
result=asyncio.run(upload_project_files(folder_id,[pdf_upload()],['CLIENTE/PROJETO/desenho.pdf']))
assert result['materials_count']==1
folder_data=get_project_full_data(folder_id)
assert folder_data['materials'][0]['item_type']=='subconjunto'
assert folder_data['materials'][0]['source_page'].startswith('CLIENTE/PROJETO/desenho.pdf')
assert get_source(folder_id,'CLIENTE/PROJETO/desenho.pdf').path.endswith('desenho.pdf')

multi_id=project()
result=asyncio.run(upload_project_files(multi_id,[pdf_upload('a.pdf'),pdf_upload('b.pdf')],
    ['CLIENTE/PROJETO/a.pdf','CLIENTE/PROJETO/b.pdf']))
assert result['materials_count']==1
assert get_project_full_data(multi_id)['unresolved_assembly_ids']

single_id=project()
result=asyncio.run(upload_project_files(single_id,[pdf_upload()],['desenho.pdf']))
assert result['materials_count']==1
assert get_project_full_data(single_id)['unresolved_assembly_ids']

zip_buffer=BytesIO()
with zipfile.ZipFile(zip_buffer,'w') as archive:
    archive.writestr('CLIENTE/PROJETO/desenho.pdf',pdf_data)
zip_id=project()
result=asyncio.run(upload_project_archive(zip_id,UploadFile(file=BytesIO(zip_buffer.getvalue()),filename='projeto.zip')))
assert result['materials_count']==1

rar_exe=Path(r'C:\Program Files\WinRAR\Rar.exe')
if rar_exe.exists():
    pdf_path=test_root/'upload_rar_source.pdf'
    pdf_path.write_bytes(pdf_data)
    rar_path=test_root/'upload_project_test.rar'
    if rar_path.exists(): rar_path.unlink()
    subprocess.run([str(rar_exe),'a','-idq',str(rar_path),str(pdf_path)],check=True)
    rar_id=project()
    result=asyncio.run(upload_project_archive(rar_id,UploadFile(file=BytesIO(rar_path.read_bytes()),filename='projeto.rar')))
    assert result['materials_count']==1

try:
    asyncio.run(upload_project_files(folder_id,[pdf_upload()],['../fora.pdf']))
    raise AssertionError('Caminho inválido aceito')
except HTTPException as error:
    assert error.status_code==400
assert len(get_project_full_data(folder_id)['materials'])==1
print('Uploads de pasta, PDF, ZIP, RAR e bloqueio de caminho inválido: OK')
database.DB_PATH=previous_db_path
upload_imports.UPLOADS_DIR=previous_uploads_dir
if previous_db_env is None:
    os.environ.pop('ORCAMENTO_DB_PATH',None)
else:
    os.environ['ORCAMENTO_DB_PATH']=previous_db_env
