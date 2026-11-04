"""One-photo estimate for a four-face, manually rotated REHAU display.

Keep this variant separate from the previous three-display and floor quotes.
The cut dimensions are hypotheses; the bearing rating is not a tipping test.
"""

from datetime import date
from pathlib import Path
import json
import shutil
import sqlite3

from app import ProjectCreate, create_project, get_project_full_data
from config import DATA_DIR
from database import get_connection
from mass_math import calculated_weight, ceil_kg
from pricing import approved_rules, price_item
from template_reports import export_template_reports


SOURCE = Path(r'C:\Users\Luis\AppData\Local\Temp\codex-clipboard-fad9422a-1ab5-47ef-91b8-c85bd373ca4c.png')
CODE = 'REHAU-GIRATORIO-PSAI-32-ROLOS-20261022'
NAME = 'REHAU expositor giratório — 32 rolos em 4 faces, PSAI'
PHOTO = Path(DATA_DIR) / 'photo_sources' / f'{CODE}.png'
REPORT = Path(DATA_DIR) / 'REHAU_GIRATORIO_PSAI_32_ROLOS_20261022.md'
SKETCH = Path(DATA_DIR) / 'REHAU_GIRATORIO_PSAI_32_ROLOS_20261022.svg'
MANUAL_WORKBOOK = (Path(DATA_DIR) / 'exports' / 'modelos_99_770e71611201' /
                   'PLANILHA DE CUSTO - REHAU_expositor_de_chão_10_rolos_fechamento_PSAI.xlsx')
BEARING_SPEC = 'https://www.fgvtn.com.br/produto/prato-giratorio-pg-1012'
BEARING_PRICE = 'https://www.madeirasgasometro.com.br/prato-giratorio/p'
LABOR_HOURS = 42
HOURLY_RATE = 45
RESERVE = .07


