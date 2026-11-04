"""Preliminary manufacturing-cost quote for three REHAU displays in one photo.

Run once against the local app DB. The image supplies only floor dimensions;
all other stock cuts and vendor costs remain explicit, reviewable hypotheses.
"""

from collections import defaultdict
from datetime import date
from pathlib import Path
import json
import shutil
import sqlite3

from app import ProjectCreate, create_project, get_project_full_data
from config import DATA_DIR, DB_PATH
from database import get_connection
from mass_math import calculated_weight, ceil_kg
from pricing import approved_rules, price_item
from template_reports import export_template_reports


SOURCE = Path(r'C:\Users\Luis\Desktop\WhatsApp Image 2026-10-19 at 15.20.43.jpeg')
CODE = 'REHAU-FOTO-20261022'
NAME = 'REHAU — três expositores (estimativa pela imagem)'
PHOTO = Path(DATA_DIR) / 'photo_sources' / f'{CODE}.jpeg'
REPORT = Path(DATA_DIR) / 'REHAU_ORCAMENTO_FOTO_20261022.md'
PARENTS = (
    '1. EXPOSITOR DE CHÃO — 10 CORES E CHAVEIROS',
    '2. EXPOSITOR GIRATÓRIO — 32 CORES EM 4 FACES',
    '3. PAINEL DE PAREDE — 5 ROLOS, 32 CORES E MOODBOARD',
)
LABOR = {PARENTS[0]: 720.0, PARENTS[1]: 1080.0, PARENTS[2]: 630.0}
CONTINGENCY = .07
MDF_RATE = round(730 / (2.75 * 1.85) * 1.12, 4)
WEB = {
    'casters': 'https://www.leroymerlin.com.br/rodizio-giratorio-com-freio-total-gel-2-com-rosca-ajax-tamanho-2_1569719891',
    'bearing': 'https://www.leroymerlin.com.br/base-giratoria-para-tampo-de-mesa-vidro-ou-madeira-60cm_1572448382',
    'led': 'https://www.leroymerlin.com.br/fita-led-12v-2700k-ip20-5w-m-rolo-5m-bella-lp224_1570437026',
    'driver': 'https://www.leroymerlin.com.br/fonte-slim-para-fita-led-12v-5a-60w-bivolt_1570172452',
}


