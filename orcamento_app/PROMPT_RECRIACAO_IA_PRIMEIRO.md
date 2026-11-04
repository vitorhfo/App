# Prompt mestre: recriar o app de orçamento com IA como motor de leitura

**Versão consolidada em 27/10/2026.** Este documento serve para reconstruir o aplicativo com arquitetura melhor, mantendo as regras aprendidas nos projetos reais. A nova versão deve usar **React + TypeScript** na interface e dar à IA o papel principal na coleta e interpretação dos documentos. Cálculos, preços, decisões de vínculo e exportação permanecem auditáveis e determinísticos.

> Este texto incorpora o histórico conhecido até a regressão R63 e as pendências P01–P26 registradas em 23/10/2026. Se algum resumo divergir do registro detalhado, consulte `REGRESSOES.md`, `MAPA_FONTES.md`, `VALIDACAO.md` e os relatórios de projeto indicados. Não converta preço histórico ou hipótese de imagem em regra geral.

## Instrução para quem vai reconstruir

Reconstrua o sistema como produto funcional, não apenas como uma tela nova. A IA lê automaticamente todas as páginas e coleta dados dos PDFs; leitor local determinístico pode apoiar a leitura e verificar resultados, mas não é o caminho principal de coleta. Preserve cálculos, hierarquia, decisões humanas, evidências, preços aprovados e os dois modelos oficiais de Excel.

Antes de implementar, leia `GUIA_RECONSTRUCAO.md`, `REGRESSOES.md`, `MAPA_FONTES.md`, `VALIDACAO.md`, `data/BRAHMA_CONFERENCIA_ORCAMENTO.md` e `data/BUD_BRAHMA_PADROES.md`. Leia relatórios REHAU em `data/` quando trabalhar com estimativa por foto. Use PDFs, planilhas e pastas de rede como fontes somente de leitura. Não altere originais para fazer uma saída parecer correta. Não inclua chaves de API em código, arquivos versionados, logs ou respostas da interface.

Implemente por etapas dentro do mesmo produto e mantenha divergências abertas visíveis. Não marque uma leitura como correta só porque o JSON é válido, o teste passa ou a IA demonstra confiança. Use evidência da página, identidade da peça, cálculo físico, histórico da mesma variante e revisão humana.

## 1. Objetivo e resultado do orçamento

O aplicativo recebe uma pasta de projeto, PDFs, ZIP/RAR ou, em casos de estimativa, uma foto. Ele produz lista auditável de **peças físicas** para fabricar/comprar, calcula quantidades totais pela estrutura de montagem, identifica dimensões e materiais, calcula peso e custo e exporta os dois arquivos adotados pela empresa:

1. `CÁLCULO+N. -1.xls`: preencher somente a aba `Total`; manter as demais abas e layout original. Se não comportar os itens, gerar cópia numerada do mesmo modelo.
2. `PLANILHA DE CUSTO -.xlsx`: separar matéria-prima e comprados nas duas abas existentes; aumentar as linhas dentro das tabelas, sem redesenhar o arquivo.

O usuário preenche a planilha de markup. Não gerar terceira planilha nem preencher markup automaticamente. Um orçamento sem cota, quantidade, composição ou tarifa confirmada permanece parcial e explica o que falta.

### Prioridade das fontes

1. **Edição humana confirmada** é a decisão vigente e nunca pode ser sobrescrita por leitura automática.
2. **IA com evidência visual/textual ligada à peça** é o coletor principal. Pode completar campos vazios quando identidade e significado da cota são inequívocos.
3. **Concordância independente IA + leitor local** aumenta a confiança daquele campo. Uma cota copiada da IA para o cadastro não conta depois como segunda confirmação.
4. **Leitor/script local** auxilia com tabelas, códigos, texto vetorial, aritmética e verificação. Divergências dele com a IA ficam visíveis por campo; ele não descarta silenciosamente a observação visual.
5. Inferência por nome, proximidade, escala, foto ou variante é hipótese. Deve ficar marcada como hipótese e não virar dado confirmado.

A IA coleta observações; regras determinísticas resolvem quantidades, massa e custo. Campos desconhecidos ficam `NULL`/pendentes, nunca zero.

## 2. Fluxo funcional

```text
Criar projeto
  → importar pasta, PDF, ZIP/RAR ou foto
  → inventariar todos os documentos, PDFs e páginas
  → enfileirar automaticamente todas as páginas para IA
  → IA classifica e extrai listas, desenhos, cortes, carimbos e revisões
  → relacionar pai/filho e item/página/desenho em todo o projeto
  → comparar observações por campo com leitura local e histórico
  → completar campos vazios de peças físicas inequívocas
  → apresentar ambiguidades e peças novas para revisão/quantidade
  → multiplicar quantidades da árvore e calcular massa/área
  → consultar preços aprovados ou marcar pendência
  → revisar divergências e edições humanas com histórico
  → exportar os dois modelos originais e uma memória auditável
```

A revisão automática da IA começa junto à importação/geração do projeto. O usuário não precisa abrir cada PDF e pedir leitura. A fila sobrevive ao fechamento/reinício, mostra progresso e retoma sem duplicar chamadas concluídas.

## 3. Motor de IA para PDFs

### 3.1 Inventário e extração

- Aceitar pasta completa, PDF, ZIP e RAR. Proteger contra caminhos relativos perigosos, arquivos repetidos e limites configuráveis.
- Inventariar todos os PDFs, páginas, imagens, planilhas de referência e documentos relevantes. PDF sem item vinculado ou sem cota continua visível e abrível.
- Guardar hash do arquivo, número da página, revisão, data, caminho relativo e resultado de cada tentativa.
- Enviar todas as páginas automaticamente, inclusive capa, listas, revisões e páginas inicialmente sem cotas. Não parar na página 1.
- Usar extração local de texto/vetores e OCR como contexto auxiliar e alternativa operacional; interpretação visual estruturada continua sendo feita pela IA.
- A IA identifica tipo da página: lista geral, lista filha, desenho de peça, quadro de corte, carimbo, revisão, detalhe, montagem ou imagem digitalizada. Uma página pode ter mais de uma grade/tabela.
- Uma segunda etapa relaciona JSONs já extraídos do projeto inteiro sem reenviar todos os PDFs ao modelo; cada vínculo indica evidência.

