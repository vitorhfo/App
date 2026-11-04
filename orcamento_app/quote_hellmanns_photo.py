"""Create a reviewable preliminary quote from the supplied Hellmann's photo."""

from datetime import date
from pathlib import Path
import shutil

from app import ProjectCreate, create_project, get_project_full_data
from calc_engine import DENSIDADE_ACO_CARBONO
from config import DATA_DIR
from database import get_connection
from mass_math import ceil_kg
from pricing import approved_rules
from template_reports import export_template_reports


SOURCE=Path(r'C:\Users\Luis\AppData\Local\Temp\codex-clipboard-1afd489b-a91e-461b-a0c8-1cb093bc5ee0.png')
CODE='FOTO-HELLMANNS-20261016'
NAME='DISPLAY DE SACHÊS HELLMANN’S — 3 COMPARTIMENTOS COM VENTOSAS'
PARTS=(
    ('Corpo superior dobrado',300,250,0.75,1),
    ('Bandeja inferior dobrada',250,180,0.75,1),
    ('Divisória superior',150,100,0.75,2),
    ('Divisória inferior',150,60,0.75,2),
    ('Frente perfurada',250,80,0.75,1),
)


def add_item(conn,project_id,number,description,group,item_type,material,
             quantity,unit,unit_weight,unit_area,unit_price,price_source,
             source_page,observation,pending_issue='',**geometry):
    total_weight=ceil_kg(unit_weight*quantity)
    total_area=round(unit_area*quantity,6)
    total_price=round(unit_price*quantity,2) if unit_price is not None else None
    values=dict(project_id=project_id,item_num=number,description=description,
                group_name=group,item_type=item_type,material=material,
                quantity=quantity,unit=unit,unit_weight=unit_weight,
                total_weight=total_weight,unit_area=unit_area,total_area=total_area,
                unit_price=unit_price,total_price=total_price,price_source=price_source,
                source_page=source_page,drawing_id=f'{CODE}-{number:02d}',
                confidence=0.45,parent_assembly=NAME,is_inferred=1,
                pending_issue=pending_issue,observation=observation,
                thickness=geometry.get('thickness',0),width=geometry.get('width',0),
                length=geometry.get('length',0),depth=geometry.get('depth',0),
                radius_diam=geometry.get('radius_diam',0))
    columns=list(values)
    conn.execute('INSERT INTO materials ('+','.join(columns)+') VALUES ('+
                 ','.join('?' for _ in columns)+')',tuple(values.values()))


def create_quote():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    photo_dir=Path(DATA_DIR)/'photo_sources'
    photo_dir.mkdir(exist_ok=True)
    photo=photo_dir/f'{CODE}.png'
    if not photo.exists():
        shutil.copy2(SOURCE,photo)
    notes=('Orçamento preliminar obtido somente da foto. Medidas externas informadas: '
           '250 × 150 × 200 mm; três compartimentos por nível; duas ventosas; '
           'massa final aproximada indicada: 0,9 kg. Hipótese: chapa SAE 1008 '
           'de 0,75 mm, pintura a pó azul e logo em adesivo vinil impresso. '
           'As dimensões de corte e o método de fabricação precisam de desenho técnico. '
           'O peso do orçamento é bruto, antes dos furos e recortes. '
           'Ventosa: referência de catálogo ainda não aprovada. '
           'Sem mão de obra, perdas, embalagem ou markup.')
    conn=get_connection()
    project=conn.execute('SELECT id FROM projects WHERE code=?',(CODE,)).fetchone()
    conn.close()
    if project:
        project_id=project['id']
    else:
        project_id=create_project(ProjectCreate(
            name=NAME,code=CODE,client='HELLMANN’S (referência visual)',
            date=date.today().isoformat(),folder_path=str(photo_dir),notes=notes))['id']
    conn=get_connection()
    if conn.execute('SELECT 1 FROM materials WHERE project_id=? LIMIT 1',(project_id,)).fetchone():
        conn.close()
        return project_id
    rules=approved_rules(conn)
    sheet_rate=rules['mp_chapa_aco']
    paint_rate=rules['mp_tinta_po']
    paint_use=rules['taxa_consumo_tinta']
    print_rate=rules['imp_digital_face']
    vinyl_rate=rules['pl_adesivo_vinil_010']
    reference=f'Imagem fornecida: {photo.name}'
    one_face_area=0.0
    for index,(label,length,width,thickness,qty) in enumerate(PARTS,1):
        area=length*width/1_000_000
        one_face_area+=area*qty
        gross=ceil_kg(length*width*thickness*DENSIDADE_ACO_CARBONO/1_000_000)
        unit_price=round(gross*sheet_rate,4)
        add_item(conn,project_id,index,label,'Chapa','materia_prima',
                 'CHAPA DE AÇO SAE 1008 0,75 mm',qty,'un',gross,area,unit_price,
                 f'Chapa: modelo vazio, R$ {sheet_rate:.2f}/kg',reference,
                 'Corte estimado pela foto; peso bruto inclui área perfurada e abas de dobra.',
                 'Confirmar planificação, furos e espessura em desenho técnico.',
                 length=length,width=width,thickness=thickness)
    paint_kg=round(2*one_face_area*paint_use,5)
    add_item(conn,project_id,6,'Pintura a pó azul escuro','Pintura a Pó',
             'materia_prima','TINTA PÓ AZUL ESCURO',paint_kg,'kg',1,0,paint_rate,
             f'Tinta pó: modelo vazio, R$ {paint_rate:.2f}/kg; consumo {paint_use:g} kg/m² em duas faces',
             reference,'Área pintada estimada em duas faces de todas as chapas.',
             'Confirmar acabamento e consumo real de tinta.')
    add_item(conn,project_id,7,'Ventosa 55 mm com botão','Outros Comprados',
             'comprado','VENTOSA 55 MM C/BOTÃO',2,'un',0,0,6.86,
             'Referência preliminar: catálogo de comprados, R$ 6,86/un, ainda não aprovado',
             reference,'Duas ventosas indicadas na imagem.',
             'Confirmar modelo, diâmetro e preço vigente das ventosas.')
    logo_area=130*55/1_000_000
    logo_unit_price=round(logo_area*(vinyl_rate+print_rate),4)
    add_item(conn,project_id,8,'Adesivo vinil impresso HELLMANN’S 130 × 55 mm',
             'Outros Comprados','comprado','ADESIVO VINIL IMPRESSO 4x0',1,'un',0,logo_area,
             logo_unit_price,
             f'Estimativa: vinil R$ {vinyl_rate:.2f}/m² + impressão R$ {print_rate:.2f}/m²',
             reference,'Tamanho do logo estimado pela proporção da foto.',
             'Confirmar arte, dimensão e custo mínimo de impressão.')
    for title,description in (
        ('Confirmar engenharia da peça',
         'Chapa, espessura, planificação, perfurações, divisórias e fixação foram inferidas da imagem.'),
        ('Confirmar itens comprados',
         'Preço da ventosa vem de linha de catálogo não aprovada; logo e impressão não têm preço mínimo confirmado.'),
    ):
        conn.execute('''INSERT INTO pending_decisions
            (project_id,title,description,impact_level,proposed_action)
            VALUES (?,?,?,?,?)''',
            (project_id,title,description,'ALTO','Conferir desenho técnico e cotação do fornecedor.'))
    conn.commit()
    conn.close()
    return project_id


if __name__=='__main__':
    project_id=create_quote()
    path=export_template_reports(get_project_full_data(project_id),project_id,'planilhas')
    print(f'PROJECT_ID={project_id}')
    print(f'EXPORT_DIR={path.parent}')
