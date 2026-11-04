# Prompt mestre — reconstruir o aplicativo de orçamentos com React

> **Versão substituída:** use [`PROMPT_RECRIACAO_IA_PRIMEIRO.md`](PROMPT_RECRIACAO_IA_PRIMEIRO.md) como especificação atual. Ele consolida o histórico até R63/P26 e muda a prioridade do produto para IA como motor principal de coleta. Este arquivo fica como referência do plano arquitetural anterior.

> Copie este documento como instrução principal para o agente que fará a reconstrução. Ele descreve o resultado esperado, os limites do projeto e os critérios de aceitação. Data da referência: **21/10/2026**.

## Papel e objetivo

Você é responsável por **reconstruir de ponta a ponta** o aplicativo local de orçamento de displays e peças para ponto de venda. Crie uma arquitetura mais clara, testável e segura, com **interface nova em React + TypeScript**. Mantenha as regras de negócio que já foram confirmadas. O resultado precisa ler os projetos reais da empresa, reconciliar PDF/script/IA/edições humanas, calcular quantidades, peso e custo e exportar os **dois modelos Excel originais** que a equipe usa.

O projeto existente é a fonte de comportamento, mas sua estrutura interna não precisa ser copiada. **Não faça apenas uma camada React sobre o `app.py` monolítico.** Separe domínio, leitura de documentos, aplicação, infraestrutura e interface. Faça a transição com migração verificável e sem perder projetos ou alterações manuais.

### Material obrigatório antes de codificar

Leia, nesta ordem:

1. `GUIA_RECONSTRUCAO.md` — visão completa das regras, exemplos, esquema atual e proposta de arquitetura.
2. `REGRESSOES.md` — R01–R57 e pendências; trate cada correção comprovada como contrato que não pode regredir.
3. `MAPA_FONTES.md` — planilhas e tarifas aprovadas, unidades e fórmulas.
4. `VALIDACAO.md` — divergências e limites observados em projetos reais.
5. `data/BRAHMA_CONFERENCIA_ORCAMENTO.md` — orçamento manual da mesma variante e diferenças ainda abertas.
6. Código atual: `app.py`, `reader_v3.py`, `score_package.py`, `database.py`, `pricing.py`, `mass_math.py`, `wire_allowance.py`, `ai_pdf_review.py`, `ai_review_queue.py`, `ai_apply_dimensions.py`, `quote_views.py`, `template_reports.py`, `fill_company_templates.ps1` e os testes relevantes.

Raiz atual: `C:\Users\Luis\Desktop\app\arquivos_raw\orcamento_app`. Os exemplos estão em `../`, `../../DADOS/` e, para BRAHMA, na pasta de rede indicada na auditoria. Use cópias de leitura e hashes nas fixtures; **nunca edite PDFs, planilhas originais, modelos vazios ou a pasta de rede para fazer os testes passarem**. Não inclua chave de API no código, nos prompts, em logs ou no repositório.

## Resultado que devo receber

- Um aplicativo funcional com **React + TypeScript** no frontend e API Python com módulos bem delimitados no backend. O backend pode continuar em FastAPI, mas a lógica de orçamento não pode ficar nas rotas.
- Migração dos projetos existentes e das edições manuais do SQLite, com backup, comparação antes/depois e rollback. Manter uma forma de executar o app antigo enquanto o novo não passar na validação.
- Todos os PDFs do projeto inventariados, inclusive páginas sem cotas ou sem item vinculado; vínculo navegável entre item e PDF/página/evidência.
- Árvore de conjuntos e peças físicas, com quantidade local, multiplicadores de cada pai, quantidade total e cortes separados.
- Medidas com **tipo e origem**: corte, planificação, cota externa, chapa comercial, posição de furo, dobra, seção de perfil e medida comercial. Uma cota não deve mudar de significado ao atravessar a API.
- Cálculo auditável de massa acabada, massa de consumo, peso de carimbo, área comercial, tarifa e custo. Valor desconhecido permanece pendente, nunca vira preço zero implícito.
- Revisão de IA automática de **todas as páginas** ao importar, com cache, fila persistente, limite de uso, fallback seguro e vínculo controlado às peças; três visões independentes: script, IA e conferido pelos dois.
- Interface React que permita conferir rapidamente projeto, fonte, peça, diferença, preço e pendência, editar sem apagar evidência e exportar as planilhas certas.
- Exportação fiel de `CÁLCULO+N. -1.xls` (somente `Total`, em cópias numeradas quando necessário) e `PLANILHA DE CUSTO -.xlsx` (duas abas, linhas ampliadas nas tabelas). **Não entregar markup preenchido automaticamente.**
- Testes automatizados e conferência de PDFs e planilhas reais da mesma variante. Documentar o que ficou pendente.

