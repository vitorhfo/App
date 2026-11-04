"""One-photo estimate for a ten-roll REHAU floor display clad in PSAI.

This is a separate variant from the eight-roll/MDF quote. Never overwrite a
previous photo estimate or turn inferred dimensions into global rules.
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


SOURCE = Path(r'C:\Users\Luis\AppData\Local\Temp\codex-clipboard-ff15a320-a1b4-4bd6-b21d-99757420c86c.png')
CODE = 'REHAU-CHAO-PSAI-10-ROLOS-20261022'
NAME = 'REHAU expositor de chão — 10 rolos, fechamento PSAI'
PHOTO = Path(DATA_DIR) / 'photo_sources' / f'{CODE}.png'
REPORT = Path(DATA_DIR) / 'REHAU_CHAO_PSAI_10_ROLOS_20261022.md'
SKETCH = Path(DATA_DIR) / 'REHAU_CHAO_PSAI_10_ROLOS_20261022.svg'
LABOR_HOURS = 24
HOURLY_RATE = 45
RESERVE = .07
STEEL_DENSITY_KG_M3 = 7850
PSAI_DENSITY_KG_M3 = 1050  # estimated sheet density for handling/load estimate
CASTER_URL = ('https://www.gerbran.com.br/'
              'rodizio-de-borracha-2-x22-giratorio-com-freio-50kg')


def build_items(conn, project_id):
    rules = approved_rules(conn)
    rows = []

    def add(label, group, item_type, material, quantity, *, length=0, width=0,
            depth=0, thickness=0, weight=0, unit_price=None, source='', note='', unit='un'):
        n = len(rows) + 1
        row = dict(project_id=project_id, item_num=n, description=label,
                   group_name=group, item_type=item_type, material=material,
                   quantity=quantity, unit=unit, length=length, width=width,
                   depth=depth, thickness=thickness, radius_diam=0,
                   unit_weight=weight, total_weight=ceil_kg(weight * quantity),
                   unit_area=round(length * width / 1_000_000, 6) if width else 0,
                   total_area=round(length * width * quantity / 1_000_000, 6) if width else 0,
                   drawing_id=f'{CODE}-{n:03d}', confidence=.4,
                   parent_assembly=NAME, is_inferred=1, source_page=PHOTO.name,
                   pending_issue=note, observation=note,
                   unit_price=unit_price, price_source=source)
        if unit_price is None:
            row['unit_price'], row['price_source'] = price_item(row, rules, conn)
        row['total_price'] = (round(row['unit_price'] * quantity, 2)
                              if row['unit_price'] is not None else None)
        rows.append(row)

    def tube(label, side, thickness, length, quantity):
        material = f'Tubo quadrado aço carbono {side}x{side}x{thickness}mm'
        weight = ceil_kg(calculated_weight(dict(group_name='Tubo Quadrado/Retangular',
            material=material, length=length, width=side, depth=side,
            thickness=thickness)))
        gauge = f'{thickness:g}'.replace('.', ',')
        add(f'TUBO QUADRADO {side}X{side}X{gauge}MM - {label.upper()} - {length}MM',
            'Tubo Quadrado/Retangular', 'materia_prima', material, quantity,
            length=length, width=side, depth=side, thickness=thickness,
            weight=weight, note='Corte proposto pela foto; validar desenho antes de fabricar.')

    def sheet(label, length, width, thickness, quantity):
        material = f'Chapa aço carbono {thickness} mm'
        weight = ceil_kg(calculated_weight(dict(group_name='Chapa',
            material=material, length=length, width=width, thickness=thickness)))
        gauge = f'{thickness:g}'.replace('.', ',')
        add(f'CHAPA AÇO {label.upper()} {length}X{width}X{gauge}MM', 'Chapa',
            'materia_prima', material, quantity, length=length, width=width,
            thickness=thickness, weight=weight,
            note='Corte proposto; conferir furos, solda e posição dos rodízios.')

    def psai(label, length, width, quantity=1):
        area = length * width / 1_000_000
        weight = round(area * .002 * PSAI_DENSITY_KG_M3, 6)
        add(f'PSAI {label.upper()} {length}X{width}X2MM', 'Polímero/PSAI',
            'comprado', 'PSAI PRETO 2,0 mm', quantity,
            length=length, width=width, thickness=2, weight=weight,
            note=('Corte e densidade inferidos da imagem. Revestimento, não peça '
                  'portante; preço CONTROLV pela área 0x0, preto = branco +10%.'))

    def bought(label, quantity, price, source='Estimativa para protótipo', weight=0):
        add(label, 'Outros Comprados', 'comprado', label, quantity,
            weight=weight, unit_price=price, source=source,
            note='Preço/solução de protótipo; confirmar fornecedor e especificação.')

    # Ten rolls require two columns of five in the pictured 1900×500×500 envelope.
    # Three front posts split the 500 mm width into ~205 mm bays.
    tube('montantes dianteiros (esquerda, centro, direita) e traseiros', 30, 1.5, 1820, 5)
    tube('quadro de base e quadro superior', 30, 1.5, 440, 8)
    tube('grade de apoio da tampa PSAI na base', 30, 1.5, 440, 5)
    tube('travessas dianteiras dos cinco níveis de rolos', 25, 1.5, 440, 5)
    tube('travessas traseiras de amarração', 25, 1.5, 440, 5)
    tube('contraventamentos laterais/traseiros', 20, 1.2, 600, 4)
    sheet('chapas de reforço e fixação dos rodízios', 80, 80, 4, 4)

    psai('TRASEIRO', 1700, 440)
    psai('LATERAL', 1700, 470, 2)
    psai('TESTEIRA', 500, 220, 2)
    psai('TAMPA BASE', 500, 500)
    psai('SAIA BASE FRONTAL/TRASEIRA', 500, 150, 2)
    psai('SAIA BASE LATERAL', 500, 150, 2)
    psai('TAMPA SUPERIOR', 500, 500)

    bought('kit de eixo, buchas e batentes, carga mínima 2 kg por rolo', 10, 28)
    bought('ganchos laterais para chaveiros', 16, 3.8)
    bought('rodízio giratório 2 pol. com freio, capacidade nominal 50 kg', 4,
           24.51, CASTER_URL, .26)
    bought('kit anti-tombo removível para uso estacionário', 1, 35)
    bought('plaquetas de identificação das dez cores', 10, 5.5)
    bought('acabamento e colagem das bordas de PSAI', 1, 35)
    bought('parafusos, porcas M8, inserts e fixadores para PSAI', 1, 85)
    bought('adesivos e testeira REHAU impressos', 1, 120)
    bought('embalagem de proteção para transporte', 1, 180)
    add('tinta a pó preta — consumo estimado', 'Pintura a Pó', 'materia_prima',
        'TINTA PÓ PRETA', 1.4, weight=1, unit='kg',
        unit_price=rules['mp_tinta_po'],
        source=f"Regra aprovada mp_tinta_po: R$ {rules['mp_tinta_po']:.2f}/kg",
        note='Consumo inferido; serviço de acabamento incluído na mão de obra.')
    return rows


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
        raise RuntimeError('Projeto já existe sem materiais; conferir antes de preencher.')
    backup = Path(DATA_DIR) / 'backups' / f'before_rehau_floor_psai_{date.today().isoformat()}.db'
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        with sqlite3.connect(backup) as destination:
            conn.backup(destination)
    conn.close()
    project_id = create_project(ProjectCreate(
        name=NAME, code=CODE, client='REHAU', date=date.today().isoformat(),
        folder_path=str(PHOTO.parent),
        notes=('Hipótese de foto para um expositor 1900×500×500 mm. '
               'Dez rolos REHAU de até 1 kg fornecidos pelo cliente, dispostos '
               'em duas colunas de cinco. Todas as peças antes em MDF foram '
               'substituídas por PSAI preto 2 mm comprado. Base é quadro de tubo '
               'com grade interna e tampa de PSAI, sem chapa de lastro. Cortes propostos, '
               'não validados por desenho. Mão de obra e reserva '
               'somadas na memória de custo fora dos modelos de material. '
               'Sem frete, instalação, imposto de venda ou markup.')))['id']
    conn = get_connection()
    for item in build_items(conn, project_id):
        columns = tuple(item)
        conn.execute('INSERT INTO materials (' + ','.join(columns) + ') VALUES (' +
                     ','.join('?' for _ in columns) + ')', tuple(item.values()))
    for title, description in (
        ('Largura axial e disposição dos rolos',
         'Confirmar se cada rolo Ø180 mm tem largura axial até 190 mm para caber em dois vãos lado a lado; se não tiver, redesenhar o expositor.'),
        ('Estabilidade e uso público',
         'Estrutura suporta carga estática proposta, mas 500×500 mm com 1900 mm de altura requer ensaio contra tombamento. Usar anti-tombo no local de exposição.'),
        ('Ferragens e custo',
         'Confirmar capacidade dos eixos, soldas, travas, rodízios, painel PSAI 2 mm e preços de protótipo antes da proposta final. Não pisar na tampa de PSAI.'),
    ):
        conn.execute('''INSERT INTO pending_decisions
            (project_id,title,description,impact_level,proposed_action)
            VALUES (?,?,?,?,?)''',
            (project_id, title, description, 'ALTO', 'Validar amostra e desenho técnico.'))
    conn.execute("UPDATE projects SET status='PRELIMINAR' WHERE id=?", (project_id,))
    conn.commit()
    conn.close()
    return project_id


def structural_checks():
    # Centre-loaded rail over 440 mm. This simple beam calculation checks only
    # elastic bending of the tube; welds, roll spindles and stability need tests.
    span_mm = 440
    load_n = 2 * 2 * 9.81  # two 1 kg rolls on each rail, with load factor two
    inertia_mm4 = (25 ** 4 - 22 ** 4) / 12
    moment_nmm = load_n * span_mm / 4
    stress_mpa = moment_nmm * 12.5 / inertia_mm4
    deflection_mm = load_n * span_mm ** 3 / (48 * 200_000 * inertia_mm4)
    caster_design_kg = 60  # 38 kg empty estimate + 20 kg rolls + 2 kg keychains
    return dict(rail_stress_mpa=stress_mpa, rail_deflection_mm=deflection_mm,
                caster_three_point_kg=caster_design_kg / 3,
                caster_nominal_kg=50,
                roll_stack_mm=5 * 180 + 4 * 40 + 220 + 150,
                frame_height_mm=1820,
                overall_height_mm=1820 + 74)


def write_report(project_id, export_dir):
    materials = [r for r in get_project_full_data(project_id)['materials']
                 if r['item_type'] != 'subconjunto']
    mp = sum(float(r['total_price']) for r in materials
             if r['item_type'] == 'materia_prima')
    bought = sum(float(r['total_price']) for r in materials
                 if r['item_type'] == 'comprado')
    labor = LABOR_HOURS * HOURLY_RATE
    reserve = round((mp + bought + labor) * RESERVE, 2)
    total = round(mp + bought + labor + reserve, 2)
    steel_kg = sum(float(r['total_weight']) for r in materials
                   if r['group_name'] in ('Chapa', 'Tubo Quadrado/Retangular'))
    psai_kg = sum(float(r['total_weight']) for r in materials
                  if r['group_name'] == 'Polímero/PSAI')
    checks = structural_checks()
    brl = lambda x: f'{x:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    text = f'''# REHAU — expositor de chão para 10 rolos, fechado em PSAI

Data: {date.today().isoformat()}. Projeto no app: #{project_id}. Quantidade: **1 expositor**.
Os rolos, fitas e amostras REHAU são fornecidos pelo cliente; suportes, estrutura, fechamento de PSAI e montagem estão incluídos. As variantes anteriores #97/#98 permanecem como histórico; **usar este #99 para o pedido atual**.

| Parcela | Estimativa |
|---|---:|
| Matéria-prima (tubos, chapas, tinta) | R$ {brl(mp)} |
| Comprados (PSAI, eixos, ferragens, rodízios, comunicação, embalagem) | R$ {brl(bought)} |
| Fabricação, solda, acabamento e montagem: {LABOR_HOURS} h × R$ {HOURLY_RATE}/h | R$ {brl(labor)} |
| Reserva técnica de protótipo: 7% | R$ {brl(reserve)} |
| **Custo estimado de fabricação** | **R$ {brl(total)}** |

As duas planilhas padrão registram apenas as peças e materiais (R$ {brl(mp + bought)}). Mão de obra e reserva técnica aparecem nesta memória para preservar o layout; não as aplicar novamente no markup. Frete, instalação no cliente, tributos de venda e markup não estão incluídos.

## Estrutura proposta

- Envelope da imagem: **1900 × 500 × 500 mm**. **Dez** rolos de Ø180 mm e até 1 kg cada; carga de produto **10 kg**, calculada também com fator 2 (**20 kg**) para pré-dimensionar suportes. Chaveiros estimados em mais 2 kg.
- Distribuição proposta: **duas colunas × cinco níveis**. Três montantes dianteiros de 30 mm separam a largura de 500 mm em dois vãos úteis próximos de 205 mm; a largura axial de cada rolo precisa ser **até 190 mm** com folga para troca. Cinco diâmetros de 180 mm + quatro folgas de 40 mm + testeira de 220 mm + plinto de 150 mm ocupam **1430 mm**, dentro do quadro de 1820 mm. Altura com rodízios de 74 mm: cerca de **1894 mm**.
- Cinco montantes 30×30×1,5 mm (três dianteiros, dois traseiros), quadros superior/inferior e grade de tubos 30×30×1,5 mm na base. Cinco travessas dianteiras e cinco traseiras 25×25×1,5 mm sustentam os níveis; contraventamento 20×20×1,2 mm. **Os tubos e eixos recebem a carga; PSAI não é estrutura portante.**
- Base visual: quadro de tubo **500×500 mm**, grade interna com travessas a cerca de 90 mm e **tampa superior PSAI preto 2 mm**. Laterais, traseiro, testeira, saia da base e tampa superior também são de PSAI preto 2 mm. **Sem MDF e sem chapa de 10 mm.** Há apenas quatro chapinhas 80×80×4 mm para fixar os rodízios.
- Aço orçado: **{steel_kg:.2f} kg**; PSAI inferido: **{psai_kg:.2f} kg**. Massa vazia aproximada com ferragens: **38 kg**; carregada com 10 rolos e chaveiros: **50 kg**.
- Quatro rodízios de **50 kg nominais cada**; se apenas três apoiarem sob carga de projeto de 60 kg, a parcela média é **{checks['caster_three_point_kg']:.1f} kg/rodízio**. Isso não verifica impacto, piso irregular nem frenagem.
- Uma travessa 25×25×1,5 mm, vão idealizado 440 mm e dois rolos por nível com carga 2×: tensão nominal **{checks['rail_stress_mpa']:.1f} MPa** e flecha **{checks['rail_deflection_mm']:.3f} mm** (aço E=200 GPa, apoio simples). Dimensionamento preliminar; soldas, eixos, suportes e centro de gravidade dependem de protótipo.

## Pendências antes de fabricar ou prometer estabilidade

1. Medir largura axial e ponto de fixação dos dez rolos; garantir vão útil de 190 mm, troca e retenção em cada eixo. Se forem mais largos, será necessário ampliar o expositor ou distribuir rolos em outra face.
2. Ensaiar a peça carregada contra tombamento e esforço lateral. Ao retirar o lastro, a margem contra empurrão diminui. A base de 500 mm e altura de 1900 mm exigem o kit anti-tombo ao expor parada ao público; para uso móvel livre, rever a base e refazer o teste.
3. Confirmar carga admissível dos eixos, fixações e rodízios, inclusive soldas e piso. O PSAI de 2 mm é acabamento: não pisar na tampa sem validação de carga localizada. Produto entregue pelo cliente não foi precificado.
4. Confirmar área e aproveitamento das chapas PSAI. A CONTROLV precifica preto 2 mm pela base branca 2 mm +10%, sem impressão; adesivos e comunicação são linhas separadas. Eixos e embalagem têm preço provisório.

Rodízio de referência: {CASTER_URL} (50 kg, R$ 24,51 à vista no acesso de 22/10/2026).
Esquema conceitual: `{SKETCH}`. Planilhas preenchidas: `{export_dir}`.
'''
    REPORT.write_text(text, encoding='utf-8')
    return dict(mp=round(mp, 2), bought=round(bought, 2), labor=labor,
                reserve=reserve, total=total, steel_kg=steel_kg,
                psai_kg=psai_kg, check=checks)


def write_sketch():
    # Concept drawing only. Not a cut or approval drawing.
    circles = []
    for y in (205, 315, 425, 535, 645):
        for x in (155, 330):
            circles.append(f'<rect x="{x-48}" y="{y-39}" width="96" height="78" rx="30" fill="#9d8067" stroke="#34251d" stroke-width="4"/>')
            circles.append(f'<ellipse cx="{x-48}" cy="{y}" rx="10" ry="34" fill="#514337"/>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 850 820">
<rect width="850" height="820" fill="white"/>
<style>text{{font:16px Arial;fill:#17243a}} .small{{font:13px Arial}} .dim{{stroke:#2b5c9a;stroke-width:2;marker-start:url(#a);marker-end:url(#a)}}</style>
<defs><marker id="a" markerWidth="8" markerHeight="8" refX="4" refY="4" orient="auto-start-reverse"><path d="M0 0 L8 4 L0 8Z" fill="#2b5c9a"/></marker></defs>
<text x="40" y="35" font-size="22" font-weight="bold">REHAU — 10 rolos, quadro tubular e fechamento PSAI</text>
<text x="40" y="60" class="small">Esquema de orçamento, não desenho de fabricação</text>
<rect x="90" y="90" width="350" height="650" fill="#f3f3f3" stroke="#111" stroke-width="6"/>
<rect x="90" y="90" width="350" height="67" fill="#222"/>
<text x="173" y="132" fill="white" font-weight="bold">TESTEIRA</text>
<rect x="90" y="690" width="350" height="50" fill="#222"/>
<rect x="106" y="158" width="12" height="532" fill="#444"/><rect x="260" y="158" width="12" height="532" fill="#444"/><rect x="412" y="158" width="12" height="532" fill="#444"/>
{''.join(circles)}
<circle cx="130" cy="755" r="16" fill="#333"/><circle cx="400" cy="755" r="16" fill="#333"/>
<line x1="55" y1="90" x2="55" y2="740" class="dim"/><text x="12" y="425" transform="rotate(-90 12 425)">1900 mm</text>
<line x1="90" y1="790" x2="440" y2="790" class="dim"/><text x="222" y="814">500 mm</text>
<text x="510" y="130" font-weight="bold">Plano de carga</text>
<text x="510" y="170">2 colunas × 5 níveis</text><text x="510" y="200">10 rolos × 1 kg = 10 kg</text>
<text x="510" y="230">Suportes calculados para 20 kg</text>
<text x="510" y="280">5 montantes 30×30×1,5</text>
<text x="510" y="310">10 travessas 25×25×1,5</text>
<text x="510" y="340">Base tubular + tampa PSAI</text>
<text x="510" y="370">4 rodízios freio 50 kg cada</text>
<text x="510" y="430" fill="#a53720">Rolo: largura axial ≤190 mm</text>
<text x="510" y="460" fill="#a53720">Confirmar protótipo e tombamento</text>
<text x="510" y="490" fill="#a53720">Usar anti-tombo em exposição</text>
</svg>'''
    SKETCH.write_text(svg, encoding='utf-8')


if __name__ == '__main__':
    project_id = create_quote()
    archive = export_template_reports(get_project_full_data(project_id), project_id, 'planilhas')
    write_sketch()
    totals = write_report(project_id, archive.parent)
    print(json.dumps({'project_id': project_id, 'archive': str(archive),
                      'report': str(REPORT), 'sketch': str(SKETCH),
                      'totals': totals}, ensure_ascii=False, indent=2))