def build_items(conn, project_id):
    rules = approved_rules(conn)
    rows = []

    def add(description, group, item_type, material, quantity, *, length=0,
            width=0, depth=0, thickness=0, weight=0, unit_price=None,
            price_source='', note='', unit='un'):
        n = len(rows) + 1
        row = dict(project_id=project_id, item_num=n, description=description,
                   group_name=group, item_type=item_type, material=material,
                   quantity=quantity, unit=unit, length=length, width=width,
                   depth=depth, thickness=thickness, radius_diam=0,
                   unit_weight=weight, total_weight=ceil_kg(weight * quantity),
                   unit_area=round(length * width / 1_000_000, 6) if width else 0,
                   total_area=round(length * width * quantity / 1_000_000, 6) if width else 0,
                   drawing_id=f'{CODE}-{n:03d}', confidence=.4,
                   parent_assembly=NAME, is_inferred=1, source_page=PHOTO.name,
                   pending_issue=note, observation=note, unit_price=unit_price,
                   price_source=price_source)
        if unit_price is None:
            row['unit_price'], row['price_source'] = price_item(row, rules, conn)
        row['total_price'] = (round(row['unit_price'] * quantity, 2)
                              if row['unit_price'] is not None else None)
        rows.append(row)

    def tube(role, side, gauge, length, quantity):
        material = f'Tubo quadrado aço carbono {side}x{side}x{gauge}mm'
        weight = ceil_kg(calculated_weight(dict(
            group_name='Tubo Quadrado/Retangular', material=material,
            length=length, width=side, depth=side, thickness=gauge)))
        gauge_text = f'{gauge:g}'.replace('.', ',')
        add(f'TUBO QUADRADO {side}X{side}X{gauge_text}MM - {role} - {length}MM',
            'Tubo Quadrado/Retangular', 'materia_prima', material, quantity,
            length=length, width=side, depth=side, thickness=gauge, weight=weight,
            note='Corte estimado pela foto; confirmar gabarito e interferência no giro.')

    def sheet(role, length, width, gauge, quantity):
        material = f'Chapa aço carbono {gauge} mm'
        weight = ceil_kg(calculated_weight(dict(
            group_name='Chapa', material=material, length=length,
            width=width, thickness=gauge)))
        add(f'CHAPA AÇO CARBONO #{gauge:g}MM - {role} - {length}X{width}MM',
            'Chapa', 'materia_prima', material, quantity, length=length,
            width=width, thickness=gauge, weight=weight,
            note='Placa de fixação; furação e corte a confirmar no mancal escolhido.')

    def psai(role, length, width, quantity=1, note=''):
        material = 'PSAI PRETO 2,0 mm'
        weight = ceil_kg(calculated_weight(dict(
            group_name='Polímero/PSAI', material=material, length=length,
            width=width, thickness=2)))
        add(f'PSAI {role} {length}X{width}X2MM', 'Polímero/PSAI',
            'comprado', material, quantity, length=length, width=width,
            thickness=2, weight=weight,
            note=('Corte bruto estimado; painel de acabamento, não portante. ' + note).strip())

    def bought(label, quantity, price, source, *, weight=0, length=0, note=''):
        add(label, 'Outros Comprados', 'comprado', label, quantity,
            length=length, weight=weight, unit_price=price,
            price_source=source, note=note)

    # Fixed base. A 600 mm square frame fits under the 900 mm round cover.
    tube('BASE FIXA QUADRO INFERIOR/SUPERIOR', 30, 1.5, 600, 8)
    tube('BASE FIXA TRAVESSAS DO MANCAL', 30, 1.5, 600, 4)
    tube('BASE FIXA ESPAÇADORES', 30, 1.5, 120, 4)
    # The four-face carrier turns; the PSAI skins do not carry the roll weight.
    tube('MIOLO GIRATÓRIO MONTANTES 4 FACES', 30, 1.5, 1600, 4)
    tube('MIOLO GIRATÓRIO QUADROS INFERIOR/SUPERIOR', 30, 1.5, 330, 8)
    tube('MIOLO GIRATÓRIO AMARRAÇÃO INTERMEDIÁRIA', 25, 1.5, 330, 8)
    tube('TESTEIRA SUPERIOR SUPORTE SEGMENTADO', 25, 1.5, 315, 8)
    tube('CONTRAVENTAMENTO DO MIOLO', 20, 1.2, 550, 8)
    sheet('PLACAS SANDUÍCHE DO PRATO GIRATÓRIO', 350, 350, 4, 2)
    sheet('PLACAS DE FIXAÇÃO DOS PÉS NIVELADORES', 80, 80, 4, 4)

    psai('PAINEL FACE GIRATÓRIA', 1590, 330, 4)
    psai('TESTEIRA CURVA METADE', 1270, 200, 2,
         'Duas metades precisam de conformação a quente e união.')
    psai('TAMPA SUPERIOR BLANK', 820, 820)
    psai('SAIA BASE FIXA METADE', 1420, 150, 2,
         'Duas metades precisam de conformação a quente.')
    psai('TAMPA DA BASE FIXA BLANK', 900, 900)

    # Previous manually edited workbook established levelers, price holders,
    # rivet nuts and knobs for this customer's floor display.
    manual = f'Ajuste manual REHAU #99 em {MANUAL_WORKBOOK.name}'
    bought('PÉ NIVELADOR M12 - CARGA ALVO 100KG', 4, 24.51, manual,
           note='Capacidade de 100 kg por pé ainda precisa de confirmação com fornecedor.')
    bought('EIXO ROLO Ø12X260MM COM BUCHAS', 32, 18.00,
           'Estimativa de protótipo a partir da solução de eixos #99',
           length=260, weight=.18,
           note='32 rolos fornecidos pelo cliente; largura axial útil assumida até 300 mm.')
    bought('PORTA PREÇO 250MM', 32, 1.70,
           'Regra aprovada porta preço/etiqueta R$ 6,80/m × 0,25 m',
           length=250)
    bought('PORCA REBITE M8 PARA EIXOS E TESTEIRA', 72, .25, manual,
           note='64 nos suportes dos rolos e 8 nos fechamentos.')
    bought('MANÍPULO DE RETENÇÃO DOS ROLOS', 32, .25, manual,
           note='Um manípulo por rolo; confirmar bitola e custo unitário.')
    bought('PRATO GIRATÓRIO FGVTN PG1012 Ø309MM 200KG', 1, 122.22,
           f'FGVTN: {BEARING_SPEC}; preço referência: {BEARING_PRICE}',
           weight=2.0,
           note='Carga declarada 200 kg para prato de mesa; momento lateral da torre exige ensaio.')
    bought('KIT GUIA RADIAL CENTRAL COM EIXO CURTO E BUCHA', 1, 180.00,
           'Estimativa de usinagem e mancal para protótipo', weight=1.5,
           note='Guia radial acima do prato; não substitui a verificação de tombamento.')
    bought('TRAVA DE GIRO 4 POSIÇÕES COM PINO', 1, 45.00,
           'Estimativa de protótipo', note='Trava manual nas quatro faces e batente de segurança.')
    bought('PARAFUSOS DO MANCAL, FIXADORES PSAI E ARRUELAS', 1, 80.00,
           'Estimativa de protótipo', weight=1.0)
    bought('CONFORMAÇÃO A QUENTE E ACABAMENTO DO PSAI CURVO', 1, 180.00,
           'Estimativa de serviço para testeira e saia da base',
           note='Confirmar raio mínimo e qualidade da dobra de PSAI 2 mm.')
    bought('ADESIVOS REHAU E IMPRESSÃO TESTEIRA CURVA', 1, 230.00,
           'Estimativa de comunicação visual da foto')
    bought('ACABAMENTO DAS BORDAS PSAI', 1, 60.00,
           'Estimativa de serviço')
    bought('EMBALAGEM REFORÇADA PARA TRANSPORTE', 1, 260.00,
           'Estimativa de protótipo')
    add('TINTA PRETA A PÓ - CONSUMO 1,8KG', 'Pintura a Pó',
        'materia_prima', 'TINTA PÓ PRETA', 1.8, unit='kg', weight=1,
        unit_price=rules['mp_tinta_po'],
        price_source=f"Regra aprovada mp_tinta_po R$ {rules['mp_tinta_po']:.2f}/kg",
        note='Consumo inferido; serviço de pintura está na mão de obra.')
    return rows


