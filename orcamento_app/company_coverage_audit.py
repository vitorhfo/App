"""Read-only company-source inventory; all evidence is written locally.

Never import company projects into the working budget database. PDF tests use
local copies. No office application is opened against the network share.
"""
from collections import Counter
from pathlib import Path
from stat import S_ISDIR, S_ISLNK
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
import unicodedata

APP = Path(__file__).resolve().parent
DEFAULT_SOURCE = r'\\192.168.1.3\bluelight'
DEFAULT_OUTPUT = APP / 'data' / 'audits' / 'company_coverage_20261106'
INTERESTING = {'.pdf', '.xls', '.xlsx', '.xlsm', '.ods', '.dwg', '.dxf',
               '.sldprt', '.sldasm', '.slddrw', '.step', '.stp', '.igs', '.iges'}


def network_path(value):
    if isinstance(value, int) or value is None:
        return False
    try:
        return os.fsdecode(value).replace('/', '\\').startswith('\\\\')
    except TypeError:
        return False


def reject_network_mutation(event, args):
    """Deny Python filesystem writes to any UNC path, including accidental ones."""
    if event == 'open' and network_path(args[0]):
        mode = args[1] or ''
        flags = args[2] or 0
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if any(c in mode for c in 'wax+') or flags & write_flags:
            raise PermissionError('Auditoria somente de leitura: gravação de rede bloqueada.')
    elif event in {'os.remove', 'os.rmdir', 'os.mkdir', 'os.rename', 'os.link',
                   'os.symlink', 'os.chmod', 'os.chown', 'os.utime', 'os.truncate'}:
        if any(network_path(value) for value in args[:2]):
            raise PermissionError('Auditoria somente de leitura: alteração de rede bloqueada.')
    elif event == 'sqlite3.connect' and network_path(args[0]):
        raise PermissionError('Bancos da rede não são abertos por esta auditoria.')


def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', str(value))
                   if not unicodedata.combining(c)).upper()


def role(relative):
    parts = [normalized(p) for p in Path(relative).parts]
    text = '/'.join(parts)
    if any('OBSOLETO' in p for p in parts):
        return 'obsolete'
    if any(p in {'ARTE', 'ARTES', 'APRESENTACAO', 'APRESENTACOES'} for p in parts[:-1]):
        return 'art_or_presentation'
    if any('ORCAMENTO' in p for p in parts[:-1]):
        return 'budget'
    if any(p.startswith(('PROJETO', 'DESENHO', 'REFERENCIA', 'TECNICO')) for p in parts[:-1]):
        return 'technical_candidate'
    if any(token in text for token in ('NOTAS FISCAIS', 'RH/', 'DOCUMENTOS/', 'USUARIOS/')):
        return 'administrative_or_user_folder'
    return 'unclassified'


def local_output(value):
    path = Path(value).resolve()
    if network_path(path) or not path.is_relative_to(APP / 'data' / 'audits'):
        raise ValueError('A saída deve ficar na pasta local data/audits do aplicativo.')
    return path


def inventory(source, output):
    root = Path(source)
    output = local_output(output)
    output.mkdir(parents=True, exist_ok=True)
    counters = Counter()
    by_client = {}
    started = time.time()
    errors = []
    with (output / 'inventory.jsonl').open('w', encoding='utf8') as target:
        with os.scandir(root) as listing:
            top = sorted(list(listing), key=lambda e: e.name.casefold())
        for entry in top:
            client = entry.name if entry.is_dir(follow_symlinks=False) else '(raiz)'
            counts = by_client.setdefault(client, Counter())
            pending = [entry]
            while pending:
                current = pending.pop()
                path = Path(current.path)
                try:
                    stat = current.stat(follow_symlinks=False)
                    if S_ISLNK(stat.st_mode) or getattr(stat, 'st_file_attributes', 0) & 0x400:
                        counts['skipped_links'] += 1
                        continue
                    if S_ISDIR(stat.st_mode):
                        counts['directories'] += 1
                        with os.scandir(path) as children:
                            pending.extend(children)
                        continue
                    suffix = path.suffix.lower()
                    counts['files'] += 1
                    counters[suffix or '(sem extensão)'] += 1
                    if suffix not in INTERESTING or path.name.startswith(('~$', '._')):
                        continue
                    relative = path.relative_to(root).as_posix()
                    record = dict(path=relative, client=client, suffix=suffix,
                                  size=stat.st_size, mtime_ns=stat.st_mtime_ns, role=role(relative))
                    target.write(json.dumps(record, ensure_ascii=False) + '\n')
                    counts[suffix] += 1
                    counts[suffix + '_bytes'] += stat.st_size
                except OSError as exc:
                    errors.append({'path': str(path), 'error': str(exc)})
                    counts['errors'] += 1
            target.flush()
            if entry.is_dir(follow_symlinks=False):
                print(json.dumps({'client': client, 'files': counts['files'],
                                  'pdfs': counts['.pdf'], 'errors': counts['errors']},
                                 ensure_ascii=False), flush=True)
    summary = dict(source=str(root), output=str(output), elapsed_seconds=round(time.time()-started, 2),
                   extensions=dict(counters), clients={k: dict(v) for k,v in by_client.items()}, errors=errors)
    (output / 'inventory_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf8')
    print('INVENTORY=' + str(output), flush=True)
    return summary