### 3.2 Dados que a IA coleta

Para cada grade/linha/desenho, tentar extrair descrição original, item local, código de desenho/MP, revisão, material, categoria provável, acabamento e unidade; quantidade local, de pai, global ou desconhecida; relação conjunto/filho, lado D/E, variantes e códigos de chamada; cada material/corte separadamente; medidas e texto literal associados à vista/linha/peça; carimbo (massa, área, material, espessura, escala, tolerância); e alterações de revisão.

Cada observação deve trazer origem, confiança por campo e evidência: arquivo, página, texto legível, região/caixa visual, unidade, papel da medida e motivo de dúvida. Modelo de resposta sugerido:

```json
{
  "page_type": "bom | detail | cut_table | title_block | assembly | photo | unknown",
  "revision": null,
  "tables": [],
  "items": [{
    "local_item": null,
    "code": null,
    "description": "",
    "material_text": null,
    "quantity": {"value": null, "scope": "unknown"},
    "parent_code": null,
    "side": null,
    "dimensions": [{
      "name": "comprimento", "value": null, "unit": "mm",
      "role": "finished_cut", "evidence": {"text": "", "bbox": null},
      "confidence": 0.0
    }],
    "weight_g": null,
    "alternatives": [],
    "uncertainties": []
  }],
  "page_notes": []
}
```

Os campos finais podem mudar, mas cada observação retém significado, unidade, escopo, evidência e proveniência. O que não foi visto é `null`, nunca inventado. Confiança é por observação/campo, não só uma nota geral da página.

### 3.3 Vínculo entre páginas e peças

- A lista geral pode estar no fim do PDF e os desenhos detalhados em páginas anteriores. Uma página de filho pode não imprimir o código do pai. Relacionar código do carimbo, descrição, nome do PDF, material, geometria, revisão, chamada e contexto.
- Vínculo pode atravessar páginas do mesmo PDF. Associação com PDF filho de outro arquivo pode ser sugerida pela IA, mas deve ser explícita e auditável.
- Número no desenho/quadro de corte é frequentemente local à folha, não ID global.
- Se houver mais de um candidato, perfil conflitante, revisão incompatível ou descrição genérica, não escolher o primeiro; abrir decisão pendente e mostrar evidências/candidatos.
- Não dizer “sem item correspondente” quando o item está em outra página do mesmo PDF.
- Mostrar todos os PDFs, inclusive ilegíveis, falhos, sem cota ou sem vínculo. Indicar motivo e permitir abrir a página.

### 3.4 Fila, falhas e economia de tokens

- Unidade de trabalho: arquivo/página/modelo/revisão do prompt. Usar fila persistente e concorrência baixa/configurável para respeitar cota gratuita.
- Cache por hash do PDF, página, modelo, instrução/schema e versão do pipeline. Cópias com conteúdo idêntico podem reutilizar leitura. Permitir reanálise forçada.
- Priorizar modelo visual econômico e reservar modelo mais forte para página complexa/ambígua. Os modelos Gemini 3.5 Flash-Lite, 3.1 Flash-Lite e 3.8 Flash constam no histórico, mas disponibilidade/preço/limites variam; não codificar cotas como permanentes.
- Google AI Studio Free tem limites próprios. ChatGPT Plus de estudante não aumenta cota Google. Mostrar dados devolvidos pelo provedor e distinguir pico histórico de limite/saldo disponível.
- 429 por minuto: aguardar no mesmo modelo com backoff. 429 diário explicitamente identificado: pausar esse modelo e encaminhar apenas páginas não concluídas ao seguinte. 429 ambíguo: aguardar e informar erro, sem presumir reset.
- 5xx/503: espera progressiva por modelo, sem repetir imediatamente todas as páginas. JSON inválido: repetir apenas página afetada com fallback. `URLError`/proxy/rede: diagnosticar conectividade; não tratar como cota nem trocar modelo em loop.
- Retry mostra estado e previsão de nova tentativa, sem inventar hora de reset que o provedor não informou.
- Economizar tokens com cache, prompts curtos, JSON enxuto, limite de saída, texto local como apoio e chamadas por página necessárias. Não reduzir resolução de cotas pequenas sem prova de legibilidade. Não reenviar página concluída.
- Chave somente em variável de ambiente/arquivo secreto local fora do controle de versão. Nunca enviar ao frontend nem inserir em logs/relatórios.

## 4. Reconciliar IA, leitor local e humano

A comparação ocorre **por campo e tipo da medida**, não por uma cadeia de texto inteira. Para cada dimensão, quantidade, material ou peso, apresentar valor IA/evidência, valor do leitor local/célula, valor manual atual, significado/unidade, vínculo da peça, escopo local/global, cálculo afetado e decisão.

1. Campo vazio + IA com evidência e identidade inequívoca: aplicar pela edição/histórico normais e recalcular. Não deixar pendência genérica quando há proposta elegível; mostrar evidência e ação para revisar/importar conforme automação configurada.
2. IA e leitor local independentes com mesmo valor **e significado**: marcar concordância e elevar confiança.
3. Divergência: manter as observações e mostrar conflito. Não substituir valor manual ou dado anterior automaticamente.
4. Valores com papéis diferentes não conflitam. Exemplo: 841 mm de corte acabado e 861 mm de consumo de arame.
5. “Importar todas as medidas elegíveis da IA” reaplica leituras válidas já salvas, sem nova chamada, mostra prévia e contagem de aplicadas/conflitos/sem vínculo/variantes sem quantidade, e pode ser repetida sem duplicação.
6. Peça só encontrada pela IA fica em itens descobertos, com PDF/evidência, fora da BOM/custo até confirmar vínculo e quantidade total.
7. IA não autoriza tarifa, área comercial CONTROLV, preço, quantidade total, folga de solda, corte desenvolvido ausente nem geometria inferida. Aplicar regras aprovadas ou decisão humana.

Manter três visões do mesmo projeto/revisão: **Script/leitura local**, **IA** e **Conferido (evidência independente comum)**. Uma cota importada da IA não valida a si própria. Concordância parcial é visível; não criar subtotal se faltar quantidade total ou dado necessário.