def mechanical_checks(rows):
    metal_kg = sum(float(r['total_weight']) for r in rows
                   if r['group_name'] in ('Tubo Quadrado/Retangular', 'Chapa'))
    psai_kg = sum(float(r['total_weight']) for r in rows
                  if r['group_name'] == 'Polímero/PSAI')
    bought_kg = sum(float(r['total_weight']) for r in rows
                    if r['item_type'] == 'comprado' and r['group_name'] != 'Polímero/PSAI')
    empty_kg = metal_kg + psai_kg + bought_kg
    design_kg = empty_kg + 2 * 32  # 32 rolls, 1 kg each, factor two
    return dict(overall_height_mm=1900, roll_diameter_mm=180, rolls_per_face=8,
                clearance_mm=10, stack_height_mm=8 * 180 + 7 * 10,
                available_roll_height_mm=1530,
                metal_kg=round(metal_kg, 3), psai_kg=round(psai_kg, 3),
                empty_kg=round(empty_kg, 3),
                bearing_design_load_kg=round(design_kg, 3),
                bearing_static_rating_kg=200,
                leveler_three_point_kg=round(design_kg / 3, 3),
                leveler_target_kg=100)


def create_quote():
    if not SOURCE.is_file():
        raise FileNotFoundError(SOURCE)
    PHOTO.parent.mkdir(parents=True, exist_ok=True)
    if not PHOTO.exists():
        shutil.copy2(SOURCE, PHOTO)
    conn = get_connection()
    existing = conn.execute('SELECT id FROM projects WHERE code=?', (CODE,)).fetchone()
    if existing:
        project_id = existing['id']
        if conn.execute('SELECT 1 FROM materials WHERE project_id=? LIMIT 1',
                        (project_id,)).fetchone():
            conn.close()
            return project_id
        conn.close()
        raise RuntimeError('Projeto existente sem materiais: conferir antes de preencher.')
    backup = Path(DATA_DIR) / 'backups' / f'before_rehau_rotating_psai_{date.today().isoformat()}.db'
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        with sqlite3.connect(backup) as destination:
            conn.backup(destination)
    conn.close()
    project_id = create_project(ProjectCreate(
        name=NAME, code=CODE, client='REHAU', date=date.today().isoformat(),
        folder_path=str(PHOTO.parent),
        notes=('Estimativa separada pela foto: expositor giratório manual de 1900 mm, '
               '32 rolos fornecidos pelo cliente em 4 faces de 8. Estrutura fixa '
               'tubular com 4 pés niveladores; corpo de tubos sobre prato giratório '
               '200 kg, guia radial e trava em 4 posições; revestimento PSAI 2 mm. '
               'Cortes e compatibilidade do giro exigem protótipo. Sem MDF, chapa '
               '10 mm, rodízios, frete, instalação, tributos de venda e markup.')))['id']
    conn = get_connection()
    for item in build_items(conn, project_id):
        columns = tuple(item)
        conn.execute('INSERT INTO materials (' + ','.join(columns) + ') VALUES (' +
                     ','.join('?' for _ in columns) + ')', tuple(item.values()))
    for title, description in (
        ('Protótipo e rotação sob carga',
         'Confirmar giro 360° livre, guia radial, folga da testeira, trava das quatro faces, fixação do mancal e momento lateral com 32 rolos. Capacidade 200 kg declarada para prato não comprova estabilidade da torre.'),
        ('Largura dos rolos e altura',
         'Cada face comporta 8 rolos Ø180 mm com vão vertical aproximado 10 mm; largura axial de cada rolo assumida até 300 mm. Medir amostra antes do corte.'),
        ('Estabilidade da base',
         'Base circular estimada Ø900 mm, quadro inferior 600×600 mm e quatro pés; ensaiar tombamento, frenagem manual e piso irregular. Confirmar capacidade real de cada pé.'),
    ):
        conn.execute('''INSERT INTO pending_decisions
            (project_id,title,description,impact_level,proposed_action)
            VALUES (?,?,?,?,?)''',
            (project_id, title, description, 'ALTO', 'Medir, cotar e ensaiar protótipo.'))
    conn.execute("UPDATE projects SET status='PRELIMINAR' WHERE id=?", (project_id,))
    conn.commit()
    conn.close()
    return project_id


