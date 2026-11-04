# Auditoria das leituras salvas — 16/10/2026

Todas as pastas reais cadastradas foram verificadas, inclusive itens com alterações manuais.
Este inventário mede o estado atual do SQLite; não transforma pendências em preço aprovado.

**Colunas:** *sem comprimento* conta matéria-prima (chapa, tubo e arame) cujo corte
continua sem comprimento confiável. A cota externa de um conjunto pode estar anotada
mesmo quando o corte desenvolvido não está informado. *Sem preço* exclui subconjuntos.

| ID | Projeto | Itens | MP sem comprimento | Sem preço | Itens pendentes | PDFs vinculados ausentes |
|---:|---|---:|---:|---:|---:|---:|
| 1 | PA00000250 - DISPLAY DE CHC_ODE AC_O VEJA (leitura real) | 44 | 0 | 3 | 4 | 0 |
| 2 | ILHA CASH RECKITT (leitura real) | 79 | 0 | 45 | 21 | 0 |
| 3 | PG - OP01 - PONTA DE GÔNDOLA - MODULO A (1 2 pallet) (leitura real) | 36 | 19 | 28 | 36 | 0 |
| 4 | ALPA BASICO 2X5 | 21 | 0 | 0 | 5 | 0 |
| 5 | ALPA BASICO 3X4 | 13 | 2 | 8 | 13 | 0 |
| 7 | ALPA BASICO 5X4 | 14 | 2 | 10 | 14 | 0 |
| 8 | ALPA BASICO 2X5 | 22 | 0 | 3 | 5 | 0 |
| 9 | Display Balcão DURACELL | 14 | 0 | 0 | 2 | 0 |
| 10 | ILHA RECKIT | 202 | 4 | 78 | 70 | 0 |
| 11 | DISPLAY BALCÃO TROPERO ALIMENTOS | 52 | 2 | 0 | 15 | 0 |
| 12 | Display Balcão DURACELL | 14 | 0 | 0 | 1 | 0 |
| 14 | ALPA BASICO 5x5 | 33 | 0 | 3 | 11 | 0 |
| 15 | DISPLAY DE CHAO TAMBASA | 26 | 0 | 7 | 12 | 0 |
| 16 | MOVEL PONTA ATACADÃO | 135 | 6 | 5 | 21 | 0 |
| 17 | ILHA FOR WAY | 42 | 1 | 6 | 8 | 0 |
| 18 | DISPLAY DE CHÃO JUNGLE | 22 | 1 | 5 | 8 | 0 |
| 19 | ILHA CASH RECKITT | 202 | 4 | 51 | 65 | 0 |
| 20 | PONTA DE GÔNDOLA - MODULO A | 36 | 19 | 28 | 36 | 0 |
| 21 | CAN BASE - MODULO D | 28 | 12 | 14 | 28 | 0 |
| 28 | DISPLAY DE CHÃO SOFT - BB - GILLETTE | 1 | 0 | 0 | 1 | 0 |
| 29 | DISPLAY RACK SUPER GIGANTE FINI | 1 | 0 | 0 | 1 | 0 |
| 30 | DISPLAY DUPLA FACE 2021 | 22 | 0 | 16 | 19 | 0 |
| 31 | DISPLAY DE SACHÊS HELLMANN’S — 3 COMPARTIMENTOS COM VENTOSAS | 14 | 0 | 0 | 14 | 0 |
| 62 | CARMED | 8 | 0 | 4 | 7 | 0 |
| 63 | TESTE | 2 | 0 | 2 | 2 | 0 |

**Total:** 25 cadastros reais, 1083 linhas, 72 matérias-primas
sem comprimento confiável, 316 itens sem preço e 419 itens com pendência.
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
