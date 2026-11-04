# Guia para reconstruir o aplicativo de orçamentos

**Estado verificado:** 21/10/2026. **Objetivo:** explicar o produto, as regras de negócio, a implementação atual, as fontes e os casos reais necessários para construir uma versão melhor sem repetir regressões. Este guia é uma fotografia do sistema atual; [REGRESSOES.md](REGRESSOES.md), [MAPA_FONTES.md](MAPA_FONTES.md) e [VALIDACAO.md](VALIDACAO.md) registram o detalhe e as mudanças posteriores.

## 1. O problema que o sistema resolve

A empresa orça displays e peças para ponto de venda a partir de pastas de projeto que podem conter vários PDFs técnicos, listas de materiais, desenhos filhos, tabelas de corte e, às vezes, apenas imagens. O resultado necessário é uma **lista de peças físicas com quantidades totais, medidas, massa e custo rastreáveis**, separando matéria-prima de material comprado. Subconjuntos explicam a montagem e multiplicam seus filhos, mas não são cobrados como uma peça adicional.

O orçamento precisa terminar nos **dois modelos de planilha usados pela empresa**:

1. `CÁLCULO+N. -1.xls`: preencher somente a aba `Total`. Quando uma cópia não comportar todos os cortes, criar cópias numeradas do mesmo modelo.
2. `PLANILHA DE CUSTO -.xlsx`: matéria-prima e comprados nas duas abas originais, ampliando linhas **dentro das tabelas**, sem redesenhar o layout.

O usuário preenche a planilha de markup separadamente; ela não entra no pacote final. Os arquivos técnicos e os modelos originais são **fontes de leitura**, nunca alvos de correções artificiais. Se não houver medida, quantidade ou tarifa confiável, o item fica pendente e o total é parcial.

### Princípios que não podem mudar

- Cada linha de quadro de corte é um corte distinto, mesmo quando pertence à mesma peça soldada; não juntar comprimentos diferentes ou dois materiais descritos na mesma célula.
- A quantidade total de cada peça é a quantidade local multiplicada pelas quantidades de todos os pais na árvore. Lados direito/esquerdo só são somados quando há prova de equivalência; uma edição em um lado não pode remover o outro.
- Peças fisicamente diferentes podem ter **as mesmas dimensões**. Medidas iguais não são uma chave de deduplicação.
- A medida da chapa comercial, a cota externa após dobra, a posição de um furo, o raio de canto e o comprimento desenvolvido de corte têm significados diferentes. A origem e o tipo da cota precisam acompanhar o número.
- O peso para consumo/custo deve ser igual ou maior que a massa geométrica bruta calculada e que o peso confiável do carimbo da peça. A divergência deve continuar visível. O carimbo do conjunto montado não deve ser copiado para cada componente.
- Arame ganha **20 mm por corte** para solda no consumo e custo; o peso da peça acabada usa o comprimento original do desenho.
- PSAI, MDF, acrílico, PVC, PETG e acessórios são comprados conforme sua função; chapa metálica, tubo e arame são matéria-prima. Um subconjunto não recebe custo próprio enquanto seus filhos são cobrados.
- Edição manual aprovada prevalece sobre novas leituras automáticas. A IA pode preencher somente campos vazios de peça inequivocamente vinculada, com evidência; não altera quantidade total, tarifa, preço manual ou área comercial sem regra aprovada.
- Foto é **estimativa**, com hipóteses explícitas e comparação com o peso informado na imagem; não equivale a um PDF técnico validado.

## 2. Onde estão as fontes e o código

Raiz do aplicativo: `C:\Users\Luis\Desktop\app\arquivos_raw\orcamento_app`. Pastas de exemplos técnicos: `C:\Users\Luis\Desktop\app\arquivos_raw` e `C:\Users\Luis\Desktop\app\DADOS`. Os PDFs de rede podem estar em caminhos UNC e devem ser copiados para uma área controlada antes de testes de regressão; não modificar o original.