def write_report(project_id, export_dir):
    rows = [r for r in get_project_full_data(project_id)['materials']
            if r['item_type'] != 'subconjunto']
    mp = round(sum(float(r['total_price']) for r in rows
                   if r['item_type'] == 'materia_prima'), 2)
    bought = round(sum(float(r['total_price']) for r in rows
                       if r['item_type'] == 'comprado'), 2)
    labor = LABOR_HOURS * HOURLY_RATE
    reserve = round((mp + bought + labor) * RESERVE, 2)
    total = round(mp + bought + labor + reserve, 2)
    checks = mechanical_checks(rows)
    brl = lambda x: f'{x:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    REPORT.write_text(f'''# REHAU — expositor giratório PSAI, 32 rolos em quatro faces

Data: {date.today().isoformat()}. Projeto no app: #{project_id}. Quantidade: **1 expositor**.
Fonte: foto {SOURCE.name} e ajustes manuais da planilha de custo anterior {MANUAL_WORKBOOK.name}.
Os rolos são fornecidos pelo cliente; estrutura, suportes, mecanismo, PSAI e montagem estão no custo. A foto não é desenho técnico.

| Parcela | Custo estimado |
|---|---:|
| Matéria-prima — tubos, chapas 4 mm de fixação e tinta | R$ {brl(mp)} |
| Comprados — PSAI, eixos, rolamento, guia, trava e ferragens | R$ {brl(bought)} |
| Fabricação, conformação estrutural, solda, pintura e montagem: {LABOR_HOURS} h × R$ {HOURLY_RATE}/h | R$ {brl(labor)} |
| Reserva de protótipo: 7% | R$ {brl(reserve)} |
| **Custo estimado de fabricação** | **R$ {brl(total)}** |

As planilhas originais levam somente MP e comprados (R$ {brl(mp+bought)}). A mão de obra e a reserva constam só nesta memória; não as somar novamente no markup. Frete, instalação no cliente, tributos de venda e markup estão fora.

## Como os ajustes anteriores foram aplicados

- Mesmo padrão de nomes e bitolas no custo: TUBO QUADRADO, CHAPA AÇO CARBONO, PSAI TESTEIRA/PAINEL/BASE e medidas por linha. Os cortes de funções diferentes permanecem separados.
- A planilha anterior passou a usar **pé nivelador, porta-preço, porca rebite e manípulo**. Eles foram levados à variante giratória com quantidades próprias para 32 rolos. Não há MDF, rodízio ou chapa de 10 mm.
- Preços de pés, porcas rebite e manípulos vêm da sua planilha editada; os demais acessórios sem tarifa aprovada são **estimativas de protótipo** identificadas em cada item. Porta-preço: 32 × 250 mm × R$ 6,80/m.

## Geometria e mecanismo propostos