## 5. Peças, conjuntos e quantidades

- Orçamento cobra componentes físicos, não o subconjunto que organiza montagem.
- Modelar BOM por árvore/grafo de ocorrências. Quantidade efetiva = quantidade local × quantidades de todos os pais ancestrais.
- Guardar local, multiplicadores, total e origem separadamente. Quantidade local no desenho filho não substitui total do projeto.
- Cada linha de quadro de corte é um corte com material, perfil, comprimento e quantidade próprios. Não juntar comprimentos nem descartar linhas seguintes.
- Composição mista (chapa + ferro chato; tubo + chapas de reforço) vira componentes separados.
- Duas peças com texto/dimensões iguais podem ser peças físicas distintas. Não deduplicar por descrição, peso, código não global ou medida. IDs são estáveis.
- D/E só espelha/consolida com evidência. Ao consolidar visualmente, manter ocorrências e quantidade de cada lado; editar um lado não apaga o outro.
- Propagar mudança de subconjunto recursivamente a filhos, massa, área e custo. Não cobrar pai e filhos simultaneamente.
- Variantes codificadas sem quantidade ficam fora do custo até o pai/orçamento escolher variante e quantidade.

## 6. Sintaxes e famílias reais

Não há sintaxe única. Classifique a família e a estrutura de cada página antes de extrair. Preserve grade e células vazias, confirme com outras páginas do projeto. Regras de cliente são exemplos, não universais.

| Família/exemplo | Interpretação | Erro já ocorrido |
|---|---|---|
| Lista técnica 14 colunas | `ITEM, QTD, DESCRIÇÃO, GRUPO, MATERIAL, ESPESSURA, RAIO/DIÂMETRO, LARGURA, PROFUNDIDADE, COMPRIMENTO, DESENHO-ID, PESO, CÓDIGO(MP), OBSERVAÇÃO`; `R`/`RAIO` e `Ø` têm semânticas diferentes. | Deslocar peso/código/observação por campo vazio; raio virar diâmetro. |
| Lista compacta 7 colunas | `Item / Descrição / Qtd / Material / Dimensões / Acabamento / Código`. | Confundir começo de tabela de 14 colunas com lista compacta. |
| Material dentro da descrição | `CHAPA DE AÇO 0,90 - 1200X2000`, `CHAPA DE PVC 0,5 - 1000X2000`, `PSAI BRANCO 1,5 - 1250X2200`, `TUBO QUADRADO 20X20X0,9`, `ARAME Ø4MM`. Distinguir chapa de origem, bitola e peça. | Formato comercial 1200×2000 tratado como corte da peça. |
| Pai e PDF filho | Pai pode não ter cota; desenho/código filho tem a dimensão. | Item fica `-` apesar de cota no desenho filho ou link abre só pai. |
| Lista e detalhe em páginas diferentes | Relacionar em todo o PDF por código, descrição, material, revisão/contexto. | “Sem item correspondente” porque busca só na página aberta. |
| Quadro de cortes com ângulos | `Nº ITEM / MATERIAL / COMPRIMENTO / ÂNGULO1 / ÂNGULO2 / QTD`, linha por corte. | Só primeiro perfil aparece ou vários cortes são agregados. |
| Quadro de corte compacto | `Nº ITEM / MATERIAL / COMPRIMENTO / QTD`; algumas famílias RISE têm sete colunas com cabeçalho específico. | Cota externa usada como corte ou linhas abaixo de `-` perdidas. |
| CAN BASE/OUTPROMO | Cotas do detalhe; formato de chapa comercial separado; perfil reto pode ter corte, quadro/perfil dobrado pode ter só envelope. | Cotas presentes sem leitura ou envelope usado como desenvolvimento. |
| DURACELL, dimensão `A` | Filho dá A variável e medidas fixas; pai informa variante e QTD. Ex.: A=80/150/230; largura 15, esp. 0,90; QTD 2/4/5. | Uma A aplicada a todos ou dobra usada como comprimento. |
| Arame parametrizado | `CÓDIGO / NOMINAL / MEDIDA A / MEDIDA B / COMPRIMENTO`; A/B descrevem dobra; COMPRIMENTO é corte acabado. | Cobrar variantes sem quantidade ou usar A como corte. |
| ALPA quadro de arame | Pai traz código/QTD; filho diâmetro/corte; comparar 841 acabado com 861 consumido. | 20 mm de solda tratado como conflito ou quantidade de folha usada como total. |
| SCORE/AMBEV BRAHMA | 37 páginas, lista principal p.36–37, subconjuntos e cortes espalhados. | Ler só página inicial, perder filhos, misturar chapa/tubo, duplicar peça. |
| SCORE/BUD | Revisão 03 p.13 vs revisão obsoleta 02 p.81; cabeçalho QTD quebrado. | Escolher revisão velha, duplicar pai ou confundir g/kg. |
| RISE/DOCILE/P&G/RACIONAL | Ordens de coluna diversas, várias grades, filho identificado pelo carimbo, código de pai por contexto e quadro compacto. | Deslocar colunas ou associar grade ao conjunto errado. |
| PDF digitalizado | OCR preliminar com baixa confiança e página navegável. | Falha OCR tratada como falta real de item/cota. |
| Foto | Estimativa marcada, hipóteses e comparação com peso fornecido. | Inferência vendida como desenho validado. |

Lista de materiais pode vir na ordem `{item}{quantidade}{descrição}{grupo}{material}{espessura}{raio/diâmetro}{largura}{profundidade}{comprimento}{desenho-id}{peso}{código(mp)}{observação}`. A IA deve identificar visualmente a grade e posição, não depender de ordem rígida de texto extraído.

## 7. Significado de medida, peso e cálculo

Unidades: mm, m², kg, g, R$. Cada dimensão guarda `role`: chapa comercial, corte acabado, comprimento consumido, planificação, cota externa, dimensão de dobra, seção de perfil, posição de furo, diâmetro, raio ou área faturável. Reter valor original e normalizado.