def build_items(conn, project_id):
    rules = approved_rules(conn)
    result = []
    number = 1

    def append(parent, description, group, kind, material, quantity, *,
               length=0, width=0, depth=0, thickness=0, weight=0,
               unit_price=None, price_source='', issue='', observation='', unit='un'):
        nonlocal number
        row = dict(project_id=project_id, item_num=number, description=description,
                   group_name=group, item_type=kind, material=material,
                   quantity=quantity, unit=unit, length=length, width=width,
                   depth=depth, thickness=thickness, radius_diam=0,
                   unit_weight=weight, total_weight=ceil_kg(weight * quantity),
                   unit_area=round(length * width / 1_000_000, 6) if width else 0,
                   total_area=round(length * width * quantity / 1_000_000, 6) if width else 0,
                   drawing_id=f'{CODE}-{number:03d}', confidence=.4,
                   parent_assembly=parent, is_inferred=1, source_page=PHOTO.name,
                   pending_issue=issue, observation=observation,
                   unit_price=unit_price, price_source=price_source)
        if kind != 'subconjunto' and unit_price is None:
            row['unit_price'], row['price_source'] = price_item(row, rules, conn)
        row['total_price'] = (round(row['unit_price'] * quantity, 2)
                              if row['unit_price'] is not None else None)
        result.append(row)
        number += 1

    def tube(parent, label, w, d, t, length, quantity):
        material = f'Tubo quadrado aço carbono {w}x{d}x{t}mm'
        gross = ceil_kg(calculated_weight(dict(group_name='Tubo Quadrado/Retangular',
            material=material, length=length, width=w, depth=d, thickness=t)))
        append(parent, f'{parent[0]}. {label} — {w}×{d}×{t} mm, corte {length} mm',
               'Tubo Quadrado/Retangular', 'materia_prima', material, quantity,
               length=length, width=w, depth=d, thickness=t, weight=gross,
               issue='Corte e perfil inferidos da imagem; confirmar desenho técnico.',
               observation='Peso bruto geométrico; comprimento de corte é hipótese da foto.')

    def sheet(parent, label, length, width, t, quantity):
        material = f'Chapa aço carbono {t} mm'
        gross = ceil_kg(calculated_weight(dict(group_name='Chapa', material=material,
            length=length, width=width, thickness=t)))
        append(parent, f'{parent[0]}. {label} — {length}×{width}×{t} mm',
               'Chapa', 'materia_prima', material, quantity,
               length=length, width=width, thickness=t, weight=gross,
               issue='Corte inferido da imagem; confirmar planificação e furos.',
               observation='Peso bruto antes de recortes.')

    def mdf(parent, label, length, width, quantity=1):
        area = length * width / 1_000_000
        append(parent, f'{parent[0]}. {label} MDF preto 15 mm — {length}×{width} mm',
               'Outros Comprados', 'comprado', 'MDF preto revestido 15 mm', quantity,
               length=length, width=width, thickness=15,
               unit_price=round(area * MDF_RATE, 4),
               price_source=('Estimativa por área: orçamento manual BUD 21/10/2026, '
                             'R$ 730/chapa 2750×1850 mm, mais 12% de recorte.'),
               issue='Dimensão e aproveitamento inferidos da imagem.',
               observation=f'Tarifa estimada R$ {MDF_RATE:.2f}/m², já com perda de 12%.')

    def bought(parent, label, quantity, rate, source='Estimativa provisória para protótipo'):
        append(parent, f'{parent[0]}. {label}', 'Outros Comprados', 'comprado',
               label, quantity, unit_price=rate, price_source=source,
               issue='Confirmar fornecedor e preço antes da proposta final.',
               observation='Peça/acessório necessário ao expositor; quantidade estimada da imagem.')

    def paint(parent, kg):
        append(parent, f'{parent[0]}. Pintura a pó preta — consumo', 'Pintura a Pó',
               'materia_prima', 'TINTA PÓ PRETA', kg, weight=1,
               unit_price=rules['mp_tinta_po'],
               price_source=f"Regra aprovada mp_tinta_po: R$ {rules['mp_tinta_po']:.2f}/kg",
               unit='kg',
               issue='Consumo estimado pela área exposta; confirmar processo.',
               observation='Consumo bruto de tinta, sem serviço de pintura.')

    for parent in PARENTS:
        append(parent, parent, 'Subconjunto', 'subconjunto', '', 1,
               observation='Agrupador sem cobrança; os componentes estão nas linhas seguintes.')
        if parent == PARENTS[0]:
            # 1900 × 500 × 500 mm is the only external dimension given in the image.
            tube(parent, 'colunas estruturais', 25, 25, 1.5, 1650, 4)
            tube(parent, 'travessas superior/inferior', 25, 25, 1.5, 500, 8)
            tube(parent, 'guias laterais', 20, 20, 1.2, 450, 4)
            sheet(parent, 'base metálica', 550, 550, 2, 1)
            mdf(parent, 'painel traseiro', 1700, 500)
            mdf(parent, 'lateral', 1700, 180, 2)
            mdf(parent, 'testeira frontal/traseira', 500, 300, 2)
            mdf(parent, 'fechamento do plinto', 500, 500)
            bought(parent, 'kit eixo, buchas e batentes para rolo Ø180 mm', 10, 28)
            bought(parent, 'ganchos laterais para chaveiros', 20, 3.8)
            bought(parent, 'rodízio 2 pol. com freio', 4, 14.8, WEB['casters'])
            bought(parent, 'plaquetas de identificação das cores', 10, 5.5)
            bought(parent, 'fita de borda/acabamento MDF', 1, 45)
            bought(parent, 'parafusos, porcas e fixadores', 1, 65)
            bought(parent, 'adesivo e testeira REHAU impressos', 1, 120)
            bought(parent, 'embalagem de proteção para transporte', 1, 180)
            paint(parent, 1.0)
        elif parent == PARENTS[1]:
            # Four faces, eight roll positions each; dimensions are image estimates.
            tube(parent, 'colunas do miolo', 30, 30, 1.5, 1700, 4)
            tube(parent, 'travessas radiais de sustentação', 30, 30, 1.5, 320, 16)
            tube(parent, 'estrutura superior/inferior', 30, 30, 1.5, 700, 4)
            sheet(parent, 'chapa base do giro', 750, 750, 2, 1)
            sheet(parent, 'chapa superior de travamento', 700, 700, 1.2, 1)
            mdf(parent, 'painel interno por face', 1650, 340, 4)
            mdf(parent, 'disco de base superior/inferior', 750, 750, 2)
            bought(parent, 'kit eixo, buchas e batentes para rolo Ø180 mm', 32, 28)
            bought(parent, 'base giratória/rolamento de apoio', 1, 287.1,
                   WEB['bearing'] + ' (capacidade de carga ainda não validada)')
            bought(parent, 'reforço e fixação do mancal giratório', 1, 130)
            bought(parent, 'testeira curva preta, acabamento e impressão', 1, 230)
            bought(parent, 'pés niveladores', 4, 20)
            bought(parent, 'plaquetas de identificação das cores', 32, 4)
            bought(parent, 'fita de borda/acabamento MDF', 1, 60)
            bought(parent, 'parafusos, porcas e fixadores', 1, 120)
            bought(parent, 'embalagem reforçada para transporte', 1, 260)
            paint(parent, 1.5)
        else:
            # No dimensions in the photo: 1800 × 1200 mm panel is assumed.
            tube(parent, 'montantes do quadro', 20, 20, 1.2, 1800, 2)
            tube(parent, 'travessas do quadro', 20, 20, 1.2, 1200, 3)
            sheet(parent, 'prateleira inferior', 1800, 180, 1.2, 1)
            mdf(parent, 'painel principal', 1800, 1200)
            mdf(parent, 'testeira de marca', 1800, 280)
            mdf(parent, 'base de moodboard', 550, 450)
            bought(parent, 'kit eixo, buchas e batentes para rolo Ø180 mm', 5, 28)
            bought(parent, 'suporte de amostra de cor', 32, 5)
            bought(parent, 'fixação removível da amostra (ímã/velcro)', 32, 2.5)
            bought(parent, 'presilhas e moldura do moodboard', 1, 60)
            bought(parent, 'fita LED branca quente 12 V, rolo 5 m', 1, 75.9, WEB['led'])
            bought(parent, 'fonte LED 12 V 5 A', 1, 39.84, WEB['driver'])
            bought(parent, 'perfil/difusor LED — 1 m', 4, 25)
            bought(parent, 'cabos, conectores e interruptor', 1, 45)
            bought(parent, 'kit de fixação à parede e chumbadores', 1, 70)
            bought(parent, 'adesivo e testeira REHAU impressos', 1, 130)
            bought(parent, 'fita de borda/acabamento MDF', 1, 45)
            bought(parent, 'embalagem de proteção para transporte', 1, 220)
            paint(parent, .8)
    return result


