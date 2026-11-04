"""Receive project PDFs without losing directory structure or extracting unsafe paths."""
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import uuid
import zipfile

from fastapi import HTTPException

from config import UPLOADS_DIR

MAX_BYTES = 500_000_000
MAX_PDFS = 1000


def new_upload_area(project_id):
    root = Path(UPLOADS_DIR) / f'proj_{project_id}' / uuid.uuid4().hex
    source = root / 'source'
    source.mkdir(parents=True)
    return root, source


def pdf_target(source, submitted_path):
    value = str(submitted_path or '').replace('\\', '/')
    parts = PurePosixPath(value).parts
    if (not parts or value.startswith('/') or any(
            part in ('', '.', '..') or re.search(r'[<>:"|*?\x00-\x1f]', part)
            for part in parts) or not parts[-1].lower().endswith('.pdf')):
        raise HTTPException(status_code=400, detail=f'Caminho de PDF inválido: {value[:100]}')
    source = Path(source).resolve()
    target = source.joinpath(*parts).resolve()
    if not target.is_relative_to(source):
        raise HTTPException(status_code=400, detail='PDF fora da pasta de importação.')
    return target


def _looks_like_pdf(path):
    with path.open('rb') as stream:
        return stream.read(1024).lstrip().startswith(b'%PDF-')


async def save_upload(upload, target, remaining):
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with target.open('xb') as output:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > remaining:
                    raise HTTPException(status_code=413, detail='Upload excede 500 MB.')
                output.write(chunk)
        if not size or not _looks_like_pdf(target):
            raise HTTPException(status_code=400, detail=f'Arquivo não é um PDF válido: {target.name}')
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return size


def extract_zip_pdfs(archive, source):
    total = 0
    count = 0
    try:
        with zipfile.ZipFile(archive) as packed:
            for info in packed.infolist():
                if info.is_dir() or not info.filename.lower().endswith('.pdf'):
                    continue
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) == stat.S_IFLNK or info.flag_bits & 1:
                    raise HTTPException(status_code=400, detail='ZIP contém PDF simbólico ou protegido por senha.')
                target = pdf_target(source, info.filename)
                if target.exists():
                    raise HTTPException(status_code=400, detail='ZIP contém nomes de PDF repetidos.')
                total += info.file_size
                count += 1
                if count > MAX_PDFS or total > MAX_BYTES:
                    raise HTTPException(status_code=413, detail='ZIP excede 1000 PDFs ou 500 MB de PDFs.')
                target.parent.mkdir(parents=True, exist_ok=True)
                actual=0
                with packed.open(info) as incoming, target.open('xb') as output:
                    while chunk := incoming.read(1024 * 1024):
                        actual+=len(chunk)
                        if total-info.file_size+actual>MAX_BYTES:
                            raise HTTPException(status_code=413, detail='ZIP excede 500 MB de PDFs.')
                        output.write(chunk)
                total+=actual-info.file_size
                if not _looks_like_pdf(target):
                    raise HTTPException(status_code=400, detail=f'Arquivo inválido no ZIP: {target.name}')
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail='Arquivo ZIP inválido.') from exc
    return count


def _unrar_executable():
    return (shutil.which('unrar') or
            next((str(path) for path in (
                Path(r'C:\Program Files\WinRAR\UnRAR.exe'),
                Path(r'C:\Program Files (x86)\WinRAR\UnRAR.exe')) if path.is_file()), None))


def extract_rar_pdfs(archive, source):
    exe = _unrar_executable()
    if not exe:
        raise HTTPException(status_code=503, detail='Extrator RAR não encontrado neste computador.')
    try:
        listing = subprocess.run([exe, 'lb', '-c-', '-p-', '-scu', str(archive)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=400, detail='Tempo esgotado ao listar o RAR.') from exc
    if listing.returncode:
        raise HTTPException(status_code=400, detail='Arquivo RAR inválido ou protegido por senha.')
    try:
        names = listing.stdout.decode('utf-16-le').splitlines()
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail='Nomes de arquivos inválidos no RAR.') from exc
    count = 0
    total = 0
    for name in names:
        if not name.lower().endswith('.pdf'):
            continue
        target = pdf_target(source, name)
        if target.exists():
            raise HTTPException(status_code=400, detail='RAR contém nomes de PDF repetidos.')
        count += 1
        if count > MAX_PDFS:
            raise HTTPException(status_code=413, detail='RAR excede 1000 PDFs.')
        target.parent.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen([exe, 'p', '-inul', '-p-', str(archive), name],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            with target.open('xb') as output:
                while chunk := process.stdout.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_BYTES:
                        raise HTTPException(status_code=413, detail='RAR excede 500 MB de PDFs.')
                    output.write(chunk)
            if process.wait(timeout=60) or not _looks_like_pdf(target):
                raise HTTPException(status_code=400, detail=f'PDF inválido ou inacessível no RAR: {name}')
        except Exception:
            process.kill()
            process.wait()
            target.unlink(missing_ok=True)
            raise
    return count