- Não confundir chapa comprada com peça cortada.
- Não usar envelope externo de dobrado como comprimento desenvolvido.
- Planificação, dimensão montada e seção dobrada são medidas diferentes.
- Posição de furo, raio de canto, escala, revisão e números do carimbo não são cotas de corte pela proximidade visual.
- Se o desenho dá apenas envelope, declarar falta de corte e linkar folha. Não completar no palpite.
- Ao clicar na cota, abrir a página e realçar recorte/evidência.

```text
chapa:             C × L × espessura × densidade / 1.000.000
arame redondo:     π × (diâmetro/2)² × comprimento × densidade / 1.000.000
tubo retangular:   [a×b − (a−2e)(b−2e)] × comprimento × densidade / 1.000.000
tubo redondo:      π × [(d/2)² − (d/2−e)²] × comprimento × densidade / 1.000.000
área retangular:   C × L / 1.000.000
quantidade total:  quantidade local × quantidade dos pais ancestrais
```

Densidades: aço carbono 7,85; inox 7,90; alumínio 2,70; PSAI 1,05; acrílico 1,19; PETG 1,27; polionda 0,45 g/cm³. MDF usa carimbo ou densidade aprovada própria, nunca densidade do aço. Massa adotada não fica abaixo da massa geométrica bruta, de peso confiável do carimbo da peça ou de edição manual válida; divergência fica visível. Peso geral do conjunto não é copiado aos componentes.

Arame: `comprimento_acabado` é o corte do desenho. Adicionar **20 mm uma única vez por corte** ao `comprimento_consumido` para solda/custo. Massa acabada exclui folga; consumo inclui. Não adicionar 20 mm por segmento de dobra.

## 8. Materiais e preços aprovados

Classificar pela função. Chapa/tubo/arame metálicos são matéria-prima. PSAI, MDF, acrílico, PVC, PETG, ferragens, ventosas, embalagem e acessórios são comprados quando essa é sua função. Subconjunto é explicativo e não vira cobrança adicional.

| Material/serviço | Regra cadastrada | Se não houver correspondência |
|---|---|---|
| Chapa de aço carbono | R$ 7,02/kg | Pendente se material/espessura incertos. |
| Arame BTC | R$ 6,34/kg bruto × 0,7875; usar consumo com 20 mm/corte. | Pendente sem corte/bitola confiável. |
| Tubo | Catálogo do mesmo perfil/bitola: preço/kg + IPI 3,25% × 0,7875. Próxima espessura maior quando essa regra existir. | Perfil/tarifa ambígua = pendente. |
| BRAHMA específico | Fabricar/pesar 50×30×1,06 mm; tarifa/kg de 50×30×2 mm autorizada pelo usuário. | Mostrar ambas espessuras; não usar massa de 2 mm nem generalizar. |
| PSAI | Comprado; CONTROLV por cor/espessura/área, próxima espessura maior da mesma cor, colorido base branca +10%, impressão aprovada R$25/m² por face. | 4x1, cor/área duvidosa/fora da tabela = pendente. |
| Porta-preço/porta-etiqueta | Mesmo acessório, R$6,80/m se comprimento confiável. | Sem cota = pendente; gancho de arame segue preço de arame. |
| Pintura a pó | Manter tarifa R$/kg e fórmula aprovada. | Sem fonte aprovada = pendente. |
| MDF/acrílico/PVC/outros | Fonte própria aprovada e unidade correta. | Nunca aplicar preço ou densidade de metal. |
| Caixa de papelão | Normal: `((100+2(C+L))×(A+L))/1.000.000`; transpassada: `((100+2(C+L))×(A+2L))/1.000.000`. | Sem tarifa/tipo aprovada, pendente. |

Tarifa sempre registra fonte, data, unidade, perfil/cor/espessura/fator e aprovação. Preço histórico é comparação da mesma variante, não catálogo universal.

## 9. Persistência e catálogo: decisão sobre SQL vs CSV/JSON

Não é necessário manter cada peça de projeto como cadastro mestre reutilizável. É necessário persistir a BOM e revisão de cada projeto, resultados IA, páginas/evidências, decisões humanas, fila, cálculos e exportações para retomar, auditar e não consumir API novamente. Materiais físicos de um projeto são dados daquele projeto.

Recomenda-se persistir em SQLite: projetos/revisões, ocorrências/peças, medidas tipadas, observações IA, arquivos/páginas por hash, histórico, decisões, jobs e snapshots. Referências reutilizáveis incluem materiais, densidades, espessuras disponíveis, tarifas e fatores aprovados.

CSV/JSON é apropriado para tabelas pequenas e estáveis, somente leitura e versionadas; mantenha planilhas originais sem alteração como fonte. Se tarifas forem editadas/aprovadas com frequência, guarde-as em tabelas SQL com origem, validade e trilha. Não mantenha CSV/JSON e SQL como duas fontes concorrentes. Templates de saída continuam Excel.

Entidades sugeridas: `Project`, `ProjectRevision`, `SourceDocument`, `SourcePage`, `AiJob`, `Observation`, `Measurement`, `Assembly`, `Part`, `Occurrence`, `Cut`, `MaterialSpec`, `PriceReference`, `Decision`, `HumanOverride`, `CalculationSnapshot`, `ExportSnapshot`. Não usar descrição, código local, caminho do pai ou dimensões como chave única.

## 10. Interface React mais clara

A interface anterior tinha muitas seções numeradas, uma tabela BOM muito larga e ações de IA espalhadas. Isso causou dúvida sobre próximo passo, PDFs sem cota ocultos, mensagens “sem item” embora a peça estivesse noutra página, medida da IA não aplicada, leitura manual/página única, falta de importação em lote, status “Pendente” genérico, retry/modelo sem explicação e aparência de que as três visões eram projetos separados.

Organize o app em uma área única de projeto com grupos curtos: Projetos; Documentos e IA; Materiais; Peso; Custos; Pendências; Comparação; Exportação; Regras. A barra mostra projeto/origem/revisão, cobertura IA e estado. O painel inicial resume páginas analisadas, peças físicas, sem cota, conflitos, quantidades/variantes pendentes, peso não validado e preços pendentes.