| Parte | Implementação atual | Responsabilidade |
|---|---|---|
| Servidor e API | `app.py`, `config.py` | FastAPI local, rotas, edição, aprovação, importação e exportação. |
| Interface | `templates/index.html`, `static/js/main.js`, `static/js/quote_views.js`, `static/css/style.css` | Dez telas do fluxo e regras de preço. |
| Leitura de projeto | `reader_v3.py`, `pdf_engine.py`, `score_package.py` | Inventário de PDFs, listas, quadros, detalhes, hierarquia e famílias de sintaxe. |
| Quantidades e tipos | `assembly_quantities.py`, `side_quantities.py`, `item_types.py` | Multiplicação dos pais, lados D/E e classificação. |
| Cálculo e validação | `calc_engine.py`, `mass_math.py`, `wire_allowance.py`, `manual_validation.py`, `comparator.py` | Massa, áreas, solda, comparação com carimbo e alterações manuais. |
| Preços | `pricing.py`, `controlv.py`, `markup_engine.py` | Tabela de metal, CONTROLV, comprados e markup interno. |
| IA de PDFs | `ai_pdf_review.py`, `ai_review_queue.py`, `ai_apply_dimensions.py`, `ai_bulk_dimensions.py`, `ai_discovered_items.py`, `ai_coded_wire_import.py`, `wire_variants.py`, `quote_views.py` | Revisão página a página, cache, fila, vínculo, aplicação e três visões. |
| Persistência | `database.py`, `data/orcamento.db` | SQLite, regras, histórico de mudanças, pendências, variantes e fila. |
| Exportação | `template_reports.py`, `fill_company_templates.ps1`, `templates/spreadsheets/` | Cópia e preenchimento dos modelos originais pelo Microsoft Excel. |
| Evidência de produto | `REGRESSOES.md`, `MAPA_FONTES.md`, `VALIDACAO.md`, `data/BRAHMA_CONFERENCIA_ORCAMENTO.md` | Contratos, fontes, histórico e auditoria real. |

Dependências declaradas em `requirements.txt`: FastAPI, Uvicorn, `python-multipart`, PyMuPDF, openpyxl e ReportLab. A exportação fiel de `.xls` requer **Microsoft Excel no Windows**. O servidor usa `127.0.0.1:8080`; `run_app.bat` inicia o app e instala dependências em `.venv` quando necessário. `ORCAMENTO_DB_PATH` permite trocar o banco, especialmente nos testes.

## 3. Fluxo completo de dados

```text
Pasta / PDF / ZIP / RAR / foto
    → inventário de todos os arquivos e páginas
    → reconhecimento da família e da lista principal
    → árvore de conjuntos e peças, com quantidades por pai
    → associação de cada peça ao desenho filho e ao quadro de corte
    → dimensões tipadas + material + proveniência por campo
    → massa bruta, massa acabada, consumo, área e comparação com carimbo
    → tarifa aprovada + custo, ou pendência explícita
    → revisão IA de todas as páginas e comparação independente
    → edições humanas com histórico e recálculo
    → três visões: script / IA / campos concordantes
    → CÁLCULO(s) originais + PLANILHA DE CUSTO original
```

O cadastro de um projeto e a importação de sua pasta são ações separadas. A rota `POST /api/projects/{id}/import-folder` chama `process_complete_project`, grava a BOM e enfileira todas as páginas para IA em segundo plano. `GET /api/projects/{id}/pdfs` lista **inclusive PDFs sem cota ou sem item vinculado**, com caminho para abrir a origem. A versão nova deve continuar a aceitar pasta inteira, PDF individual, ZIP e RAR, limitando tamanho, quantidade de PDFs e caminhos relativos perigosos.

**Limitação concreta do sistema atual:** essa rota apaga e recria `materials`, `pending_decisions` e `wire_variants` do projeto antes de inserir a nova leitura. As migrações corretivas usadas até agora fazem backup e preservam alterações item por item, mas a reimportação geral não é uma mesclagem segura de edições manuais. Na reconstrução, trate importação como uma **proposta de revisão**, com diferença visual e aplicação por identidade estável de peça. Nunca substitua silenciosamente uma BOM já editada.

## 4. Modelo de dados e significado dos campos