## Arquitetura exigida

Use um **monólito modular** inicialmente; não crie microserviços para resolver separação de código. A API serve a interface React e uma fila de tarefas persistente. Organize por responsabilidades, com dependências apontando para o domínio:

```text
frontend React/TypeScript
    ↓ API HTTP tipada
backend/api                 valida entrada, autorização local e resposta
backend/application         comandos, consultas, transações e casos de uso
backend/domain              peças, conjuntos, medidas, massa, preço, decisões
backend/document_reading    inventário, PDF, OCR, parsers por família
backend/reconciliation      evidências de script, IA e humano; conflitos
backend/infrastructure      SQLite/migrações, arquivos, Gemini, Excel, jobs
```

Os módulos de domínio devem ser **funções puras ou serviços determinísticos**, testáveis sem API, Excel, Google ou banco. O parser não calcula preço; a IA não modifica diretamente a BOM; a exportação não corrige a BOM. Cada alteração de estado passa por um caso de uso transacional que recalcula derivados, cria histórico e mantém proveniência.

### Persistência sugerida

Modele entidades explícitas para `project`, `project_revision`, `source_document`, `source_page`, `drawing`, `assembly`, `part`, `part_occurrence`, `cut`, `measurement`, `material_spec`, `price_reference`, `price_decision`, `ai_observation`, `human_override`, `pending_decision`, `calculation_snapshot` e `export_snapshot`. Os nomes podem mudar, desde que a semântica seja preservada.

Uma peça física tem ID estável independente de texto, dimensões ou ordem de importação. Duas peças 2359×159×0,7 mm podem ter IDs diferentes e continuar separadas. Conjunto e ocorrência não são sinônimos de peça: um conjunto pode aparecer várias vezes, multiplicando seus filhos. Mantenha quantidade local e quantidade efetiva separadas. Guarde em cada medida: valor, unidade, papel, método de obtenção, PDF/página, trecho/posição visual, revisão da fonte, confiança e decisão de uso.

Use migrações versionadas. O SQLite existente deve poder ser importado com backup; para uso local, SQLite pode continuar como banco inicial. Deixe o acesso a dados isolado para permitir outro banco no futuro. Não use número de item, descrição, caminho textual de pai ou geometria como chave única de peça.

### Contrato da API

Defina schemas tipados para projeto, fonte, árvore de produto, peça, corte, medida, revisão, conflito, preço, pendência e exportação. A API deve oferecer comandos diferentes para **importar proposta**, **comparar proposta com estado salvo**, **aplicar alterações aprovadas** e **reverter**. Preserve rotas antigas por adaptador ou forneça migração explícita da interface/dados; não quebre o app atual silenciosamente.

Operações mínimas: criar/listar projeto; importar pasta/PDF/ZIP/RAR; listar todos os PDFs/páginas; abrir fonte; ver árvore/BOM; editar peça, lado, cota, quantidade e material; ver histórico/impacto; resolver pendência; ver preços e sua fonte; ver fila IA; importar cotas elegíveis; comparar três visões; gerar prévia de completude e exportar.

## Motor de leitura e reconciliação