Lista BOM compacta: descrição física, quantidade total, material/tipo, medidas principais, peso, custo/estado. Código, grupo, desenho, código MP, carimbo, observações e histórico ficam acessíveis no detalhe expansível, sem sumir. PDF e BOM ficam lado a lado ou em drawer; selecionar cota navega à região da folha. Filtros por fonte/estado/material e busca por código/descrição preservam contexto.

Estados com significado: aguardando IA; IA leu; sem cota nesta página; cota encontrada sem vínculo; pronta para importar; importada; conflito; edição manual; variante sem quantidade; sem corte desenvolvido; sem preço; erro de API com retry; revisão obsoleta. Não resumir todos em `Pendente`.

Ações obrigatórias: importar em lote cotas IA já armazenadas, sem custo/chamada nova; prévia de cada alteração/exclusão; aceitar/manter/editar/desfazer por campo; tela de itens descobertos fora do custo até confirmação; três visões IA/script/conferido claramente ligadas ao mesmo projeto; status de fila/retry/modelo/horário; exportação com lista de bloqueios. Usar rótulos e estados textuais acessíveis, não só cor/ícone.

O React deve estar completamente integrado ao backend. Não entregar HTML parcialmente trocado que aponta para bundle inexistente. Durante reconstrução, manter opção de voltar à versão antiga até passar validação funcional.

## 11. Arquitetura técnica

Usar monólito modular inicialmente; não manter lógica de orçamento dentro das rotas nem criar microserviços prematuros.

```text
frontend/ React + TypeScript
backend/api/             rotas, validação HTTP
backend/application/     casos de uso, transações, import/export
backend/domain/          BOM, medidas, decisões, massa, preço
backend/ai/              provedores, prompts/schema, fila, cache, retry
backend/documents/       inventário, render/OCR, leitores auxiliares
backend/reconciliation/  vínculo, confiança, conflito, importação IA
backend/pricing/         catálogo e escolha de tarifa aprovada
backend/export/          adaptadores dos dois Excel oficiais
backend/infrastructure/  SQLite/migrações, arquivos, segredo, jobs
```

IA e leitor local devolvem propostas com evidência; um caso de uso transacional reconcilia/grava, recalcula e cria histórico. Domínio é testável sem Gemini, Excel, browser ou banco. Frontend não calcula preço/peso como fonte autoritativa.

API mínima: CRUD de projetos; importação; listagem de docs/páginas; resultados IA/reanálise/fila; árvore/BOM; observações e medidas; prévia/aplicação em lote; conflitos/pendências; histórico/reversão; fontes e preços; três visões; completude; prévia/exportação.

A importação deve ser proposta de revisão com diff, não apagar e recriar BOM editada. Migração SQLite exige backup, contagem/identidade, comparação, preservação manual e rollback. Conferir todas as cópias da mesma origem; não esquecer outro cadastro ligado à pasta.

### Infraestrutura necessária para melhorar a leitura e a operação

- **Ingestão sem perda:** copiar/registrar arquivos em armazenamento interno controlado, manter originais imutáveis, calcular SHA-256 e registrar revisão. Usar hash para deduplicar arquivos iguais e recuperar resultados IA sem guardar cópias idênticas sem necessidade. Não depender somente de caminhos de rede que podem ficar indisponíveis.
- **Separação de arquivo e metadado:** SQLite guarda metadados, árvore, observações, decisões, tarifa e estados; PDFs/imagens ficam em armazenamento de arquivos por projeto/hash. Nunca carregar binário grande dentro de cada linha de material. Guardar cópia/retensão conforme configuração local e mostrar quando a origem ficou inacessível.
- **Fila durável de páginas:** cada job tem chave idempotente, estado, modelo, tentativas, próxima execução, erro categorizado e heartbeat/lease. Workers podem reiniciar sem perder página concluída nem duplicar aplicação. Usar concorrência e limite por provedor; separar erro de validação, JSON, rate limit, 5xx e rede/proxy.
- **Recuperação operacional:** retry com backoff/jitter e limite; reprocessamento manual seletivo; opção de pausar/cancelar; fila de falha permanente que continua visível; circuit breaker durante indisponibilidade; checkpoint após cada página. Um erro em página não interrompe as outras.
- **Processamento visual consistente:** armazenar texto vetorial/OCR paralelo ao render da página; preservar resolução suficiente para números pequenos; usar pré-processamento/crop apenas mantendo referência às coordenadas originais. Guardar versão do render/OCR/prompt/modelo para reproduzir uma leitura.
- **Persistência segura:** SQLite com transações, migrações versionadas, WAL/backup consistente e verificação de integridade; testes sempre em banco temporário. Manter camada de repositório para poder migrar para PostgreSQL se houver necessidade multiusuário, sem adotar serviço distribuído agora.
- **API resiliente:** validar entrada e saída com schemas tipados; endpoints de fila não bloqueiam durante leitura IA; respostas incluem IDs estáveis, revisão e proveniência; operações em lote têm idempotency key; erros mostram código e ação possível sem stack trace/chave.
- **Configuração e segredo:** modelos, limites, diretórios e timeout fora do código. Chave Google via variável/secret store do usuário. Aplicação local escuta somente em loopback por padrão; não expor chave em JavaScript, banco, tela ou telemetria.
- **Observabilidade útil:** logs estruturados com project/page/job IDs, duração, modelo e categoria do erro; métricas de páginas totais/concluídas/falhas, cache hit, tentativas e tempo de fila. Remover texto sensível e chave dos logs. Interface mostra o estado por página e não exige abrir terminal.
- **Backup e recuperação:** backup automático do banco antes de migração/reimportação e antes de reparos de dados; guardar export snapshot; restaurar projeto sem recuperar conteúdo de outros projetos. Testar restauração, não apenas criação de backup.
- **Limites de recursos:** limitar tamanho/contagem de upload, páginas simultâneas, memória de render, timeout e espaço em disco; processar por página sem manter PDFs renderizados todos na RAM. Mostrar progresso real por documento.
- **Instalação local previsível:** um launcher abre exatamente a versão/banco configurados, valida dependências, indica falta de Excel/OCR/API e não instala/edita arquivos de origem silenciosamente. Separar diretórios de produção, testes, cache, exportação e backups.