O SQLite atual tem `projects`, `materials`, `price_rules`, `catalog_prices`, `pending_decisions`, `material_changes`, `budget_versions`, `ai_review_jobs`, `wire_variants`, `ai_discovered_items`, `markup_configs`, `box_configs` e `app_meta`. O esquema completo e suas migrações estão em `database.py`.

| Campo em `materials` | Significado obrigatório |
|---|---|
| `item_type` | `materia_prima`, `comprado` ou `subconjunto`; categoria física separada do grupo do material. |
| `group_name`, `material` | Família de cálculo/tarifa e especificação textual original: bitola, cor, tipo de tubo etc. |
| `quantity` | Quantidade **total** no projeto após multiplicação dos pais. O número local do PDF deve ser guardado separadamente na próxima versão. |
| `length`, `width`, `depth`, `thickness`, `radius_diam` | mm. Seu papel depende do material; uma cota externa não deve ocupar `length` de corte sem prova. |
| `drawing_length`, `wire_allowance_mm` | Comprimento acabado do arame e acréscimo por corte; `length` passa a ser o comprimento consumido. |
| `unit_weight`, `total_weight` | kg usados no consumo/custo; `finished_unit_weight` e `finished_total_weight` preservam a massa acabada do arame. |
| `unit_area`, `total_area` | m², com cuidado para não confundir envelope geométrico e área comercial CONTROLV. |
| `drawing_id`, `source_page`, `raw_code` | Identidade do desenho, PDF/página e código de matéria-prima ou peça. |
| `parent_assembly`, `mirrored_assembly`, `is_consolidated`, `is_inferred` | Caminho dos pais, segundo lado incluído, consolidação e inferência. Hoje os pais são texto; preferir chaves estrangeiras na reconstrução. |
| `unit_price`, `total_price`, `price_source` | R$, sempre com tarifa, unidade, fatores e espessura da referência explícitos. `NULL` significa desconhecido; zero só se um preço zero foi realmente aprovado. |
| `confidence`, `pending_issue`, `observation` | Grau de confiança, lacuna bloqueadora e notas de cálculo/evidência. Não ocultar a pendência depois de uma sugestão ambígua. |

Uma variante de arame com `MEDIDA A` fica em `wire_variants` com quantidade `NULL` até que a BOM escolha código e quantidade. Uma peça encontrada só pela IA fica em `ai_discovered_items`, fora do custo, até ser vinculada e ter quantidade total confirmada. `material_changes` grava o antes/depois das edições. Cada cópia salva da mesma pasta de origem precisa ser verificada separadamente antes de declarar uma correção concluída.

### Modelo recomendado para a nova versão

Separar `source_document`/`page`, `drawing`, `assembly`, `part`, `part_occurrence`, `cut`, `measurement`, `material_spec`, `price_reference`, `decision`, `human_override`, `ai_observation` e `export_snapshot`. Uma peça deve ter **identificador estável próprio**, e cada cota deve guardar valor, unidade, papel (`corte`, `planificação`, `externa`, `chapa_comercial`, `posição`, `dobra`), PDF/página, trecho ou caixa visual, método (`script`, `IA`, `humano`), revisão e status. Isso permite manter duas peças 2359×159×0,7 separadas e comparar leituras sem usar texto ou dimensões como identidade.

## 5. Como reconhecer os PDFs

Não existe uma única sintaxe da empresa. O leitor atual usa formatos específicos e um complemento por desenho. O novo leitor deve primeiro **identificar a família de página**, depois ler colunas e relações; uma regra de cliente não deve valer para todas as pastas.