1. Faça inventário imutável de todos os documentos e respectivas páginas. Use hash de conteúdo para identificar revisão. Uma nova revisão não herda automaticamente uma inferência específica de uma versão antiga.
2. Detecte a **família e o tipo de página** antes de escolher parser: lista principal, desenho filho, quadro de cortes, carimbo, revisão, imagem digitalizada. Use adaptadores pequenos para CAD/ALPA, SolidWorks, DURACELL, CAN BASE/OUTPROMO, SCORE/AMBEV, tabelas parametrizadas e OCR; cada adaptador retorna observações com evidência, não grava diretamente `part`.
3. Construa relações pai/filho por código do desenho, nome, página e contexto. O número de item de um quadro de corte é local à folha. Quando lista e detalhe estiverem em páginas diferentes do mesmo PDF, complemente a mesma peça se a identidade for inequívoca.
4. Para tabelas de corte, crie uma linha por corte com perfil, bitola, comprimento e quantidade próprios. Peça soldada com chapa+tubo+ferro chato gera componentes físicos separados. Não deduplique só por dimensão.
5. Resolva variantes (`MEDIDA A`) com a lista do pai. Se a tabela só der A e COMPRIMENTO sem quantidade de projeto, guarde as alternativas fora da BOM/custo. Em arame, COMPRIMENTO é o corte; A e alturas são medidas de dobra.
6. Calcule quantidade efetiva pelo produto das quantidades dos ancestrais. Espelhamento D/E exige evidência; peças iguais podem ser consolidadas visualmente sem perder o vínculo e a parcela de cada lado.
7. Não use chapa comercial (`CHAPA DE AÇO 0,90 - 1200X2000`), envelope externo de peça dobrada, posição de furo, escala, revisão ou peso do conjunto como corte da peça. Se o desenvolvimento não estiver no desenho, mantenha pendência.
8. Reconcilie script, IA e edição humana **por campo**, com papel da medida e fonte. Concordância de duas leituras independentes aumenta confiança, mas não aprova material, quantidade ou preço que nenhuma delas comprovou. Conflito fica visível e não produz valor inventado.

## Motor físico e comercial obrigatório

Trabalhe internamente em mm, m², kg e R$. Use as densidades e fórmulas documentadas em `GUIA_RECONSTRUCAO.md` e `calc_engine.py`. Massa de chapa = `C×L×e×ρ/1.000.000`; arame = `π(d/2)²×C×ρ/1.000.000`; tubo retangular = `[a×b−(a−2e)(b−2e)]×C×ρ/1.000.000`; tubo redondo = área anular × comprimento × densidade. Valide espessuras fisicamente possíveis. Massa adotada para orçamento nunca fica abaixo da geometria bruta e da referência confiável do carimbo da peça; arredondamento e diferenças ficam explícitos.

Para arame, guarde `comprimento_acabado`, `folga_solda=20 mm`, `comprimento_consumido`, `massa_acabada` e `massa_consumida` por corte. Acrescente a folga uma única vez por peça; não por segmento de dobra. Para comparar com o peso do produto pronto, use massa acabada. Para custo do material, use consumo.

Preço por material:

- Chapa de aço carbono: referência aprovada atual **R$ 7,02/kg**.
- Arame BTC: **R$ 6,34/kg bruto × 0,7875**.
- Tubo: catálogo aprovado do mesmo perfil, seção e espessura exata ou próxima **maior** permitida; IPI **3,25%** e fator **0,7875**. Correspondência ambígua deixa preço pendente.
- PSAI: comprado, tabela CONTROLV por cor, espessura e área comercial; próxima espessura maior da mesma cor quando a regra existir; impressão por face. Área externa do desenho não substitui área faturável divergente do carimbo sem decisão.
- Porta preço/porta etiqueta: **R$ 6,80/m** com comprimento confiável; peça de arame com esse nome continua sob regra de arame.
- MDF, acrílico, PVC, PETG, ferragens, ventosas, embalagem e tinta: fonte própria aprovada. Sem tarifa, `NULL`/pendência, não R$ 0,00 por conveniência.

Exceção de amostra BRAHMA: fabricar/pesar tubo **50×30×1,06 mm**; usar apenas a tarifa por kg disponível do **50×30×2 mm** conforme confirmação do usuário. A tela e a planilha devem mostrar que bitola física e bitola da tarifa diferem. Não converter o peso para parede de 2 mm. Limite essa decisão à fonte/revisão confirmada; não aplique uma anotação manual de um cliente a todos os projetos.

Os custos MP e comprados são parciais até resolver preços e medidas. O produto só pode receber estado final quando peças, pesos, unidades, composições, divergências de peso e decisões necessárias estiverem completos. O usuário preenche o markup final; não gere uma terceira planilha.

## IA e operação econômica

Use um adaptador de provedor configurável. A configuração inicial pode migrar os três IDs de modelo usados hoje (`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` e `gemini-3.8-flash`), mas não espalhe IDs, cotas ou datas de reset pelo domínio. Cotas e disponibilidade do provedor variam. Leia **todas as páginas** ao importar, uma por job persistente; salve PDF/página/modelo/hash da fonte/hash do prompt/resultado/erro/tentativa.