def create_quote():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    PHOTO.parent.mkdir(parents=True, exist_ok=True)
    if not PHOTO.exists():
        shutil.copy2(SOURCE, PHOTO)
    conn = get_connection()
    previous = conn.execute('SELECT id FROM projects WHERE code=?', (CODE,)).fetchone()
    if previous:
        project_id = previous['id']
        if conn.execute('SELECT 1 FROM materials WHERE project_id=? LIMIT 1',
                        (project_id,)).fetchone():
            conn.close()
            return project_id
    else:
        backup_dir = Path(DATA_DIR) / 'backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f'before_rehau_photo_{date.today().isoformat()}.db'
        if not backup.exists():
            with sqlite3.connect(backup) as destination:
                conn.backup(destination)
        conn.close()
        project_id = create_project(ProjectCreate(
            name=NAME, code=CODE, client='REHAU', date=date.today().isoformat(),
            folder_path=str(PHOTO.parent),
            notes=('Estimativa de custo de materiais para 1 unidade de cada expositor '
                   'baseada somente na imagem. Produtos REHAU (rolos e amostras) '
                   'fornecidos pelo cliente. A fabricação e montagem na oficina e reserva técnica '
                   'estão na memória de orçamento, fora das duas planilhas modelo. '
                   'Sem frete, instalação no cliente, impostos de venda ou markup. '
                   'Dimensões do giratório e do painel e todos os cortes são hipóteses.')))['id']
        conn = get_connection()
    items = build_items(conn, project_id)
    for item in items:
        columns = tuple(item)
        conn.execute('INSERT INTO materials (' + ','.join(columns) + ') VALUES (' +
                     ','.join('?' for _ in columns) + ')', tuple(item.values()))
    for title, description in (
        ('Geometria do expositor de chão',
         'Dez rolos de Ø180 mm em 1900 mm de altura deixam pouco espaço para base e testeira. Confirmar se 10 cores equivalem a 10 rolos montados ou se parte é mostrada por chaveiros/amostras.'),
        ('Dimensões e capacidade de carga',
         'Giratório estimado em 1900 mm de altura e base de 750 mm; painel estimado em 1800×1200 mm. Confirmar carga de 32 rolos de até 1 kg mais estrutura, mancal e ancoragens.'),
        ('Fonte e escopo do custo',
         'Rolos/fita e amostras REHAU fornecidos pelo cliente; custo inclui suportes, fixação, iluminação, acabamento e embalagem. Confirmar preços de compra e engenharia antes de emitir proposta final.'),
    ):
        conn.execute('''INSERT INTO pending_decisions
            (project_id,title,description,impact_level,proposed_action)
            VALUES (?,?,?,?,?)''',
            (project_id, title, description, 'ALTO', 'Validar protótipo e fornecedores.'))
    conn.execute("UPDATE projects SET status='PRELIMINAR' WHERE id=?", (project_id,))
    conn.commit()
    conn.close()
    return project_id


