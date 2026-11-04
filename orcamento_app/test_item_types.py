"""Cost and hierarchy regression for raw, purchased, and assembly entries."""
import os
from pathlib import Path

test_root=Path(__file__).resolve().parent/'data'/'test_runs'
test_root.mkdir(parents=True,exist_ok=True)
if True:
    db_file=test_root/'test_item_types.db'
    if db_file.exists(): db_file.unlink()
    previous_db_env=os.environ.get('ORCAMENTO_DB_PATH')
    os.environ['ORCAMENTO_DB_PATH']=str(db_file)
    import database
    previous_db_path=database.DB_PATH
    database.DB_PATH=str(db_file)
    from database import init_db
    from app import create_project, create_material, get_project_full_data, MaterialCreate, ProjectCreate
    from item_types import infer_item_type

    assert infer_item_type('SUBCONJUNTO BASE', 'Outros Comprados', 'SUB CONJUNTO')=='subconjunto'
    assert infer_item_type('PARAFUSO', 'Outros Comprados', has_dimensions=False)=='comprado'
    assert infer_item_type('CHAPA AÇO', 'Chapa', has_dimensions=False)=='materia_prima'
    init_db()
    project=create_project(ProjectCreate(name='Estrutura de teste'))['id']
    main='CORPO PRINCIPAL'
    create_material(project,MaterialCreate(description='CHAPA AÇO',group_name='Chapa',
        item_type='materia_prima',parent_assembly=main,quantity=2,unit_weight=1,
        unit_price=10))
    create_material(project,MaterialCreate(description='RODÍZIO',group_name='Ferragens',
        item_type='comprado',parent_assembly=main,quantity=3,unit_weight=0.1,
        unit_price=5))
    assembly=create_material(project,MaterialCreate(description='CONJUNTO LATERAL',
        group_name='Subconjunto',item_type='subconjunto',parent_assembly=main,
        quantity=1,unit_weight=4,unit_price=99))['id']
    info=get_project_full_data(project)
    assert info['markup_result']['cost_mp']==20
    assert info['markup_result']['cost_mc']==15
    assert info['weight_result']['total_product_weight']==2.3
    assert info['unresolved_assembly_ids']==[assembly]
    assert assembly not in info['missing_price_ids']
    assert next(m for m in info['materials'] if m['id']==assembly)['total_price'] is None
    create_material(project,MaterialCreate(description='ARAME LATERAL',group_name='Arame',
        item_type='materia_prima',parent_assembly=main+' / CONJUNTO LATERAL',
        quantity=2,unit_weight=0.2,unit_price=2))
    info=get_project_full_data(project)
    assert info['unresolved_assembly_ids']==[]
    assert info['markup_result']['cost_mp']==24
    assert info['markup_result']['cost_mc']==15
    assert info['weight_result']['total_product_weight']==2.7
    print('Tipos de item, custos e hierarquia: OK')
    database.DB_PATH=previous_db_path
    if previous_db_env is None:
        os.environ.pop('ORCAMENTO_DB_PATH',None)
    else:
        os.environ['ORCAMENTO_DB_PATH']=previous_db_env