| Família/caso real | O que reconhecer | Erro que deve ser evitado |
|---|---|---|
| Lista CAD ALPA de 14 colunas | `item, quantidade, descrição, grupo, material, espessura, raio/diâmetro, largura, profundidade, comprimento, desenho-id, peso, código(MP), observação`. | Deslocar campos por célula vazia; trocar raio por diâmetro; perder código e peso. |
| CAN BASE / OUTPROMO | `CHAPA DE AÇO 0,90 - 1200X2000` e variações de PVC/PSAI: material + espessura + formato comercial. As cotas de corte vêm do desenho filho. | Tratar 1200×2000 como o corte da peça; deixar os filhos sem cotas quando elas constam nas folhas. |
| DURACELL com dimensão `A` | O PDF filho tem `A` variável e largura/espessura fixas; a lista do pai diz `CH. ... - 80`, `- 150`, `- 230`, com quantidades 2/4/5. | Aplicar uma única variante a todos; preencher `A` com dimensão de dobra. |
| Quadro `Nº DO ITEM / MATERIAL / COMPRIMENTO / QTD.` | Criar uma linha por linha/corte, com perfil, ângulos quando relevantes, quantidade e origem. | Juntar os cortes 1286 e 323 mm ou perder a segunda linha. |
| FLEXVERO, arame parametrizado | `CÓDIGO / NOMINAL / MEDIDA A / COMPRIMENTO`: `A` é a medida dobrada, `COMPRIMENTO` é o corte; 400/550/595 mm são variantes. | Cobrar as três variantes com quantidade inventada; usar A como corte. |
| SCORE/AMBEV BRAHMA | PDF de 37 páginas, lista contínua nas páginas 36–37, conjuntos e quadros em páginas anteriores. Peças soldadas podem conter chapa, tubo e ferro chato separados. | Ler só a primeira folha, cobrar o pai, perder parte da lista, juntar materiais ou copiar peso do conjunto aos componentes. |
| RECKITT e chapas dobradas | Folhas filhas com planificação, recortes e peso; comparar candidatos de dimensões com massa. | Usar envelope externo ou distância de furo como largura; aceitar cota que não bate com massa. |
| ALPA/José Vitor digitalizados | OCR como leitura preliminar da lista, mantendo origem e baixa confiança. | Transformar OCR incerto em cota ou quantidade aprovada. |
| Foto Hellmann's | Estimativa explícita das sete chapas 0,75, contorno em arame Ø4, ventosas e logo; registrar divergência com ~0,9 kg da imagem. | Generalizar a construção específica para qualquer foto. |

Para cada PDF: guardar todas as páginas; localizar lista principal, detalhes, carimbo, tabela de cortes e revisões; relacionar peça do pai ao filho por código/desenho/descrição e família de material. Um número de item num quadro de detalhe é **local**, não uma identidade global. Um mesmo PDF pode trazer a lista numa página e o detalhe em outra. Se duas folhas candidatas forem equivalentes ou conflitantes, abrir pendência em vez de escolher pela primeira sem evidência.

## 6. Quantidades, peças soldadas e lados

Para um caminho `produto → conjunto A (q=2) → conjunto B (q=3) → corte (q=4)`, a quantidade no orçamento é `2 × 3 × 4 = 24`. O custo do conjunto A e de B não é somado novamente. Alterar a quantidade de A deve atualizar seus descendentes; peças do outro lado que não pertencem a A permanecem. Duas linhas de cortes iguais só podem ser consolidadas quando identidade física, contexto de montagem, material, geometria, preço e evidência de espelhamento forem equivalentes.

Uma peça soldada ou composta pode exigir **vários materiais de estoque**. A vista `Chapa 1,5 + ferro chato 2×20` do BRAHMA gerou chapa 748×400×1,5 e ferro chato 394×20×2. Os reforços BRAHMA são tubo mais duas chapas cada, repetidos quatro vezes pela prateleira pai. A ficha de cada componente precisa distinguir quantidade local, multiplicador dos pais e quantidade total. Um par de chapas 2359×159×0,7 que fecha lados da estrutura e outro par do mesmo tamanho são **quatro peças distintas**, por confirmação do usuário. A tampa de aço 1250×520×3 da testeira é distinta do fechamento PSAI comprado com dimensões semelhantes.

## 7. Medidas, áreas e pesos

Unidades do motor: dimensões em mm; área em m²; massa em kg; preço em R$. Densidades atuais em g/cm³: aço carbono `7,85`, inox `7,90`, alumínio `2,70`, PSAI `1,05`, acrílico `1,19`, PETG `1,27`, polionda `0,45`. MDF não recebe densidade de aço: usar o carimbo ou uma densidade própria aprovada.

