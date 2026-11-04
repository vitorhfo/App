"""Generate a reproducible project-by-project reading audit from the live DB."""

from pathlib import Path

from database import get_connection


ROOT=Path(__file__).resolve().parent
OUT=ROOT/'RELATORIO_AUDITORIA_2026-10-19.md'
METAL={'Tubo Quadrado/Retangular','Tubo Redondo','Arame','Chapa'}


def run():
    conn=get_connection()
    try:
        projects=[dict(row) for row in conn.execute('SELECT * FROM projects ORDER BY id')
                  if row['folder_path'] and not row['name'].startswith(
                      ('Teste de upload','Estrutura de teste'))]
        rows=[]
        total_items=total_missing=total_prices=total_pending=0
        for project in projects:
            items=[dict(item) for item in conn.execute(
                'SELECT * FROM materials WHERE project_id=?',(project['id'],))]
            missing=sum(item['item_type']=='materia_prima' and item['group_name'] in METAL
                        and not item['length'] for item in items)
            prices=sum(item['item_type']!='subconjunto' and item['unit_price'] is None
                       for item in items)
            pending=sum(bool(item['pending_issue']) for item in items)
            invalid=[]
            for item in items:
                source=item['source_page'] or ''
                if '#page=' not in source: continue
                rel=source.rsplit('#page=',1)[0]
                root=Path(project['folder_path']).resolve()
                pdf=(root/rel).resolve()
                if not pdf.is_relative_to(root) or not pdf.is_file(): invalid.append(item['id'])
            total_items+=len(items); total_missing+=missing
            total_prices+=prices; total_pending+=pending
            rows.append(f"| {project['id']} | {project['name'].replace('|','/')} | "
                        f'{len(items)} | {missing} | {prices} | {pending} | {len(invalid)} |')
        text='''# Auditoria das leituras salvas — 19/10/2026

Todas as pastas vinculadas aos cadastros foram verificadas desde 16/10/2026,
inclusive itens com alterações manuais e um cadastro de teste do usuário.
Este inventário mede o estado atual do SQLite; não transforma pendências em preço aprovado.

**Colunas:** *sem comprimento* conta matéria-prima (chapa, tubo e arame) cujo corte
continua sem comprimento confiável. A cota externa de um conjunto pode estar anotada
mesmo quando o corte desenvolvido não está informado. *Sem preço* exclui subconjuntos.

| ID | Projeto | Itens | MP sem comprimento | Sem preço | Itens pendentes | PDFs vinculados ausentes |
|---:|---|---:|---:|---:|---:|---:|
'''+ '\n'.join(rows)+f'''

**Total:** {len(projects)} cadastros com pasta de origem, {total_items} linhas, {total_missing} matérias-primas
sem comprimento confiável, {total_prices} itens sem preço e {total_pending} itens com pendência.
Vários cadastros apontam para a mesma pasta (RECKITT, DURACELL, OP01 e ALPA 2x5);
esses totais não representam projetos únicos nem itens distintos de produção.

## Leitura corrigida e conferida no PDF

- Quadros de corte com linhas diferentes agora geram peças separadas. A migração
  dividiu 13 linhas agregadas em 30 cortes, preservando quantidade, página e histórico.
- Em tabelas com comprimento `-`, o leitor continua após essa linha e mantém os
  cortes posteriores. Os quadros variáveis do MÓVEL PONTA aparecem completos na
  nova importação; o comprimento variável depende de escolher H2770 ou H2670.
- A leitura de chapas dobradas aceita uma única planificação cuja massa bruta
  calculada fique entre 100% e 110% da massa acabada do carimbo. Duas passadas
  preencheram 64 linhas de chapa com dimensões antes vazias. Pares concorrentes
  e massa incompatível continuam pendentes.
- Perfis de tubo redondo em polegadas, ferro chato/laminado fracionário e MDF
  foram revistos; MDF usa o peso do desenho até existir densidade aprovada.
- O OP01 recebeu três componentes da lateral em cada cópia salva, com quantidade
  2 pelos lados direito e esquerdo. VEJA recebeu três itens de embalagem presentes
  na página 6 e ausentes do cadastro. ALPA 5x5 recebeu os dois pés da BOM lateral.
- Os 12 painéis PSAI INF TESTEIRA nas três cópias RECKITT mostram 700×700×1 mm e
  `1x0` no PDF. A antiga cobrança como `0x0` foi retirada; impressão de uma cor
  aguarda tarifa aprovada. A área do carimbo excede a caixa externa e deve ser
  confirmada antes de escolher a base comercial.
- As três cópias RECKITT receberam a correção de 12 chapas: `FIX BATEDOR BASE`
  usa 130×20×3 mm, pois 50 mm no PDF é posição do furo, e `CH BARRA DE CARGA`
  usa 70×60×2 mm. A massa bruta foi recalculada e comparada ao carimbo.

## Pendências técnicas visíveis

- OP01 e CAN BASE trazem perfis, quadros e dobras com envelope externo; várias
  folhas não fornecem comprimento desenvolvido ou divisão em barras. A cota
  externa é mostrada na observação, sem transformá-la em corte inventado.
- ALPA 3x4 e 5x4 incluem páginas digitalizadas de leitura parcial; faltam cotas
  de peças físicas. A foto Hellmann's é uma hipótese de orçamento, sem PDF técnico.
- Alguns quadros MÓVEL PONTA oferecem duas variantes H2770/H2670. A BOM pai não
  escolhe uma delas; os cortes variáveis continuam pendentes.
- Há materiais e comprados sem tarifa validada, inclusive `1x0`, acessórios e
  itens de embalagem. Quantidades manuais divergentes do PDF permanecem
  identificáveis no histórico; não se deve sobrescrevê-las por reimportação cega.

## Preservação e teste

- Cada gravação no banco teve backup em `data/backups/` e registro em
  `material_changes`. `audit_migration_integrity.py` compara o backup inicial
  com o banco atual: nenhuma linha antiga apagada, nenhuma origem ou projeto
  alterado, nenhuma modificação sem histórico.
- Casos reais e negativos ficam em `test_cut_table_weight.py`,
  `test_drawing_details.py`, `test_saved_op01_lateral.py`,
  `test_saved_veja_packaging.py`, `test_saved_alpa_feet.py` e demais testes.
- Novos projetos devem ser verificados com os mesmos PDFs e com o mesmo modelo
  de planilha; uma suíte verde não confirma a geometria que o PDF não fornece.
'''
        OUT.write_text(text,encoding='utf-8')
        print(OUT)
    finally:
        conn.close()


if __name__=='__main__': run()
