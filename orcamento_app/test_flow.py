"""Integration smoke test against a temporary database and three real source folders."""
import csv
import os
from pathlib import Path
import database

previous_db_path=database.DB_PATH
previous_db_env=os.environ.get('ORCAMENTO_DB_PATH')

test_root=Path(__file__).resolve().parent/'data'/'test_runs'
test_root.mkdir(parents=True,exist_ok=True)
if True:
    tmp=str(test_root)
    db_file=test_root/'teste.db'
    if db_file.exists(): db_file.unlink()
    os.environ['ORCAMENTO_DB_PATH']=str(db_file)

    import pymupdf
    from fastapi import HTTPException
    from openpyxl import load_workbook

    database.DB_PATH=str(db_file)
    from database import init_db, get_connection
    from app import (seed_historical_projects, get_project_full_data, create_project,
                     create_material, update_material, create_version, approve_markup,
                     update_rule, update_box_config, MaterialCreate, MaterialUpdate,
                     ProjectCreate, VersionCreate, RuleUpdate, BoxConfigUpdate)
    from exporter import export_budget_pdf, export_budget_xlsx, export_budget_csv

    init_db()
    imported=seed_historical_projects()['imported']
    assert len(imported)==3, imported
    expected=(44,202,34)
    for (project,count) in zip(imported,expected):
        info=get_project_full_data(project['id'])
        assert len(info['materials'])==count, (project,len(info['materials']))
        assert not info['can_finalize'] and info['missing_price_ids']
        assert info['project']['status']=='PRELIMINAR'
        assert all(m['source_page'] for m in info['materials'])
        assert len(info['materials'])==len({m['item_num'] for m in info['materials']})
        if project['name'].startswith('ILHA CASH RECKITT'):
            wire=next(m for m in info['materials'] if m['description'].startswith('ARAME APARADOR BASE'))
            sheet=next(m for m in info['materials'] if m['description'].startswith('CH APARADOR BASE'))
            assert (wire['drawing_length'],wire['length'],wire['radius_diam'])==(40.0,60.0,5.0)
            assert (sheet['length'],sheet['width'],sheet['thickness'])==(20.0,15.0,0.75)
            assert wire['unit_weight']>0 and sheet['unit_weight']>0
        try:
            create_version(project['id'],VersionCreate(final=True))
            raise AssertionError('emissão final deveria estar bloqueada')
        except HTTPException as error:
            assert error.status_code==409
        stem=f'projeto_{project["id"]}'
        pdf=export_budget_pdf(info['project'],info['materials'],info['markup_result'],
                              info['weight_result'],str(Path(tmp)/(stem+'.pdf')),
                              info['pending_decisions'])
        xlsx=export_budget_xlsx(info['project'],info['materials'],info['markup_result'],
                                info['weight_result'],str(Path(tmp)/(stem+'.xlsx')),
                                info['pending_decisions'])
        csv_path=export_budget_csv(info['materials'],str(Path(tmp)/(stem+'.csv')))
        with pymupdf.open(pdf) as doc:
            assert len(doc)>=2
            assert 'PRELIMINAR' in doc[0].get_text()
        book=load_workbook(xlsx,read_only=True,data_only=True)
        assert {'Resumo Executivo','Lista de Materiais (BOM)','Memória Markup','Pendências'}<=set(book.sheetnames)
        assert book['Lista de Materiais (BOM)'].max_row==count+1
        book.close()
        with open(csv_path,encoding='utf-8-sig',newline='') as stream:
            assert len(list(csv.reader(stream,delimiter=';')))==count+1
        print(f'{stem}: {count} itens, {info["project"]["nominal_weight_pdf"]:.3f} kg no PDF, '
              f'{info["weight_result"]["total_product_weight"]:.3f} kg extraídos, '
              f'{len(info["missing_price_ids"])} preços pendentes')

    manual=create_project(ProjectCreate(name='Teste de cálculo manual'))['id']
    item=create_material(manual,MaterialCreate(description='CHAPA AÇO CARBONO',group_name='Chapa',
        material='AÇO CARBONO',quantity=2,unit='un',length=1000,width=500,thickness=1.0))['id']
    before=get_project_full_data(manual)['materials'][0]
    assert before['unit_weight']>0
    assert abs(before['unit_price']-round(before['unit_weight']*7.02,4))<0.01
    update_rule('mp_chapa_aco',RuleUpdate(value=7.02,approved=1))
    priced=get_project_full_data(manual)['materials'][0]
    assert abs(priced['unit_price']-round(priced['unit_weight']*7.02,4))<0.01
    update_material(manual,item,MaterialUpdate(width=600))
    revised=get_project_full_data(manual)['materials'][0]
    assert revised['unit_weight']>before['unit_weight']
    assert revised['total_price']>priced['total_price']
    update_material(manual,item,MaterialUpdate(unit_price=99.0))
    assert get_project_full_data(manual)['materials'][0]['unit_price']==99.0
    update_material(manual,item,MaterialUpdate(unit_price=None))
    assert get_project_full_data(manual)['materials'][0]['unit_price']==revised['unit_price']
    conn=get_connection()
    assert conn.execute('SELECT COUNT(*) FROM material_changes WHERE project_id=?',(manual,)).fetchone()[0]>=2
    conn.close()
    box=update_box_config(manual,BoxConfigUpdate(length=880,width=130,height=350,flap_type=2,sheet_type=2))
    assert box['box_calc']['unit_cost'] is None
    final=create_version(manual,VersionCreate(final=True))
    assert final['status']=='FINAL'
    assert get_project_full_data(manual)['project']['final_price'] is None
    print('Cálculo, histórico de alterações e versão final sem markup automático: OK')

print('TESTES DE INTEGRAÇÃO CONCLUÍDOS')
database.DB_PATH=previous_db_path
if previous_db_env is None:
    os.environ.pop('ORCAMENTO_DB_PATH',None)
else:
    os.environ['ORCAMENTO_DB_PATH']=previous_db_env