```text
chapa:                 C × L × e × ρ / 1.000.000
arame:                 π × (d/2)² × comprimento × ρ / 1.000.000
tubo retangular:       [a×b − (a−2e)×(b−2e)] × comprimento × ρ / 1.000.000
tubo redondo:          π × [(d/2)² − (d/2−e)²] × comprimento × ρ / 1.000.000
área retangular:       C × L / 1.000.000
quantidade total:      quantidade local × produto dos multiplicadores dos pais
peso adotado por peça: máximo(massa bruta geométrica, carimbo da peça, peso manual válido)
```

O fator `/1.000.000` converte mm³ com densidade em g/cm³ para kg. O motor arredonda massa adotada **para cima** a seis casas decimais. Um desenho pode conter furos, pintura, dobras, perfis ou peso do conjunto; por isso uma diferença de massa é sinal para revisão da geometria e do significado do carimbo, não prova automática de que a cota escolhida está certa. `comparator.py` compara peso **acabado do produto** com o carimbo do conjunto, peso de metal com histórico de metal, e mostra `INCOMPLETO` enquanto houver peça sem peso. A tolerância padrão do projeto é 5%, configurável.

No arame, `drawing_length` é o corte acabado; consumo = `drawing_length + 20 mm` **uma vez por peça/corte**. `finished_unit_weight` não inclui a folga; `unit_weight` do estoque inclui. Dobra em U com várias cotas parciais exige comprimento desenvolvido do U; não adicionar 20 mm em cada segmento geométrico. Uma única peça de arame pode, em casos controlados, ter comprimento estimado a partir de peso e diâmetro; grade/montagem não pode usar essa inferência como se fosse um único fio.

## 8. Tarifa e custo

As fontes estão detalhadas em [MAPA_FONTES.md](MAPA_FONTES.md). Uma tarifa histórica digitada em orçamento antigo não vira regra universal. O preço deve carregar `fonte, data, unidade, perfil/cor/espessura escolhidos, fatores e aprovação`.

| Categoria | Regra hoje cadastrada |
|---|---|
| Chapa de aço carbono | Modelo vazio vigente: **R$ 7,02/kg**. Não aplicar automaticamente ao ferro chato. |
| Arame BTC | **R$ 6,34/kg bruto × 0,7875**, usando massa de consumo com a folga de 20 mm. |
| Tubo | Tarifa em R$/kg do catálogo aprovado para o mesmo perfil e bitola exata ou a **próxima maior disponível**, com **IPI 3,25% × fator 0,7875**. Correspondência ambígua/ausente fica pendente. |
| PSAI | Material comprado pela tabela CONTROLV: área faturável × (tarifa da mesma cor/espessura ou próxima espessura maior + impressão por face). Colorido usa base branca com +10% onde a regra aprovada se aplica. Impressão `4x0` e `4x4` têm R$ 25/m² por face; `4x1` não tem tarifa aprovada. |
| Porta preço/porta etiqueta | Mesmo comprado, **R$ 6,80/m**, desde que exista comprimento confiável; uma peça de arame com esse nome segue arame. |
| MDF, acrílico, PVC, ferragens, embalagem e outros | Usar fonte aprovada específica. Sem tarifa ou área comercial confiável, manter `unit_price=NULL` e pendência. |

Exceção confirmada na variante BRAHMA: o tubo retangular **50×30×1,06 mm** é fabricado e pesado como **1,06 mm**, mas usa a **tarifa por kg do perfil 50×30×2 mm** por ser a menor opção disponível no catálogo, conforme decisão do usuário. A origem do preço deve exibir as duas bitolas; não aumentar a massa física para 2 mm. Essa confirmação não valida o orçamento manual antigo, que digitou geometria de 2 mm.

O aplicativo calcula custo conhecido de MP e comprados separadamente. O markup interno usa duas bases: `preço_MP = custo_MP / [1 − (MO + despesas + impostos + margem_MP)/100]` e `preço_MC = custo_MC / [1 − (despesas + impostos + margem_MC)/100]`. Esse cálculo ajuda a conferir, mas o fluxo contratado exporta **somente CÁLCULO e CUSTO**; os percentuais finais de venda são preenchidos pelo usuário na planilha de markup. Um custo parcial não pode aparecer como preço final.