Reutilize cache para a mesma versão do PDF e prompt compatível; evite reenviar página já validamente lida. Resposta 429 por minuto aguarda; 429 comprovadamente diário aciona o modelo reserva; 429 ambíguo aguarda. 5xx usa espera progressiva, sem bombardear as páginas seguintes do mesmo modelo. JSON inválido pode encaminhar **a página específica** ao reserva. Falha de rede (`URLError`) não deve ser interpretada como cota. Mostre cobertura, resultado, erro e próxima tentativa na interface. Não inclua chave ou resposta sensível do provedor em mensagens de erro.

A IA retorna observações estruturadas com `null` para campos desconhecidos, quantidade local/total/indefinida e tipo da cota. Ela pode completar **somente campo vazio** de peça física inequívoca com evidência numérica e geometria plausível; reusa o mesmo caso de uso de edição para recálculo e histórico. Nunca substitui alteração manual, quantidade total, tarifa, preço manual, área comercial ou um corte desenvolvido ausente. Uma peça nova sugerida pela IA fica fora do custo até confirmação de identidade e quantidade. O botão de importação deve reaplicar revisões salvas sem consumir uma chamada nova.

## Interface React obrigatória

Crie uma aplicação React + TypeScript com rotas e estado de servidor tipado. Separe componentes de apresentação, formulários, consultas e regras de domínio. Não recalcule preço/peso de forma diferente no navegador: a API é a autoridade; o frontend pode oferecer prévia derivada da mesma resposta. Defina tokens de design, layout responsivo, estados de carregamento/erro e acessibilidade de teclado. Use componentes reutilizáveis para evidência, status, peso, preço e conflito.

Telas e interações mínimas:

1. **Projetos:** busca por cliente/variante, status, completude, duplicatas da mesma origem e histórico de versões.
2. **Importação:** pasta/PDF/ZIP/RAR, árvore dos arquivos, todas as páginas, progresso do script e da IA, erros e PDFs sem item/cota.
3. **Revisão de PDF + BOM lado a lado:** árvore dos conjuntos, tabela de peças/cortes, quantidade local × pais = total, tipo de material, medidas e peso. Clicar num campo abre a página e destaca a evidência. Mostrar peças idênticas com IDs diferentes sem juntá-las.
4. **Peso:** massa bruta, carimbo da peça, massa adotada, massa acabada/consumo de arame, total do produto e diferenças por peça e por grupo.
5. **Custos:** MP/comprados separados, tarifa, unidade, fatores, origem, vigência, preço pendente e efeito de mudança de espessura.
6. **Pendências:** por impacto e causa, com link exato para PDF/página/peça; decisão humana gera histórico e pode ser revertida.
7. **Três visões:** script, IA e conferido pelos dois, com diferenças por campo. Não mostrar uma cota importada da IA como concordância independente.
8. **Fila IA:** páginas concluídas, pendentes e em retry, modelo usado, consumo/cobertura conhecida, erro e reanálise seletiva.
9. **Exportação:** prévia de quantas linhas/cópias serão geradas, itens sem preço/corte, vínculo da versão exportada e download apenas dos modelos originais.
10. **Regras/catálogo:** fonte, data, unidade, aprovação e histórico; não editar tarifa sem mostrar impacto.

Para edição manual, mostre **antes → depois → impacto em quantidade/peso/custo**, inclusive nos descendentes de subconjuntos. Diferencie cota medida no PDF, inferida pela IA, introduzida manualmente, preço aprovado e hipótese de foto com estilos e rótulos claros. Evite telas que exibem `0` quando o dado é desconhecido.

## Exportação e compatibilidade

Use os arquivos de `templates/spreadsheets/` como modelos **imutáveis**. Preencha apenas `Total` de cada `CÁLCULO+N. -1.xls`; se uma categoria exceder oito linhas, crie outra cópia numerada. Preserve as outras sete abas. No custo, mantenha as duas abas e expanda linhas dentro das tabelas. PSAI/acessórios em comprados, chapas/tubos/arames em MP, subconjuntos fora do custo. Itens sem preço permanecem vazios, e a exportação informa que o orçamento é preliminar.

No Windows, mantenha o preenchimento por Excel como adaptador isolado ou reproduza o resultado **com prova de equivalência**: mesmos nomes de abas, fórmulas, células, áreas de impressão, aparência e totais. Não altere o layout por conveniência técnica. Salve um snapshot da BOM e das regras usados no ZIP para auditoria. Não gere FATOR MARKUP preenchido.