def load_records(output):
    return [json.loads(line) for line in (output / 'inventory.jsonl').read_text(encoding='utf8').splitlines()]


def project_key(record):
    """Candidate package boundary, kept explicit rather than claimed as a registry."""
    parts = record['path'].split('/')
    anchors = [i for i,p in enumerate(parts[:-1])
               if normalized(p).startswith(('PROJETO', 'REFERENCIA', 'DESENHO', 'TECNICO'))]
    return '/'.join(parts[:anchors[0]]) if anchors else '/'.join(parts[:-1])


def plan(output):
    output = local_output(output)
    records = load_records(output)
    grouped = {}
    for row in records:
        if row['suffix'] == '.pdf' and row['role'] in {'technical_candidate', 'unclassified'}:
            grouped.setdefault(project_key(row), []).append(row)
    cases = []
    for folder, rows in grouped.items():
        if not folder:
            continue
        # Include other active PDF evidence below this same package, including
        # historical budget PDFs. Preserve the reader's own exclusion rules.
        files = [r for r in records if r['suffix'] == '.pdf'
                 and r['path'].startswith(folder + '/')
                 and r['role'] not in {'obsolete', 'art_or_presentation', 'administrative_or_user_folder'}]
        case = dict(id=hashlib.sha256(folder.encode()).hexdigest()[:16], folder=folder,
                    client=rows[0]['client'], files=files,
                    pdfs=len(files), bytes=sum(r['size'] for r in files),
                    technical=any(r['role']=='technical_candidate' for r in rows),
                    latest_mtime_ns=max(r['mtime_ns'] for r in rows))
        cases.append(case)
    by_client = {}
    for case in cases:
        by_client.setdefault(case['client'], []).append(case)
    selected = {}
    for client, options in by_client.items():
        eligible = [c for c in options if c['bytes'] <= 80_000_000 and c['pdfs'] <= 90]
        pool = eligible or options
        pool.sort(key=lambda c: (c['technical'], 2<=c['pdfs']<=45,
                                 c['latest_mtime_ns'], -c['bytes']), reverse=True)
        selected[pool[0]['id']] = {**pool[0], 'selection': 'um pacote por pasta de cliente com PDF candidato'}
        # Broaden the large collections without pretending that a sample is a
        # complete validation of every project/revision stored on the server.
        if len(options) >= 50 and eligible:
            ordered = sorted(eligible, key=lambda c:c['folder'])
            for index in {0, len(ordered)//3, 2*len(ordered)//3, len(ordered)-1}:
                case = ordered[index]
                selected.setdefault(case['id'], {**case, 'selection': 'diversidade de pastas em coleção extensa'})
    result = dict(candidate_groups=len(cases), all_cases=cases,
                  selected_cases=list(selected.values()),
                  scope='inventário completo; testes funcionais por amostragem estratificada, não validação de todas as peças')
    (output / 'plan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'candidate_groups':len(cases),'selected_cases':len(selected),
                      'clients':len(by_client),'selected_pdfs':sum(c['pdfs'] for c in selected.values()),
                      'selected_gb':round(sum(c['bytes'] for c in selected.values())/1e9,2)},ensure_ascii=False),flush=True)
    return result


def digest(path):
    value = hashlib.sha256()
    with open(path, 'rb') as file:
        for chunk in iter(lambda:file.read(1024*1024), b''):
            value.update(chunk)
    return value.hexdigest()


def reader_fingerprint():
    paths=[APP/'reader_v3.py',APP/'calc_engine.py',APP/'mass_math.py',APP/'item_types.py',
           APP/'wire_allowance.py',APP/'score_package.py',*sorted((APP/'reader_profiles').glob('*.py'))]
    value=hashlib.sha256()
    for path in paths:
        value.update(path.relative_to(APP).as_posix().encode());value.update(path.read_bytes())
    return value.hexdigest()