## 9. IA: segunda leitura, vínculo e economia de cota

O leitor por script e a IA precisam trabalhar em conjunto, mas suas observações devem continuar independentes para que uma cota copiada da IA não conte como confirmação de si mesma. As três telas são: **Orçamento do Script**, **Orçamento da IA** e **Conferido pelos Dois**. A terceira mostra só campos com mesmo item físico, mesmo papel da medida e valores compatíveis. Concordância parcial não valida a peça toda ou seu custo.

A implementação atual envia cada página PDF isoladamente à Gemini, pede JSON estruturado com descrição, material, tipo, medidas, escopo da quantidade (`project_total`, `local_table`, `unknown`), papel da medida e evidência. Um item sem valor confiável retorna `null` mais aviso. A resposta é normalizada e salva em `data/ai_reviews/` com caminho, página, modelo, tamanho/data do PDF e hash de prompt. Revisões válidas são reaproveitadas entre cópias da mesma pasta; reanálise forçada pode renovar a leitura. A chave vem de `GEMINI_API_KEY` ou de `data/private/google_api_key.txt`; **nunca colocar chave no código ou neste documento**.

Modelos configurados em 21/10/2026: `gemini-3.5-flash-lite` para todas as páginas; `gemini-3.1-flash-lite` como reserva; `gemini-3.8-flash` para revisão seletiva. Esses nomes e limites são dependentes da conta/provedor e devem ser configuráveis na nova versão, sem prometer custo zero permanente. A fila `ai_review_jobs` persiste por PDF/página/modelo, processa sequencialmente, espera em 429 por minuto e 5xx, transfere páginas não concluídas ao reserva se 429 identificar cota **diária**, e encaminha ao reserva apenas a página que retornou JSON inválido. `URLError` é falha de conexão e não prova esgotamento de cota. Cache e prompts compactos reduzem chamadas; não reduzir a resolução técnica a ponto de apagar cotas pequenas.

**Aplicação automática:** preencher só campos dimensionais vazios de uma peça física com identidade inequívoca e número visível na evidência; mesmo PDF/página ou associação complementar segura entre páginas. Histórico de alteração manual bloqueia sobrescrita. Chapa dobrada requer verificação de massa e base `corte/planificação`; envelope externo não é corte. A IA não muda quantidades, preço, composição, área CONTROLV ou item manual. Antes de cada lote que altera materiais salvos, criar backup SQLite e registrar `material_changes`. O botão **Importar cotas e peças encontradas pela IA** reaplica resultados salvos sem nova chamada. Peças só da IA permanecem candidatas até vínculo e quantidade.

## 10. Edição, aprovação e exportação

A interface atual oferece Projetos, Importação & Desenhos, BOM, Peso, Custos/Markup, Pendências, três visões de orçamento, Orçamento Final e Regras/Preços. A edição de medida, bitola ou peso passa por sincronização do perfil, cálculo geométrico, comparação com o PDF, atualização de preço pela tarifa aprovada e histórico antes/depois. Uma edição não pode reduzir o peso abaixo do maior mínimo comprovado. Projeto com preço, medida, unidade, composição ou decisão pendente continua `PRELIMINAR`.

`template_reports.py` divide os itens físicos em arame, chapa, tubo retangular/quadrado, tubo redondo, pintura e comprado. Cada CÁLCULO original comporta oito linhas por seção; uma nona cria outra cópia numerada, mantendo as outras sete abas idênticas ao modelo. `fill_company_templates.ps1` usa Excel para preencher os arquivos copiados. A planilha de custo cresce dentro das duas tabelas originais; preços ausentes ficam em branco, e PSAI entra em comprados. A exportação deve verificar fórmulas, totais, área de impressão e erros de célula; passar na suíte Python não basta.

Rotas essenciais atuais: `GET/POST /api/projects`, `POST /api/projects/{id}/import-folder`, uploads, `GET/POST/PUT/DELETE` de materiais, `GET /api/projects/{id}/pdfs`, `GET /api/projects/{id}/ai-review-jobs`, `GET/POST /api/projects/{id}/ai-pending-dimensions`, `GET /api/projects/{id}/quote-views`, revisão por página/PDF, catálogo/regras, versões e `GET /api/projects/{id}/export/modelos/{kind}`. O código de `app.py` é a definição exata dos campos e erros das rotas atuais.