O alvo inicial pode continuar local no Windows com FastAPI, React e SQLite. A arquitetura deve ser tolerante a falha de rede/Google e preservar trabalho local; não exigir nuvem, microserviços ou banco externo para começar. Caso multiusuário entre no escopo depois, os contratos de API, IDs e camada de persistência devem permitir evolução sem reescrever cálculos e reconciliação.

## 12. Exportação

- Modelos vazios oficiais imutáveis. CÁLCULO só aba `Total`; demais abas preservadas. Cópias numeradas se lotar.
- Custo mantém as duas abas, categorias separadas, linhas ampliadas dentro da tabela e layout/formatação/fórmulas/área de impressão.
- Exportar componentes físicos, nunca pai e filhos cobrados juntos.
- PSAI/acessórios comprados em `RELAÇÃO MATERIAL COMPRADO`; chapa/tubo/arame em `RELAÇÃO MATÉRIA-PRIMA`.
- Nome de custo descreve componente, material e medida, por ex. `TUBO QUADRADO 20X20X1,2MM - TRAVESSA - 500MM`, `PSAI TESTEIRA 500X220X2MM`.
- Desconhecido vazio com pendência, nunca R$0,00. Não exportar markup.
- Conferir no Excel abas, linhas, fórmulas, pesos, subtotais, erros e impressão. Guardar snapshot de BOM/regras/fontes usados.

## 13. Exemplos reais de aceitação

1. **DURACELL**: PSAI lateral DIR/ESQ com PDF filho compartilhado, 250×150×1 mm; gaveta planificada 281,2×246,2×1 e base 110×70; perfil superior aberto 245,8×110×0,75 (230 após dobra); cantoneira aberta 135×38,3×0,90 (seção 20×20); chapa A=80/150/230 e QTD do pai 2/4/5. Área do carimbo diverge da caixa externa: mostrar, não forçar.
2. **CAN BASE Módulo D**: chapas 1350×250, 1110×250, 650×225, 1000×435; tubos 1050/800; PSAI 1345×249, 1105×249, 645×274, 430×998. Formatos comerciais separados. Perfis/quadros só com envelope ficam pendentes.
3. **ALPA BASICO 2X5**: pai/filho em páginas distintas; ARAME GANCHO Ø6, 841 mm acabado, 861 mm consumo, peso acabado/consumo separados, total 10.
4. **MALHA Grade Prateleira**: ARCO código 332856/QTD1, código exato da lista e desenho filho, Ø6, 2255 acabado/2275 consumido. TRAVESSA ambígua fica pendente. Importação em lote sem duplicação.
5. **FLEXVERO APARADOR**: código/nominal/A/comprimento; A=345/495/540, cortes 400/550/595, Ø5. Guardar variantes; quantidade nula até escolha do pai.
6. **BRAHMA ILHA**: 37 páginas, lista final, pais e cortes espalhados, composições distintas. Dois pares 2359×159×0,7 são peças diferentes; tampa de aço 1250×520×3 distinta do PSAI. Fabricar 50×30×1,06, tarifa 2 mm autorizada. Não forçar as 21 diferenças contra manual.
7. **BUD ILHA**: revisão 03 p.13 sobre 02 p.81; BOM 131,19 kg vs carimbo 131,26. Peso acabado não equivale ao consumo de metal; 33 medidas/composições estavam pendentes.
8. **RISE/DOCILE/P&G/RACIONAL/PEPSI**: ordem de colunas varia; várias grades/página; pai pelo carimbo/contexto; cabeçalho QTD quebrado; cortes compactos e quantidades decimais.
9. **RECKITT**: planificação, recortes, posição de furo não largura, PSAI 1x0 sem tarifa, cópias da mesma pasta; preservar alterações/lados.
10. **Hellmann's e REHAU por foto**: declarar hipótese e comparar peso. Hellmann's: arame Ø4 e sete chapas 0,75 separadas, duas ventosas; metal estimado 1,358 kg vs ~0,9kg da imagem, diferença aberta. REHAU: cliente fornece rolos/amostras, orçamento cobre suportes/montagem. Expositor chão corrigido para **10 rolos**, MDF trocado por PSAI, base tubular fechada por PSAI, sem chapa 10 mm. Giratório tem **32 rolos/cores em quatro faces**, altura 1900 mm e mecanismo giratório. Dimensões, fixação, estabilidade e custos continuam hipóteses até protótipo/ensaio. Variante intermediária #98 de 8 rolos não deve virar cotação atual.

## 14. Histórico de falhas a não repetir (R01–R63)

Índice de cada regressão numerada em `REGRESSOES.md`. Esse arquivo mantém status/teste/arquivo real detalhado. Comportamentos são contratos, mesmo se o parser for refeito.