## Validação que bloqueia a substituição do sistema antigo

Antes de considerar um módulo concluído, escreva teste que reproduz a falha conhecida e um caso próximo que não deve mudar. Rode a suíte completa antiga (`py -3 -m unittest discover -p 'test_*.py' -q`) enquanto migrar o comportamento e a nova suíte do frontend/backend. A linha de base em 21/10/2026 é **162 testes aprovados**. Depois compare a saída com o PDF e, quando houver, com orçamento histórico **da mesma variante**. Preço manual antigo é evidência, não regra geral.

Casos de aceitação obrigatórios, com expectativas detalhadas em `GUIA_RECONSTRUCAO.md` e `REGRESSOES.md`:

- ALPA com grade de 14 colunas, tubo vertical em páginas diferentes, arame 841 mm acabado/861 mm consumido e quadro de dois cortes 1286/323 mm.
- CAN BASE com `CHAPA DE AÇO 0,90 - 1200X2000`, cotas nas páginas filhas e perfis dobrados ainda sem corte desenvolvido.
- DURACELL com PDF filho compartilhado D/E, gaveta PSAI de área comercial divergente e dimensão variável A=80/150/230.
- FLEXVERO com tabela de arame `MEDIDA A` e cortes 400/550/595 mm sem quantidade inventada.
- RECKITT com múltiplas cópias da mesma origem, PSAI `1x0` sem tarifa aprovada e chapas planificadas.
- BRAHMA 37 páginas, lista contínua, pai × filhos, componentes soldados separados, duas peças de mesma medida mantidas distintas, tampa de aço separada do PSAI e tarifa 2 mm aplicada à massa física de 1,06 mm. **Não force as 21 diferenças ainda abertas a coincidir.**
- Foto Hellmann's como hipótese identificada, com comparação entre massa estimada e ~0,9 kg da imagem.

Para exportação, abra amostras geradas no Excel e confira quantidade de arquivos, abas, linhas, fórmulas, totais, erros de célula e impressão. Faça isso em projeto pequeno e grande. Compare o banco migrado com backups: nenhuma edição manual apagada, nenhuma outra cópia da mesma pasta esquecida e nenhum projeto alheio alterado.

## Plano de execução esperado

Execute incrementalmente, entregando código funcional e verificado ao fim de cada etapa:

1. **Inventário e contrato:** mapear API, dados, testes, PDFs/planilhas e decisões pendentes; criar fixtures com hash e matriz de aceitação. Registrar divergências reais sem resolvê-las por suposição.
2. **Domínio e banco:** modelo de peças/ocorrências/cortes/medidas/proveniência, cálculo puro, migrações e importação por proposta. Provar preservação de edição manual.
3. **Leitores:** portar cada família, com testes reais e vizinhos. Montar árvore e cortes antes de preço.
4. **API e React:** implementar fluxo completo, PDF + BOM lado a lado, edição auditada, peso, custo, pendências e três visões. Testar interações e acessibilidade.
5. **IA:** fila multipágina, cache, limites/fallback, vínculo e aplicação segura; testar falhas de cota, rede e respostas ambíguas sem usar quota real na suíte.
6. **Excel:** gerar apenas os dois modelos, validar por automação e inspeção de amostras reais.
7. **Migração e comparação:** rodar sistema antigo e novo sobre as mesmas variantes, comparar linha por linha, preservar backups e só trocar o atalho após os critérios de aceitação passarem.

Não pare após criar a estrutura ou a interface visual. O objetivo é um orçamento completo, auditável e exportável. Se uma regra comercial ou técnica realmente não estiver determinada pelas fontes, implemente a pendência visível e continue os demais trabalhos; documente a decisão necessária sem inventar um valor.

## Relatório final esperado do agente executor

Informe: arquitetura criada; telas React funcionais; dados migrados e backups; famílias de PDF verificadas; mudanças de regra e sua evidência; resultado dos testes; planilhas reais inspecionadas; divergências ainda abertas; instruções de execução; caminho dos artefatos. Para cada correção, atualize `REGRESSOES.md` com **sintoma, regra, arquivo real, estado e teste**, e `VALIDACAO.md` quando a comparação de projeto mudar.