## 11. Exemplos reais que precisam virar testes de aceitação

| Amostra | Resultado mínimo exigido |
|---|---|
| `PSAI LAT. Display Balcão DURACELL.PDF` | Filho certo para direita e esquerda; 250×150×1 mm por peça; área do carimbo diferente do envelope permanece anotada. |
| `CH. Display Balcão DURACELL.PDF` + lista pai | Variantes A=80/150/230 mm com quantidades 2/4/5; largura 15 mm e espessura 0,90 mm; sem preencher variante errada. |
| `PSAI GAVETA Display Balcão DURACELL.PDF` | Separar planificação 281,2×246,2×1 mm, base/dobras e área comercial maior; não declarar área validada por peso apenas. |
| ALPA BASICO 2X5, páginas 7 e 10 | `TUBO VERTICAL FUNDO` 1630×25×25×0,9 mm vinculado entre páginas; quantidade local do detalhe não substitui total 2. |
| ALPA `ARAME GANCHO`, páginas 12 e 14 | Corte acabado 841 mm Ø6; consumo 861 mm; total 10; peso acabado comparado com a IA. |
| Quadro de dois tubos 50×30 | Cortes 1286 e 323 mm separados, com quantidades próprias, mesmo se repetidos em outro conjunto. |
| FLEXVERO `APARADOR Grade Prateleira.PDF` | Variantes código/A/corte 400/550/595 mm, Ø5; quantidade nula até seleção; A e altura da dobra não viram corte. |
| CAN BASE Módulo D | Ler cotas das folhas filhas; `CHAPA DE AÇO 0,90 - 1200X2000` informa estoque, não dimensão de peça. |
| BRAHMA ILHA, PDF de 37 páginas e orçamento manual | Ler lista contínua 36–37, multiplicar filhos, separar composições e pares de mesma medida; tubo 50×30 pesa 1,06 mm e usa tarifa 2 mm; manter diferenças abertas. [Auditoria detalhada](data/BRAHMA_CONFERENCIA_ORCAMENTO.md). |
| Hellmann's por foto | Marcar todas as sete chapas e contorno como hipótese; massa estimada e ~0,9 kg da imagem devem aparecer em confronto. |

Executar também o **caso vizinho** de outra família ou material em cada teste. Exemplos: ler SCORE sem alterar SolidWorks TROPERO; corrigir um PSAI sem reclassificar chapa de aço; separar um quadro de dois cortes sem duplicar uma linha única. Existem **162 testes aprovados** no estado verificado em 21/10/2026, mas exemplos reais e Excel gerado continuam sendo critério de aceitação.

## 12. Pendências e limites atuais

O registro completo está em [REGRESSOES.md](REGRESSOES.md), seção `Pendências conhecidas`, e as diferenças por projeto em [VALIDACAO.md](VALIDACAO.md). Pontos importantes para a nova construção:

- Perfis U, tubos e arames dobrados frequentemente têm apenas envelope externo, sem desenvolvimento; não gerar corte e custo fictícios.
- PSAI `1x0`, impressão/cores e área comercial divergente do envelope precisam de regra comercial aprovada. Comprados, embalagem e ferragens podem faltar ou estar sem tarifa.
- Alguns projetos são digitalizados; OCR não garante cotas. A revisão IA também pode errar material, raio, quantidade e cortes, e depende de rede/cota do provedor.
- A planilha de custo manual BRAHMA e o PDF ainda divergem em **21 chaves de corte/quantidade**; há **18 peças sem preço**. O projeto #93 contém 74 linhas, 63 peças físicas e custo conhecido parcial R$ 1.187,84. Esses números não são preço final. A escolha sobre quantidades manuais menores de prateleira/laterais ainda precisa de decisão.
- O peso de consumo pode exceder o peso montado do carimbo por sobras e critério de máximo por peça. Comparar os dois sem separar base e itens faltantes gera falsa conclusão.
- Um novo parser não deve remover correções antigas. O `REGRESSOES.md` documenta R01–R57 com PDF real, regra, estado e teste; usar esse acervo como contrato de migração.