| ID | Falha observada | Contrato novo |
|---|---|---|
| R01 | Só aceitava ZIP; risco de caminho `../`. | Aceitar pasta/PDF/ZIP/RAR e validar entradas. |
| R02 | Sintaxe de uma família aplicada a outra; digitalizados sem cotas. | Classificar família; OCR incerto é preliminar. |
| R03 | Comprado, MP e subconjunto misturados. | Categoria física correta; pai não é custo adicional. |
| R04 | Filhos não multiplicavam pelos ancestrais. | Quantidade, peso, área e custo propagam todos os pais. |
| R05 | D/E omitido/duplicado; edição de um lado apagava outro. | Espelhar com evidência e preservar ocorrências/lados. |
| R06 | Lista ALPA de 14 colunas deslocava campos e raio/diâmetro. | Ler grade/células vazias e distinguir R de Ø. |
| R07 | Chapa comercial 1200×2000 tratada como corte. | Separar origem, espessura e peça. |
| R08 | Cotas CAN BASE visíveis não chegavam ao app. | Associar lista e desenho filho/carimbo. |
| R09 | Quadro de cortes perdia linhas ou juntava dois cortes. | Linha e comprimento próprios. |
| R10 | Cota externa de dobrado usada como corte. | Comprimento desenvolvido; senão pendente. |
| R11 | Cota só visual Ø5×40 / 20×15×0,75 não calculava. | Leitura multimodal com evidência. |
| R12 | Peso abaixo da geometria/carimbo; edição manual quebrava validação. | Recalcular, preservar override e explicar diferença. |
| R13 | Acréscimo de solda errado/repetido. | +20 mm por corte, só consumo. |
| R14 | Perfil de tubo dividido e precificado errado. | Reconstruir perfil; ambiguidade pendente. |
| R15 | Fatores de tarifa antigos/incorretos. | Usar fonte aprovada e regra de próxima espessura maior quando aplicável. |
| R16 | PSAI classificado/preçado errado. | Comprado, CONTROLV, cor/espessura/impressão corretos. |
| R17 | Porta-preço e porta-etiqueta com tarifas distintas. | Mesmo R$6,80/m; gancho de arame segue arame. |
| R18 | Planilha perdia itens/layout ao lotar. | CÁLCULO numerado; custo cresce dentro da tabela; só dois modelos. |
| R19 | Tarifa da pintura em pó sumia na exportação. | Preservar custo/kg e fórmula. |
| R20 | Foto Hellmann's interpretada como chapa dobrada. | Estimativa explícita; sete chapas/arame separados; comparar peso. |
| R21 | DURACELL lateral apontava ao pai, não ao PDF filho DIR/ESQ. | Vínculo único e lados visíveis. |
| R22 | PDF sem cota/vínculo desaparecia. | Mostrar inventário inteiro e estado por página. |
| R23 | Gaveta PSAI tinha desenho com cota e item vazio. | Completar só campo vazio vinculado, preservar manual. |
| R24 | Perfil/cantoneira confundiam planificação, dobra e seção. | Usar dimensão aberta validada, cota após dobra separada. |
| R25 | Só uma de duas cópias da mesma origem foi corrigida. | Verificar todas as cópias ligadas à pasta. |
| R26 | Variantes A do pai e largura/espessura do filho não se juntavam. | Associar A e completar cotas fixas válidas. |
| R27 | RECKITT/MÓVEL PONTA juntavam cortes. | Manter linha por corte, inclusive após campo vazio. |
| R28 | Tubo em polegadas/ferro chato tinham massa/classe errada. | Normalizar perfil e separar MDF de aço. |
| R29 | Chapas planificadas ignoradas ou selecionadas sem validação. | Cota única coerente; concorrente pendente. |
| R30 | OP01 sem componentes espelhados em cópias salvas. | Completar só os componentes faltantes, preservar demais. |
| R31 | VEJA faltava embalagem/QR/grampo; ALPA pés. | Não perder acessórios listados nem editar outros itens. |
| R32 | PSAI 1x0 cobrado como 0x0. | Sem tarifa de impressão, preço pendente. |
| R33 | Distância de furo virou largura; recorte afetava peso. | Posição ≠ dimensão; validar massa e mostrar recortes. |
| R34 | Atalho iniciava cópia antiga do app. | Launcher único aponta à versão/banco ativo. |
| R35 | Testes inseriam projetos no SQLite real. | Isolar banco de teste. |
| R36 | Script falhava em cota filho; IA precisava comparar sem apagar manual. | Reconciliar por campo/ocorrência com evidência. |
| R37 | Modelo não adequado e cache não separado por modelo. | Roteamento configurável e cache completo. |
| R38 | IA só lia primeira página/apenas após clique. | Fila automática em todas as páginas e PDFs. |
| R39 | HTTP 503 encerrava ou repetia sem backoff. | Retry temporário por página/modelo e estado visível. |
| R40 | Modelo de cota baixa usado sem observar limite. | Respeitar cota/configuração corrente. |
| R41 | Fallback podia usar modelo não habilitado/exceder limite. | Fallback condicionado e lista configurável. |
| R42 | JSON inválido em poucas páginas interrompia a leitura. | Repetir só página afetada. |
| R43 | IA achou 299×234 no filho, item permaneceu sem cota. | Vincular observação ao cadastro via fluxo normal. |
| R44 | IA tratou cota externa de chapa dobrada como corte. | Dimensões tipadas; externo não vira planificação. |
| R45 | Excel diferia R$0,02 pela ordem de arredondamento. | Uma regra de arredondamento entre app/exportação. |
| R46 | Faltava importar em lote cotas IA encontradas. | Ação idempotente, sem nova API, com prévia. |
| R47 | MEDIDA A confundida com corte e variantes cobradas sem quantidade. | A/B de dobra; COMPRIMENTO corte; QTD nula até escolha. |
| R48 | Retry e cópias da mesma pasta reenviavam página concluída. | Cache de hash e retomada de pendentes. |
| R49 | Lista e detalhe em páginas diferentes não se vinculavam. | Correlação dentro do documento inteiro. |
| R50 | Corte acabado 841 vs consumo 861 gerava conflito e IA-only podia duplicar. | Tipar massa/comprimento e guardar descoberta fora do custo. |
| R51 | Proxy causou URLError como se fosse indisponibilidade Gemini. | Diagnosticar rede, sem troca falsa de modelo. |
| R52 | Tabela de arame por código não completava item. | Exigir código + filho + linha/evidência; preservar QTD/manual. |
| R53 | Três visões criavam falsa concordância pós-importação IA. | Recuperar leitura independente anterior e excluir auto-confirmação. |
| R54 | Teste de fila falhava por ordem temporal variável. | Simular a fila até estado final, sem ordem presumida. |
| R55 | BRAHMA 37 páginas aparecia só como pai. | Ler lista final, hierarquia e quadros de corte. |
| R56 | Orçamento manual BRAHMA revelou componentes omitidos e peças iguais distintas. | Decompor fisicamente; não deduplicar nem forçar 21 diferenças. |
| R57 | Bitola física 1,06 trocada por tarifa 2 mm. | Massa 1,06; preço 2 só por autorização específica. |
| R58 | RISE AMB0021 não ligava BOM filho identificado no carimbo. | Vincular M02/M06/M07/M11, multiplicar M11 ×3, não puxar M12 avulso. |
| R59 | BUD escolhia revisão 02 e perdia BOM/QTD quebrados e unidade de peso. | Preferir revisão 03, recuperar filhos e validar g/kg. |
| R60 | DOCILE/P&G tinham ordens de colunas distintas, lados e pais perdidos. | Detectar grade/raiz e reconhecer SUB-MONTAGEM. |
| R61 | Múltiplas grades e quadros compactos eram unidos ou perdidos. | Associar cada tabela ao pai com evidência e ler família compacta certa. |
| R62 | Quantidade decimal 0,08 engolia descrição; lista 14 colunas virava 7. | Ler célula decimal e validar cabeçalho completo. |
| R63 | Histórico RISE não bate em massa/custo, mesmo com cortes compatíveis. | Documentar diferenças por variante; não forçar igualdade com constante. |