def worker(manifest, output):
    version=reader_fingerprint()
    from reader_v3 import process_complete_project
    from source_inventory import _missing_dimensions
    output = local_output(output)
    manifest = Path(manifest).resolve()
    if not manifest.is_relative_to(output):
        raise ValueError('Manifesto fora da pasta local de auditoria.')
    case = json.loads(manifest.read_text(encoding='utf8'))
    folder = Path(case['local_folder']).resolve()
    copy_root=Path(case.get('copy_root',output/'copies')).resolve()
    local_output(copy_root.parent)
    if not folder.is_relative_to(copy_root) or network_path(folder):
        raise ValueError('O leitor só pode receber a cópia local.')
    started = time.time()
    data = process_complete_project(folder)
    physical = [m for m in data['materials'] if m['item_type'] != 'subconjunto']
    missing_dimensions = [m for m in physical if _missing_dimensions(m)]
    assemblies = [m for m in data['materials'] if m['item_type'] == 'subconjunto']
    read_errors = [p for p in data['pending_decisions'] if p['title'] in {'PDF não lido','OCR não concluído'}]
    status = ('partial_read_error' if physical and read_errors else 'read_error' if read_errors else
              'no_physical_items' if not physical else 'recognized_with_pending' if
              assemblies or missing_dimensions or data['pending_decisions'] else 'recognized_needs_reference_validation')
    result = dict(id=case['id'], folder=case['folder'], client=case['client'], status=status,
                  pdfs=case['pdfs'], rows=len(data['materials']), physical_rows=len(physical),
                  unresolved_assemblies=len(assemblies), missing_dimensions=len(missing_dimensions),
                  missing_weights=sum(not m.get('finished_unit_weight',m.get('unit_weight',0)) for m in physical),
                  uncertain_quantities=sum(m.get('unit')=='?' for m in physical),
                  nominal_weight_pdf=data['nominal_weight_pdf'],
                  known_finished_weight=sum(m.get('finished_total_weight',m.get('total_weight',0)) or 0 for m in physical),
                  profiles=sorted({e['profile'] for e in data['reading_report']['events']}),
                  decisions=Counter(p['title'] for p in data['pending_decisions']),
                  read_errors=read_errors, elapsed_seconds=round(time.time()-started,2),
                  reader_fingerprint=version,reader_changed_during_run=version!=reader_fingerprint())
    (output / 'results' / (case['id']+'.json')).write_text(
        json.dumps({'summary':result,'reading':data},ensure_ascii=False,indent=2),encoding='utf8')
    return result


def run_case(case, source, output, timeout):
    result_path = output / 'results' / (case['id']+'.json')
    integrity_path = output / 'integrity' / (case['id']+'.json')
    if result_path.is_file() and integrity_path.is_file():
        return json.loads(result_path.read_text(encoding='utf8'))['summary']
    local_folder = output / 'copies' / case['id'] / case['folder'].split('/')[-1]
    local_folder.mkdir(parents=True,exist_ok=True)
    copies = []
    try:
        for row in case['files']:
            remote = Path(source) / Path(row['path'])
            relative = Path(row['path']).relative_to(Path(case['folder']))
            target = (local_folder / relative).resolve()
            if not target.is_relative_to(local_folder.resolve()):
                raise ValueError('Arquivo fora da cópia local.')
            before = remote.stat()
            if (before.st_size,before.st_mtime_ns)!=(row['size'],row['mtime_ns']):
                raise RuntimeError('Fonte mudou desde o inventário: '+row['path'])
            target.parent.mkdir(parents=True,exist_ok=True)
            sha = hashlib.sha256()
            with remote.open('rb') as original, target.open('wb') as local:
                for chunk in iter(lambda:original.read(1024*1024),b''):
                    sha.update(chunk);local.write(chunk)
            copies.append(dict(path=row['path'],sha256_before=sha.hexdigest(),
                               size=row['size'],mtime_ns=row['mtime_ns']))
        manifest = {**case,'local_folder':str(local_folder)}
        manifest_path = output / 'manifests' / (case['id']+'.json')
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
        try:
            run = subprocess.run([sys.executable,str(Path(__file__).resolve()),'worker',
                                  '--manifest',str(manifest_path),'--output',str(output)],
                                 capture_output=True,text=True,encoding='utf8',errors='replace',timeout=timeout)
            if not result_path.is_file():
                raise RuntimeError((run.stderr or run.stdout)[-2200:])
            result = json.loads(result_path.read_text(encoding='utf8'))['summary']
        except subprocess.TimeoutExpired:
            result = dict(id=case['id'],folder=case['folder'],client=case['client'],
                          status='timeout',pdfs=case['pdfs'],timeout_seconds=timeout)
    except Exception as exc:
        result = dict(id=case['id'],folder=case['folder'],client=case['client'],
                      status='copy_or_execution_error',pdfs=case['pdfs'],error=str(exc))
    changes = []
    for record in copies:
        try:
            remote = Path(source) / Path(record['path'])
            after = remote.stat()
            record['sha256_after'] = digest(remote)
            record['unchanged'] = (record['sha256_after']==record['sha256_before']
                                   and (after.st_size,after.st_mtime_ns)==(record['size'],record['mtime_ns']))
            if not record['unchanged']:changes.append(record['path'])
        except OSError as exc:
            record['verification_error'] = str(exc);changes.append(record['path'])
    result['source_files_verified'] = len(copies)
    result['source_changes_observed'] = changes
    integrity_path.write_text(json.dumps(copies,ensure_ascii=False,indent=2),encoding='utf8')
    if result_path.is_file():
        payload=json.loads(result_path.read_text(encoding='utf8'));payload['summary']=result
    else:
        payload={'summary':result}
    result_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    return result