- **Altura total 1900 mm**, como no expositor de chão. Quatro faces × oito posições = **32 rolos Ø180 mm**, até 1 kg por rolo. Oito diâmetros + sete folgas de 10 mm ocupam {checks['stack_height_mm']} mm dentro dos {checks['available_roll_height_mm']} mm destinados aos rolos. A folga é estreita e depende do rolo real.
- Núcleo quadrado estimado em 330 mm de face; largura axial útil assumida **até 300 mm** por rolo. Envelope externo de giro aproximado Ø760–820 mm. Base fixa Ø900 mm e tampa superior Ø820 mm são hipóteses da foto.
- Base **fixa**: quadro de tubos 600×600 mm, quatro pés niveladores, placas de aço 4 mm para o mancal. Corpo de quatro faces **gira manualmente** sobre o prato FGVTN PG1012 Ø309 mm, 360°, nominal 200 kg. Guia radial central limita a oscilação; pino trava as quatro faces na posição de exposição. PSAI preto 2 mm apenas fecha e identifica as faces; tubos e eixos carregam os rolos.
- O fabricante informa 200 kg para o prato; preço observado R$ 122,22 na referência indicada em 22/10/2026. A carga de pré-dimensionamento aqui é {checks['bearing_design_load_kg']:.1f} kg: massa vazia calculada {checks['empty_kg']:.1f} kg + 64 kg (32 rolos com fator 2). Em três pés, a média idealizada é {checks['leveler_three_point_kg']:.1f} kg por pé. Isso **não verifica momento lateral, tombamento, solda, carga fora de centro nem operação repetida**.

## Antes de fabricar

1. Medir diâmetro, largura e centro de cada rolo; validar oito posições por face, troca individual e ausência de colisão entre faces.
2. Fazer protótipo do prato, guia e trava e ensaiar o giro carregado, a oscilação da torre e a fixação do mancal. O prato de mesa não está homologado aqui como conjunto do expositor.
3. Ensaiar estabilidade e conferir a capacidade dos quatro pés com fornecedor. Para uso público, definir se a base precisa ser maior ou ancorada.
4. Confirmar raio e acabamento da testeira curva e da saia de PSAI; confirmar tarifas provisórias e prazo de fabricação.

Prato: {BEARING_SPEC}. Preço de referência: {BEARING_PRICE}.
Esquema de orçamento: {SKETCH}. Planilhas preenchidas: {export_dir}.
''', encoding='utf-8')
    return dict(mp=mp, bought=bought, labor=labor, reserve=reserve,
                total=total, checks=checks)


def write_sketch():
    roll_rows = ''.join(
        f'<rect x="{x}" y="{y}" width="120" height="42" rx="18" fill="#9e8065" stroke="#362c25" stroke-width="3"/>'
        for x in (150, 430) for y in range(194, 584, 55))
    SKETCH.write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 800">
<rect width="900" height="800" fill="white"/>
<style>text{{font:16px Arial;fill:#17243a}} .small{{font:13px Arial}}</style>
<text x="32" y="36" font-size="22" font-weight="bold">REHAU — 32 rolos, 4 faces giratórias, 1900 mm</text>
<text x="32" y="60" class="small">Esquema de orçamento; não é desenho de fabricação</text>
<ellipse cx="350" cy="704" rx="270" ry="55" fill="#202126"/>
<rect x="115" y="627" width="470" height="73" fill="#23252a"/>
<ellipse cx="350" cy="627" rx="235" ry="35" fill="#25262a"/>
<rect x="150" y="178" width="400" height="440" fill="#242526"/>
<rect x="150" y="118" width="400" height="75" fill="#202126"/>
{roll_rows}
<rect x="300" y="647" width="100" height="11" fill="#8b9297"/>
<text x="608" y="164">4 faces × 8 rolos = 32</text>
<text x="608" y="204">Corpo tubular gira 360°</text>
<text x="608" y="244">Prato Ø309 / guia radial</text>
<text x="608" y="284">Trava em 4 posições</text>
<text x="608" y="324">Base fixa com 4 pés</text>
<text x="608" y="364">Fechamentos PSAI 2 mm</text>
<text x="608" y="424">Altura: 1900 mm</text>
<text x="608" y="464">Base estimada: Ø900 mm</text>
<text x="608" y="524" fill="#a83a22">Validar rolos e tombamento</text>
<path d="M230 746 A130 32 0 0 0 470 746" stroke="#2672a8" stroke-width="4" fill="none"/>
<text x="310" y="782">GIRO 360°</text>
</svg>''', encoding='utf-8')


if __name__ == '__main__':
    project_id = create_quote()
    archive = export_template_reports(get_project_full_data(project_id),
                                      project_id, 'planilhas')
    write_sketch()
    totals = write_report(project_id, archive.parent)
    print(json.dumps({'project_id': project_id, 'archive': str(archive),
                      'report': str(REPORT), 'sketch': str(SKETCH),
                      'totals': totals}, ensure_ascii=False, indent=2))