## 15. Pendências abertas e hipóteses (P01–P26)

Pendência significa que evidência atual não autoriza número final. A interface deve explicar e permitir resolver; não mascarar com chute.

| ID | O que falta resolver |
|---|---|
| P01 | Célula pode listar tubo e arame; só separar quando PDF der corte/QTD confiáveis por material. |
| P02 | PDFs digitalizados José Vitor/ALPA podem precisar OCR e conferência visual. |
| P03 | CAN BASE: perfil U/quadro/tubo dobrado pode ter envelope sem desenvolvimento/segmentos. |
| P04 | Tarifa PSAI/impressão diverge dos históricos tag/testeira/lateral; confirmar serviços/perdas/mínimo. |
| P05 | Embalagens, ponteiras, rebites, parafusos e outros comprados carecem de tarifa ou desenho. |
| P06 | Reimportar projeto salvo precisa mesclar por identidade e preservar edição. |
| P07 | RECKITT, VEJA, DURACELL, ALPA, CAN BASE têm diferenças por variante; `VALIDACAO.md`. |
| P08 | `.xls` fiel requer Excel Windows; inspeção visual/recálculo real além do teste estrutural. Aba Total tem tarifas antigas. |
| P09 | Hellmann's: arame/planificação/vazados/sete chapas por foto; 1,358 kg bruto vs ~0,9kg imagem; preço de ventosa pendente. |
| P10 | Markup histórico diverge; usuário preenche externamente. |
| P11 | Não consta P11 no registro consultado; não inventar conteúdo. |
| P12 | Lateral DURACELL 250×150×1: carimbo 0,054665m² vs caixa 0,0375m²; confirmar área faturável. |
| P13 | Gaveta: planificação 281,2×246,2×1, base 110×70; carimbo 0,107731m²/83,646g vs envelope 0,069231m²/72,693g. |
| P14 | Quadros MÓVEL PONTA dependem de variante H2770/H2670 não escolhida pelo pai. |
| P15 | OP01/CAN BASE têm cotas externas sem corte desenvolvido; havia 72 linhas de MP sem comprimento confiável. |
| P16 | CONTROLV sem tarifa PSAI `1x0`; 12 painéis RECKITT sem preço/área aprovados. |
| P17 | IA pode confundir raio/diâmetro, QTD local/total e superfície/corte PSAI; revisar tipo/evidência. |
| P18 | Três páginas JSON inválido/fallback 503 sem conferência final: duas ALPA obsoletas e PETG DURACELL. |
| P19 | PSAI frontal DURACELL 299×234 externo vs carimbo 0,131708152m²/102,365g; área preço pendente. |
| P20 | BRAHMA #93: 21 diferenças contra custos manuais; BATEDOR/APARADOR sem corte, tarifas faltando, 18 sem preço. |
| P21 | BUD: comparar 91 lançamentos de 10 CÁLCULOs por código/revisão; 33 medidas pendentes; 156,710kg manual não equivale a 106,119kg conhecido. |
| P22 | REHAU foto #97: dimensões/cortes inferidos, estabilidade/fornecedores pendentes. |
| P23 | REHAU #98 de 8 rolos foi variante intermediária corrigida; não usar como cotação atual. |
| P24 | Primeira proposta 10 rolos #99 tinha MDF e lastros 10mm; substituída por PSAI e base tubular. |
| P25 | REHAU chão #99: dez rolos, sem MDF/chapa 10mm; confirmar largura axial, fixação, montagem e tombamento. |
| P26 | REHAU giratório #100: 32 rolos/quatro faces/1900mm; validar carga, mancal, guia, estabilidade e giro cíclico. |

## 16. Validação e conclusão

Última linha de base documentada: **188 testes aprovados em 23/10/2026**. É a informação histórica do registro, não execução nova nem prova de que todo orçamento está correto. R63 e P01–P26 continuam com detalhes/pendências nos arquivos de referência.

Na reconstrução, cada falha reproduzível recebe teste de regressão com caso real/família e caso vizinho que não pode mudar. Validar imagem/extração, vínculo, cálculo, e Excel; JSON válido ou suíte verde não prova que a cota do PDF foi interpretada corretamente. Testes usam banco isolado. Comparar PDF com orçamento histórico da mesma variante e registrar diferença não explicada. Migração exige backup e comparação para todas as cópias da mesma origem. Abrir planilhas geradas no Excel e conferir abas, linhas, fórmulas, pesos, totais, erros e impressão.

O app está pronto quando coleta automaticamente todos os documentos, apresenta vínculos/evidências, aplica apenas decisões elegíveis, preserva edições, calcula valores conhecidos sem inventar os desconhecidos e produz os dois modelos oficiais revisáveis. Pendência remanescente pode existir, mas nunca escondida.

## 17. Arquivos de referência

- `REGRESSOES.md`: casos R01–R63, estado, arquivos reais e testes.
- `MAPA_FONTES.md`: planilhas, unidades, tarifas e fórmulas atuais.
- `GUIA_RECONSTRUCAO.md`: modelo do app anterior, cálculos e famílias de PDFs.
- `VALIDACAO.md`: comparações reais e diferenças frente a PDFs/históricos.
- `data/BRAHMA_CONFERENCIA_ORCAMENTO.md`, `data/BUD_BRAHMA_PADROES.md`.
- `data/audits/RISE_AMOSTRAS_20261023.md`.
- `data/REHAU_CHAO_PSAI_10_ROLOS_20261022.md`, `data/REHAU_ORCAMENTO_FOTO_20261022.md` e relatórios associados.