def run_cases(source,output,jobs,timeout,case_ids=None):
    output=local_output(output)
    for name in ('copies','results','manifests','integrity'):
        (output/name).mkdir(exist_ok=True)
    planned=json.loads((output/'plan.json').read_text(encoding='utf8'))
    cases=planned['selected_cases']
    if case_ids:
        known={case['id']:case for case in planned['all_cases']}
        unknown=set(case_ids)-known.keys()
        if unknown:raise ValueError('Casos desconhecidos: '+', '.join(sorted(unknown)))
        cases=[known[key] for key in case_ids]
    results=[]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        tasks={pool.submit(run_case,c,source,output,timeout):c for c in cases}
        for task in as_completed(tasks):
            result=task.result();results.append(result)
            print(json.dumps({'done':len(results),'total':len(cases),'client':result['client'],
                              'status':result['status'],'physical_rows':result.get('physical_rows',0)},
                             ensure_ascii=False),flush=True)
    (output/'functional_summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    return results


def retest(previous, output, jobs, timeout):
    """Repeat only local inputs, preserving the entire earlier audit and hashes."""
    previous=local_output(previous);output=local_output(output)
    if previous==output:
        raise ValueError('O antes e o depois precisam ficar em pastas separadas.')
    output.mkdir(parents=True,exist_ok=True)
    for name in ('results','manifests','integrity'):(output/name).mkdir(exist_ok=True)
    manifests=sorted((previous/'manifests').glob('*.json'))
    def one(path):
        case=json.loads(path.read_text(encoding='utf8'))
        integrity=json.loads((previous/'integrity'/path.name).read_text(encoding='utf8'))
        local_folder=Path(case['local_folder']).resolve()
        if not local_folder.is_relative_to(previous/'copies'):
            raise ValueError('Cópia fora da auditoria anterior.')
        for row in integrity:
            local=local_folder/Path(row['path']).relative_to(Path(case['folder']))
            if digest(local)!=row['sha256_before']:
                raise ValueError('A cópia local diverge do original registrado: '+row['path'])
        case['copy_root']=str(previous/'copies')
        manifest_path=output/'manifests'/path.name
        manifest_path.write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf8')
        result_path=output/'results'/path.name
        if result_path.is_file():
            cached=json.loads(result_path.read_text(encoding='utf8'))['summary']
            if (cached.get('reader_fingerprint')==reader_fingerprint()
                    and not cached.get('reader_changed_during_run')
                    and cached.get('local_copies_verified')==len(integrity)):
                return cached
        try:
            run=subprocess.run([sys.executable,str(Path(__file__).resolve()),'worker',
                                '--manifest',str(manifest_path),'--output',str(output)],
                               capture_output=True,text=True,encoding='utf8',errors='replace',timeout=timeout)
            if not result_path.is_file():raise RuntimeError((run.stderr or run.stdout)[-1800:])
            result=json.loads(result_path.read_text(encoding='utf8'))['summary']
        except subprocess.TimeoutExpired:
            result=dict(id=case['id'],folder=case['folder'],client=case['client'],
                        pdfs=case['pdfs'],status='timeout',timeout_seconds=timeout)
            result_path.write_text(json.dumps({'summary':result},ensure_ascii=False,indent=2),encoding='utf8')
        prior=json.loads((previous/'results'/path.name).read_text(encoding='utf8'))['summary']
        result['before_status']=prior['status'];result['before_physical_rows']=prior.get('physical_rows',0)
        result['lost_all_physical_rows']=prior.get('physical_rows',0)>0 and result.get('physical_rows',0)==0
        result['local_copies_verified']=len(integrity)
        payload=json.loads(result_path.read_text(encoding='utf8'));payload['summary']=result
        result_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
        return result
    results=[]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        tasks=[pool.submit(one,path) for path in manifests]
        for task in as_completed(tasks):
            result=task.result();results.append(result)
            print(json.dumps({'done':len(results),'total':len(manifests),'client':result['client'],
                              'before':result['before_physical_rows'],'after':result.get('physical_rows',0),
                              'status':result['status']},ensure_ascii=True),flush=True)
    (output/'functional_summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8')
    return results


def report(output):
    output=local_output(output)
    inventory_data=json.loads((output/'inventory_summary.json').read_text(encoding='utf8'))
    planned=json.loads((output/'plan.json').read_text(encoding='utf8'))
    results=[json.loads(path.read_text(encoding='utf8'))['summary']
             for path in sorted((output/'results').glob('*.json'))]
    records=load_records(output)
    states=Counter(r['status'] for r in results)
    integrity={}
    for path in (output/'integrity').glob('*.json'):
        for row in json.loads(path.read_text(encoding='utf8')):
            prior=integrity.get(row['path'])
            integrity[row['path']]=row if prior is None or not row.get('unchanged') else prior
    labels={'no_physical_items':'Sem peças físicas extraídas',
            'recognized_with_pending':'Peças extraídas com pendências',
            'recognized_needs_reference_validation':'Peças extraídas; validar contra referência',
            'timeout':'Inconclusivo: tempo limite', 'copy_or_execution_error':'Erro de cópia ou execução',
            'read_error':'Erro de leitura','partial_read_error':'Leitura parcial com erro'}
    def safe_cell(value):
        return "'"+value if isinstance(value,str) and value.startswith(('=','+','-','@')) else value
    with (output/'RESULTADOS_POR_PACOTE.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file,delimiter=';')
        writer.writerow(['Pasta','Situação','PDFs na entrada','Peças extraídas','Subconjuntos pendentes',
                         'Itens sem medidas','Itens sem peso','Peso PDF kg','Peso conhecido kg',
                         'Formatos reconhecidos','Fontes conferidas','Mudanças observadas na origem','ID'])
        for r in sorted(results,key=lambda r:r['folder'].casefold()):
            writer.writerow([safe_cell(v) for v in [r['folder'],labels.get(r['status'],r['status']),r['pdfs'],
                r.get('physical_rows',0),r.get('unresolved_assemblies'),r.get('missing_dimensions'),
                r.get('missing_weights'),r.get('nominal_weight_pdf'),r.get('known_finished_weight'),
                ', '.join(r.get('profiles',[])),r.get('source_files_verified',0),
                len(r.get('source_changes_observed',[])),r['id']]])
    with (output/'INTEGRIDADE_FONTES.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file,delimiter=';')
        writer.writerow(['Arquivo na rede','SHA256 antes','SHA256 depois','Conteúdo e data preservados'])
        for path,row in sorted(integrity.items()):
            writer.writerow([safe_cell(path),row['sha256_before'],row.get('sha256_after',''),row.get('unchanged',False)])
    pdf_prefixes=set()
    for row in records:
        if row['suffix']=='.pdf' and row['role'] not in {'obsolete','art_or_presentation'}:
            parts=row['path'].split('/')
            pdf_prefixes.update('/'.join(parts[:i]) for i in range(1,len(parts)))
    cad_groups={}
    for row in records:
        if row['suffix'] in {'.dwg','.dxf','.sldprt','.sldasm','.slddrw','.step','.stp','.igs','.iges'} and row['role'] in {'technical_candidate','unclassified'}:
            key=project_key(row)
            if key not in pdf_prefixes:
                cad_groups.setdefault(key,Counter())[row['suffix']]+=1
    with (output/'PASTAS_CAD_SEM_PDF.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file,delimiter=';');writer.writerow(['Pasta candidata','Arquivos CAD','Tipos'])
        for key,counts in sorted(cad_groups.items()):
            writer.writerow([safe_cell(key),sum(counts.values()),', '.join(sorted(counts))])
    unique_copied=len(integrity)
    unchanged=sum(r.get('unchanged',False) for r in integrity.values())
    total_files=sum(c.get('files',0) for c in inventory_data['clients'].values())
    total_dirs=sum(c.get('directories',0) for c in inventory_data['clients'].values())
    def brint(value): return format(value, ',').replace(',', '.')
    lines=[
        '# Auditoria de cobertura do acervo — 06/11/2026','',
        '**Conclusão: o programa ainda não cobre automaticamente todo o acervo.** Há formatos de lista presentes em desenhos legíveis que não são reconhecidos e arquivos técnicos ignorados por nome.','',
        '## Escopo','',
        f"- Origem apenas lida: `{inventory_data['source']}`.",
        f'- Inventário: {brint(total_files)} arquivos e {brint(total_dirs)} pastas; {brint(inventory_data["extensions"].get(".pdf",0))} PDFs. Erros de enumeração: {len(inventory_data["errors"])}.',
        f'- A segmentação por caminho identificou {brint(planned["candidate_groups"])} grupos candidatos a projetos. Não é uma contagem oficial de projetos ou variantes.',
        f'- Testes funcionais: {len(results)} pacotes candidatos em {len({r["client"] for r in results})} pastas de primeiro nível; um pacote por pasta com PDFs candidatos e diversidade adicional nas coleções maiores.',
        '- A rodada principal tem 200 pacotes; o MINI PORTA PALETE foi acrescentado como caso dirigido para investigar o filtro de nomes.',
        '- Trata-se de amostragem estratificada. Não valida todas as peças de todos os projetos, nem permite estimar uma taxa geral de acerto. Alguns candidatos contêm logos, apresentação, plantas ou referências, sem lista técnica completa.',
        '- O leitor foi executado nas cópias locais. Não houve importação no banco de orçamentos da empresa, recálculo de preços históricos, envio à IA ou abertura de aplicativos de edição nos originais.','',
        '## Resultado da amostragem','',
        '| Resultado | Pacotes |','|---|---:|',
    ]
    for key,count in sorted(states.items()):lines.append(f'| {labels.get(key,key)} | {count} |')
    lines += ['',
        '“Peças extraídas” comprova reconhecimento nesta execução; não comprova a correção de todas as quantidades, medidas, hierarquia, massa, preço ou preenchimento final do orçamento. Os casos sem pendências estruturais detectadas também exigem confronto com a referência da mesma variante.',
        '“Sem peças extraídas” significa que a entrada não gerou uma lista física automaticamente. Não é, por si só, falha de parser: pode ser uma imagem, um detalhe avulso ou um documento sem lista. As falhas confirmadas abaixo foram verificadas separadamente.','',
        '## Falhas e limites confirmados','',
        '1. **Cabeçalho CAD não suportado:** em `!LAVANDERIA/ZF - TEMPORÁRIOS/WV/CONJ. APOIO CENTRAL AL. e F.F..PDF`, a tabela mostra `Nº ITEM / Nº DA PEÇA / DESCRIÇÃO / QTD.` e duas peças, uma de aço e uma de alumínio, quantidade 1 de cada. O pacote de 23 PDFs terminou sem peças físicas. A imagem da página foi conferida em `visual/unsupported_cad_columns.png`; o texto legível está em `unrecognized_evidence.json`. O leitor CAD atual espera a descrição imediatamente após o número do item e não reconhece essa organização.',
        '2. **Filtro de nome descarta PDF técnico:** os módulos de MINI PORTA PALETE com `7 PARTES` e `13 PARTES` no nome são excluídos antes da abertura porque o filtro procura o trecho `ARTE` em qualquer posição do caminho. Em cópias isoladas, o nome original resultou em “Sem PDF técnico”; uma segunda cópia local com nome neutro foi aberta. Isso confirma a exclusão por nome; o nome neutro ainda não extraiu a composição, portanto renomear não resolve toda a leitura. Os originais da rede não foram renomeados. Evidência: `filename_filter_evidence.json`.',
        '3. **Arquivos CAD nativos:** o aplicativo atual procura componentes em PDF; a existência de DWG, DXF, SLDPRT, SLDASM ou SLDDRW não equivale a suporte à extração desses formatos. Há pastas com desenhos nativos e sem PDFs correspondentes; a lista é `PASTAS_CAD_SEM_PDF.csv`. A contagem é de pastas candidatas, não de produtos finais.',
        '4. **Reconhecimento parcial:** os resultados detalham itens sem medidas/peso e subconjuntos não expandidos. Esses casos exigem conferência e não são orçamentos prontos. Preços não foram auditados nesta execução.','',
        '## Exemplo positivo conferido','',
        'No `BIG MART/BARRA DE CARGA BIG MART`, a lista da montagem contém duas chapas e um tubo. O leitor gerou as duas linhas físicas com quantidades 2 e 1, vinculadas aos PDFs filhos e com medidas extraídas. A página foi conferida em `visual/recognized_big_mart.png`. O peso do carimbo é 1,005241 kg e o peso conhecido calculado é 1,089902 kg; a diferença de cerca de 8,42% continua para revisão. Esta conferência confirma a composição observada, não aprova um orçamento completo.','',
        '## Integridade da origem','',
        '- O script bloqueia operações Python de escrita, criação, atualização, exclusão, renomeação e mudança de metadados em caminhos UNC. Atalhos e pontos de redirecionamento não foram seguidos.',
        f'- {unique_copied} PDFs únicos foram copiados para testes; {unchanged} tiveram SHA256 antes/depois e tamanho/data de modificação preservados no intervalo de sua conferência.',
        '- A conferência por hash abrange os arquivos copiados/testados, não todos os arquivos inventariados. Nenhum comando de alteração foi executado na pasta da rede. Mudanças feitas por outros usuários durante a auditoria, se observadas, aparecem no CSV de integridade.',
        '- Imagens de conferência, relatórios, resultados e cópias ficaram somente na pasta local desta auditoria.','',
        '## Próximas prioridades','',
        '1. Criar teste real para a tabela `Nº ITEM / Nº DA PEÇA / DESCRIÇÃO / QTD.` e implementar um leitor específico, protegendo os formatos CAD já reconhecidos.',
        '2. Trocar a exclusão por trecho de texto por critérios explícitos de pasta/tipo, com teste para `PARTES` e para uma pasta verdadeira de arte.',
        '3. Separar documentos sem lista, desenhos de peça única e montagens; a ausência de BOM não pode virar uma composição inventada.',
        '4. Priorizar os formatos pendentes dos clientes de maior volume e ampliar as referências reais conferidas contra os desenhos e orçamentos da mesma variante.','',
        '## Arquivos desta auditoria','',
        '- `RESULTADOS_POR_PACOTE.csv`: matriz de leitura e pendências por pacote.',
        '- `INTEGRIDADE_FONTES.csv`: hashes e preservação dos originais testados.',
        '- `PASTAS_CAD_SEM_PDF.csv`: pastas candidatas com formatos nativos e sem PDF.',
        '- `inventory_summary.json`, `inventory.jsonl` e `plan.json`: inventário e critério de seleção.',
        '- `results/`, `manifests/` e `integrity/`: dados completos e evidência individual.','',
        'O programa de leitura não foi corrigido nesta auditoria; as lacunas acima permanecem abertas. Os três testes da proteção de leitura da rede passaram. A suíte de 227 testes da etapa anterior cobre seus exemplos conhecidos, mas não representa validação de todo este acervo.',
    ]
    (output/'RELATORIO_COBERTURA.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    summary=dict(inventory_files=total_files,inventory_pdfs=inventory_data['extensions'].get('.pdf',0),
                 cases=len(results),top_folders=len({r['client'] for r in results}),states=dict(states),
                 copied_unique=unique_copied,unchanged=unchanged,cad_folders_without_pdf=len(cad_groups),
                 scope=planned['scope'])
    (output/'FINAL_SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    return summary


def report_retest(previous,output):
    from collections import defaultdict
    previous=local_output(previous);output=local_output(output)
    current=reader_fingerprint();rows=[];field_changes=[];lost=[];stale=[];gains=[]
    fields=('quantity','unit','material','group_name','item_type','thickness','radius_diam',
            'width','depth','length','drawing_length','wire_allowance_mm','unit_weight','total_weight',
            'finished_unit_weight','finished_total_weight','unit_area','total_area','printing')
    compared_working=0
    def grouped(payload):
        result=defaultdict(list)
        for item in payload.get('reading',{}).get('materials',[]):
            if item['item_type']=='subconjunto':continue
            key=(item['drawing_id'],item['source_page'],item['parent_assembly'],item['description'])
            result[key].append(item)
        return result
    for file in sorted((previous/'results').glob('*.json')):
        target=output/'results'/file.name
        if not target.is_file():stale.append(file.stem);continue
        before=json.loads(file.read_text(encoding='utf8'));after=json.loads(target.read_text(encoding='utf8'))
        old=before['summary'];new=after['summary'];rows.append(new)
        if new['status']!='timeout' and (new.get('reader_fingerprint')!=current or new.get('reader_changed_during_run')):
            stale.append(file.stem)
        if old.get('physical_rows',0)==0 and new.get('physical_rows',0)>0:gains.append(new)
        if old.get('physical_rows',0)>0:
            compared_working+=1;a=grouped(before);b=grouped(after);differences=[]
            if not new.get('physical_rows',0):lost.append(new['folder'])
            for key,items in a.items():
                if key not in b:
                    differences.append({'item':key,'kind':'missing_previous_item'});continue
                if len(items)!=len(b[key]):
                    differences.append({'item':key,'kind':'changed_occurrences'});continue
                for x,y in zip(items,b[key]):
                    for field in fields:
                        if x.get(field)!=y.get(field):
                            differences.append({'item':key,'field':field,'before':x.get(field),'after':y.get(field)})
            if differences:field_changes.append({'folder':new['folder'],'differences':differences})
    summary=dict(cases=len(rows),before_recognized=sum(json.loads(p.read_text(encoding='utf8'))['summary'].get('physical_rows',0)>0
                 for p in (previous/'results').glob('*.json')),after_recognized=sum(r.get('physical_rows',0)>0 for r in rows),
                 newly_recognized=len(gains),previous_working_compared=compared_working,
                 changed_working_cases=len(field_changes),lost_working_cases=lost,stale_cases=stale,
                 states=dict(Counter(r['status'] for r in rows)),reader_fingerprint=current,
                 sources='cópias locais conferidas contra os hashes da auditoria anterior; nenhuma leitura ou gravação nova na rede')
    (output/'COMPARACAO_CAMPOS_ANTERIORES.json').write_text(json.dumps(field_changes,ensure_ascii=False,indent=2),encoding='utf8')
    (output/'RESUMO_CORRECOES.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    with (output/'ANTES_DEPOIS.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.writer(file,delimiter=';')
        writer.writerow(['Pasta','Peças antes','Peças depois','Situação depois','Subconjuntos pendentes',
                         'Itens sem medidas','Itens sem peso','Páginas/formato com evidência','ID'])
        for row in sorted(rows,key=lambda r:r['folder'].casefold()):
            writer.writerow([row['folder'],row.get('before_physical_rows'),row.get('physical_rows',0),row['status'],
                             row.get('unresolved_assemblies'),row.get('missing_dimensions'),row.get('missing_weights'),
                             ', '.join(row.get('profiles',[])),row['id']])
    lines=['# Correções de leitura e comparação com a auditoria — 06/11/2026','',
           '## O que mudou','',
           '- O filtro separa rótulos de arte/apresentação/obsoleto de nomes de peças: PARTES e MARTELLO são aceitos.',
           '- Leitura por células para Nº ITEM / Nº DA PEÇA / DESCRIÇÃO / QTD, preservando descrição vazia e código explícito.',
           '- Três grades adicionais: ITEM/QTD/DESCRIÇÃO com cabeçalho inferior; CAD com descrição quebrada e código vazio; POS/QTDE/CÓDIGO/MATERIAL/PESO.',
           '- Cortes de arame explícitos na tabela entram separadamente: comprimento nominal e consumo com 20 mm extras uma vez por corte.',
           '- Perfis/comprimentos de estoque não se tornam corte. Peso sem unidade permanece para confirmação.',
           '- Em pasta ambígua, um leitor novo não substitui silenciosamente o produto que o leitor existente reconhecia. A escolha de variante permanece pendente.',
           '- Listas de detalhe novas em outras páginas não se somam à principal sem comprovar o conjunto e a multiplicação. As páginas ficam identificadas como pendência.','',
           '## Antes e depois','',
           f"- Pacotes retestados: **{summary['cases']}**.",
           f"- Pacotes com peças extraídas: **{summary['before_recognized']} antes → {summary['after_recognized']} depois**.",
           f"- Pacotes que passaram a extrair peças: **{summary['newly_recognized']}**.",
           f"- Casos anteriores comparados por identidade, quantidade, material, medidas, pesos, áreas e impressão: **{compared_working}**.",
           f"- Casos anteriores com diferenças nesses campos: **{len(field_changes)}**; casos que perderam todas as peças: **{len(lost)}**.",
           f"- Resultados de outra versão a refazer: **{len(stale)}**.",
           '- Os resultados completos e pendências estão em `ANTES_DEPOIS.csv`. Reconhecer peças não aprova todas as cotas, massas, quantidades de conjunto ou preços.','',
           '## Exemplos conferidos','',
           '- WV: a tabela do apoio central contém as duas peças com uma unidade de cada. O pacote WV inclui variantes sem raiz única; essa ambiguidade permanece explícita.',
           '- POLAR: 12 linhas de componentes e 104 cortes. A linha de 82 arames Ø2,7 × 401 mm mantém 401 mm como nominal e 421 mm no consumo. O peso declarado de 0,4 kg diverge da massa conhecida calculada; o orçamento continua preliminar.',
           '- FABRÃO: as duas descrições quebradas em linhas e os códigos vazios são preservados; nenhuma quantidade é consumida como código.',
           '- NICOLAS: seis linhas da lista, com MTG tratado como subconjunto; perfil 15×15×0,9 mm e estoque de 6000 mm separado do corte ainda não conhecido.',
           '- LUPO/MEZANINO e AMBBAG: a auditoria detectou troca de variante causada por tabelas novas. O fallback foi corrigido para preservar as leituras anteriores de 3 e 12 linhas, respectivamente.','',
           '## Limites e proteção da origem','',
           '- Toda esta rodada usa os PDFs já copiados localmente, conferidos contra os hashes registrados dos originais. Nenhum arquivo da rede foi alterado e nenhum orçamento salvo foi reimportado.',
           '- A auditoria original e seus hashes permanecem na pasta superior; os dados anteriores não foram substituídos pelos resultados corrigidos.',
           '- Documentos auxiliares sem lista, desenhos incompletos, formatos ainda não reconhecidos e arquivos CAD nativos sem PDF continuam exigindo tratamento específico.',
           '- Um pacote arquitetônico de 123 PDFs (ÉDMAIS/LOJA - ATATIBA) permanece inconclusivo por tempo limite; o relatório não o classifica como leitura correta.',
           '- Não houve preenchimento automático de cotas, pesos ou quantidades desconhecidas para aumentar artificialmente a cobertura.','',
           '## Validação final','',
           'Suíte completa e exportação nativa: conferir os resultados finais registrados ao encerrar a entrega.','',
           'Versão dos leitores: `'+current+'`.']
    (output/'RELATORIO_CORRECOES.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps(summary,ensure_ascii=True),flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inventory','plan','run','worker','report','retest','report-retest'])
    parser.add_argument('--source', default=DEFAULT_SOURCE)
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--manifest')
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--timeout',type=int,default=150)
    parser.add_argument('--case',action='append',dest='case_ids')
    parser.add_argument('--previous-output',default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    sys.addaudithook(reject_network_mutation)
    if args.action=='inventory':inventory(args.source,args.output)
    elif args.action=='plan':plan(args.output)
    elif args.action=='report':report(args.output)
    elif args.action=='retest':retest(args.previous_output,args.output,args.jobs,args.timeout)
    elif args.action=='report-retest':report_retest(args.previous_output,args.output)
    elif args.action=='worker':worker(args.manifest,args.output)
    else:run_cases(args.source,args.output,args.jobs,args.timeout,args.case_ids)


if __name__ == '__main__':
    main()