## 13. Projeto técnico recomendado para uma versão melhor

1. **Inventário imutável e versionado:** guardar hash de cada PDF, páginas, OCR/texto, imagens de referência e planilhas recebidas. Nenhuma reimportação sobrescreve original ou edição humana.
2. **Parsers por família:** detector de formato com regras pequenas para CAD, SolidWorks, SCORE, tabelas parametrizadas e OCR; cada saída gera observações com proveniência, nunca escreve diretamente na BOM final.
3. **Grafo de produto normalizado:** conjuntos, peças, ocorrências e cortes com IDs estáveis e multiplicadores explícitos. Duas ocorrências idênticas continuam separadas até consolidação justificada.
4. **Motor único e determinístico:** fórmulas, unidades, arredondamento, peso acabado/consumo, fatores de preço e fonte da tarifa numa biblioteca isolada da API e da IA.
5. **Reconciliação de evidências:** script, IA e humano produzem candidatos por campo. Um resolvedor checa identidade, papel da medida, material, peso e conflito. Toda aplicação é revisável e reversível, com antes/depois e razão.
6. **Importação por diferença:** mostrar `adicionar / atualizar / manter manual / conflito / remover proposto`; aplicar em transação após backup. Conferir todas as cópias da mesma origem.
7. **Preços versionados:** catálogo com vigência, unidade, material, seção, espessura, aprovação e conversões explícitas. Ausência permanece `NULL` e bloqueia finalização.
8. **Fila IA com orçamento de uso:** todas as páginas, cache por hash, limites por modelo, retries por causa, fallback só quando adequado e painel de cobertura. Modelo/limites configuráveis, sem espalhar IDs pelo código.
9. **Exportador validado:** adaptar os dois modelos originais em cópias, conferir com Excel número de abas, células, fórmulas, impressões, linhas e totais. Guardar snapshot da versão exportada.
10. **Qualidade contínua:** cada bug novo inclui amostra real, teste que falha antes, caso vizinho, atualização do registro e verificação da planilha. Usar fixture reduzida e redigida quando o PDF for sigiloso; guardar hashes para provar a versão da amostra.

### Sequência prática de reconstrução

**Fase 1 — dados e contratos:** congelar amostras e modelos, desenhar esquema com proveniência/IDs estáveis, importar catálogo e escrever testes de aceitação das famílias acima. **Fase 2 — motor:** hierarquia, dimensões, massa, preço e pendências sem IA. **Fase 3 — leitores:** PDFs por família, OCR e vínculo pai/filho. **Fase 4 — IA:** fila, comparação independente e aplicação controlada. **Fase 5 — interface e exportação:** revisão por peça, três visões e modelos Excel. **Fase 6 — migração:** comparar a nova saída com cada projeto salvo e orçamento da mesma variante, preservando edições, backups e diferenças sem solução.

## 14. Como verificar o estado atual

```powershell
cd C:\Users\Luis\Desktop\app\arquivos_raw\orcamento_app
py -3 -m unittest discover -p 'test_*.py' -q
run_app.bat
```

Na última conferência, a suíte terminou com **162 testes aprovados**. Para mudança de parser, comparar PDF real, script e planilha manual da **mesma variante**. Para mudança de exportação, abrir os arquivos gerados no Excel e verificar layout, abas, fórmulas, quantidade de linhas, totais e impressão. Antes de migrar um projeto salvo, criar backup do SQLite, conferir todas as cópias com a mesma `folder_path` e provar que as demais peças permaneceram iguais.

**Arquivos de partida:** [README.md](README.md) para operação, [MAPA_FONTES.md](MAPA_FONTES.md) para fórmulas/fontes, [REGRESSOES.md](REGRESSOES.md) para contratos, [VALIDACAO.md](VALIDACAO.md) para diferenças reais, [BRAHMA_CONFERENCIA_ORCAMENTO.md](data/BRAHMA_CONFERENCIA_ORCAMENTO.md) para a última auditoria peça a peça.