def write_report(project_id, export_dir):
    full = get_project_full_data(project_id)
    totals = defaultdict(float)
    for row in full['materials']:
        if row['item_type'] != 'subconjunto':
            totals[row['parent_assembly']] += float(row.get('total_price') or 0)
    money = lambda value: f'{value:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    lines = [
        '# REHAU — custo preliminar de fabricação pela imagem', '',
        f'Data: {date.today().isoformat()}. Projeto no app: #{project_id}. '
        'Quantidade: **1 unidade de cada um dos três modelos**.', '',
        'Os rolos, fitas e amostras de cores são fornecidos pelo cliente. '
        'Os modelos originais CÁLCULO e CUSTO incluem todas as matérias-primas '
        'e comprados; a mão de obra de fabricação e montagem é somada abaixo. Frete, instalação '
        'no cliente, tributos de venda e markup serão definidos depois.', '',
        '| Modelo | Materiais | Fabricação e montagem | Reserva técnica 7% | Custo estimado |',
        '|---|---:|---:|---:|---:|',
    ]
    for parent in PARENTS:
        contingency = round((totals[parent] + LABOR[parent]) * CONTINGENCY, 2)
        cost = totals[parent] + LABOR[parent] + contingency
        lines.append(f'| {parent} | R$ {money(totals[parent])} | '
                     f'R$ {money(LABOR[parent])} | R$ {money(contingency)} | '
                     f'**R$ {money(cost)}** |')
    material_total = sum(totals.values())
    labor_total = sum(LABOR.values())
    reserve_total = sum(round((totals[p] + LABOR[p]) * CONTINGENCY, 2) for p in PARENTS)
    lines.extend([f'| **Total das três peças** | **R$ {money(material_total)}** | '
                  f'**R$ {money(labor_total)}** | **R$ {money(reserve_total)}** | '
                  f'**R$ {money(material_total + labor_total + reserve_total)}** |',
                  '', 'Mão de obra de fabricação, acabamento e montagem estimada na oficina: 16 h, 24 h e 14 h por modelo, '
                  'a R$ 45/h. Reserva técnica moderada de 7% cobre ajustes '
                  'normais de protótipo. Não aplicar novamente esses dois valores '
                  'no markup. As planilhas preservam os modelos originais da empresa.', '',
                  '## Hipóteses de engenharia', '',
                  '- Chão: 1900×500×500 mm é a única medida externa indicada. '
                  'Os 10 conjuntos de eixos foram orçados para não faltar suporte, '
                  'mas dez rolos Ø180 mm em uma coluna podem exigir outra distribuição.',
                  '- Giratório: 1900 mm de altura, base 750 mm, quatro faces com oito '
                  'rolos por face. Confirmar mancal, esforço e estabilidade com carga.',
                  '- Parede: painel estimado 1800×1200 mm, com cinco eixos, '
                  '32 suportes removíveis, moodboard, LED, fonte e ancoragens.',
                  '- Aço: tubo/chapa pelo peso geométrico e regras aprovadas do app. '
                  'MDF: R$ 730 por chapa 2750×1850 mm do orçamento BUD de 21/10/2026, '
                  'rateado pela área com 12% para recortes. Ferragens especiais, '
                  'impressão e embalagem têm preços preliminares de protótipo.', '',
                  '## Fontes de alguns componentes comprados', ''])
    for key, url in WEB.items():
        lines.append(f'- {key}: {url}')
    lines.extend(['', '## Conferência pendente', '',
                  '- Fazer desenho cotado, verificar carga e acomodação dos rolos.',
                  '- Cotar eixos, buchas, adesivos, MDF, embalagem e instalação com fornecedores.',
                  '- Comparar custo e perdas depois do protótipo; o total é estimativa '
                  'de fabricação, não preço de venda.', '',
                  f'Arquivos preenchidos: `{export_dir}`.', ''])
    REPORT.write_text('\n'.join(lines), encoding='utf-8')
    return totals


if __name__ == '__main__':
    project_id = create_quote()
    archive = export_template_reports(get_project_full_data(project_id), project_id, 'planilhas')
    totals = write_report(project_id, archive.parent)
    print(json.dumps({'project_id': project_id, 'archive': str(archive),
                      'report': str(REPORT), 'totals': totals}, ensure_ascii=False, indent=2))
