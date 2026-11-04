# Orçamentos PDV e displays

Aplicativo local em português para importar projetos, revisar a lista de materiais, conferir peso, calcular custo e markup e exportar orçamento. O banco é SQLite em `data/orcamento.db`; os arquivos de origem em `arquivos_raw` e `DADOS` são apenas lidos.

## Abrir no Windows

1. Instale Python 3.11 ou mais recente, com `python` ou `py -3` disponível no terminal.
2. Dê dois cliques em `run_app.bat`. Se as bibliotecas não estiverem instaladas, o script cria `.venv` e instala `requirements.txt` na primeira abertura.
3. Abra [http://127.0.0.1:8080](http://127.0.0.1:8080). Deixe a janela do servidor aberta durante o uso. Todos os dados ficam no computador.

O OCR de PDFs digitalizados usa Tesseract local quando instalado e disponível no `PATH`. PDFs digitais são lidos diretamente. Se não houver OCR ou um desenho não trouxer cotas em texto, o aplicativo registra pendência para conferência manual. Não usa serviço externo.

Quando a lista de materiais não traz medidas, o leitor consulta o PDF do desenho da peça. Ele reconhece chapas com comprimento, largura e espessura separados no desenho, e arames com uma cota de comprimento e indicação de diâmetro. O peso em gramas do carimbo é convertido para kg, inclusive em desenhos com escala decimal (por exemplo, 1:1.5). Desenhos parametrizados com MEDIDA A podem fornecer variantes como travessas e canaletas de comprimentos diferentes. Valores preenchidos manualmente em projetos já salvos são preservados; `python backfill_drawing_details.py ID_DO_PROJETO` mostra as lacunas que podem ser preenchidas, e `--apply` grava após criar backup.

Na **Lista de materiais**, o painel **PDFs do projeto** mostra todos os arquivos da pasta importada, inclusive desenhos sem cotas extraídas ou sem item vinculado. O nome pode ser pesquisado e cada PDF abre na página de origem. Quando a lista separa `DIR` e `ESQ`, mas um único PDF de peça sem lado mostra explicitamente ambos, o leitor associa os dois itens a esse PDF. O DURACELL é um exemplo: `PSAI LAT. DIR/ESQ` usa o desenho filho `PSAI LAT.` com 250×150×1 mm. Um PDF sem indicação dos dois lados não é associado por semelhança de nome.

Em chapas e PSAI com várias cotas de dobras, furos e vistas, o leitor usa as duas cotas gerais da peça aberta somente quando elas são as duas medidas dominantes do desenho. Compara a massa bruta do retângulo com o peso do carimbo e usa o maior valor no orçamento. A área usada na cotação de PSAI segue o valor extraído do PDF e a tabela CONTROLV da empresa. Se o carimbo superar a massa bruta por mais de 10%, a observação pede revisão de densidade, espessura e cotas; o peso por si só não determina qual par de medidas é correto. Quando as cotas competem entre si, as dimensões ficam pendentes de medição manual.

Nas listas técnicas, o leitor preserva a última cota antes do código do desenho. A observação “impressão frente” gera pendência para confirmar quantidade de cores e área impressa; ela não basta para selecionar automaticamente `4x0`. Preços unitários digitados nas planilhas históricas de custo são referências específicas daquele orçamento e podem incluir serviços ou condições que não aparecem na fórmula de matéria-prima da CONTROLV.

Quando a **Lista de Materiais** traz as colunas `ITEM / QTD / DESCRIÇÃO / GRUPO / MATERIAL / ESPESSURA / Ø / LARGURA / PROFUNDIDADE / COMPRIMENTO / DESENHO / PESO (kg) / CÓDIGO (MP) / OBSERVAÇÃO`, o leitor usa a grade desenhada no PDF para associar cada valor à coluna correta, inclusive quando há células vazias. Preserva separadamente ID do desenho, código MP, peso e observação; estes identificadores ficam visíveis na lista do app. Valores marcados como raio (`R`/`RAIO`) são convertidos para diâmetro antes do cálculo; `Ø` já indica diâmetro. Uma segunda cota de chapa ou PSAI impressa em **Profundidade**, sem comprimento, permanece registrada nessa coluna e também é usada como comprimento para calcular a área, com explicação na observação. PDFs sem grade legível continuam usando a leitura textual e podem exigir conferência.

Na lista de sete colunas `Item / Descrição / Qtd / Material / Dimensões / Acabamento / Código`, o leitor interpreta `CHAPA DE AÇO 0,90 - 1200X3000`, `CHAPA DE PVC 0,5 - 1000X2000` e `PSAI BRANCO 1,5 - 1250X2200` como tipo, espessura e **formato da chapa de origem** (primeira medida × segunda medida). Esse formato aparece na coluna Dimensões do app, identificado como “Chapa de origem”, separado das cotas da peça usadas em peso e custo. A espessura também pode vir na coluna Dimensões do PDF (`ESP. 0,9mm`). Perfis como `TUBO 20X20X0,9` preenchem seção e espessura, e `ARAME Ø4MM` preenche diâmetro. Quando a célula lista mais de um perfil, a composição fica pendente. O mesmo reconhecimento de material é aplicado como complemento às outras famílias de lista, sem substituir cotas medidas no desenho.

No CAN BASE Módulo D, as folhas 4–11 trazem quatro chapas cortadas de 1350×250, 1110×250, 650×225 e 1000×435 mm, além de tubos retos de 1050 e 800 mm; o leitor associa essas cotas aos respectivos itens da lista e calcula a massa bruta. A página 12 dá as cotas de quatro comunicações PSAI: 1345×249, 1105×249, 645×274 e 430×998 mm. O formato comercial (`1200×2000`, `1200×3000` ou `1250×2200 mm`) continua visível em separado. Quadros soldados, perfis U, suportes e tubos dobrados mostram suas **cotas externas** na lista; comprimento desenvolvido e número de segmentos ficam pendentes quando o desenho não os especifica. Cota externa não entra como comprimento de corte nem como peso de uma peça única.

Nos desenhos que trazem o quadro **Nº do item / Material / Comprimento / Qtd.**, o comprimento desenvolvido e a quantidade de cada linha são lidos desse quadro; as cotas gerais da peça dobrada não são usadas como comprimento de corte. O app calcula a massa bruta pela seção do arame, tubo ou chapa e pela densidade do material, compara com o peso do carimbo e usa o maior valor por peça. A observação do item mostra os dois pesos e o adotado. Para arame, o peso da peça pronta continua separado do consumo dos 20 mm extras de solda. Um PDF único com esse quadro também gera seus itens de matéria-prima. Divergências podem indicar furos, recortes ou diferença de densidade e devem ser revisadas no desenho.

Para tubos, o leitor junta as linhas do carimbo quando o tipo e o perfil vêm separados (por exemplo, `TUBO IND. RET` e `50x30x2mm`). Em desenhos de tubo reto sem quadro de corte, usa a cota geral de comprimento apenas quando ela é a primeira e única maior medida; desenhos dobrados sem comprimento desenvolvido ficam pendentes de medição. O peso bruto de um tubo retangular é `(largura × altura − (largura − 2 × espessura) × (altura − 2 × espessura)) × comprimento × densidade / 1.000.000`. O peso adotado nunca fica abaixo desse cálculo nem do carimbo, e a observação mostra perfil, comprimento e comparação.

Edições manuais passam pela mesma conferência. Se o perfil escrito no material mudar, as medidas do tubo são atualizadas; se o texto e os campos numéricos forem alterados para perfis diferentes na mesma gravação, o app pede correção. Ao editar comprimento, espessura ou peso, o app relê o PDF vinculado à peça, recalcula a massa bruta e mantém o maior entre peso informado, cálculo e carimbo. A resposta mostra os três valores e destaca medidas diferentes do desenho. O peso não pode ser reduzido abaixo desse mínimo; quando falta uma medida necessária, a pendência de validação aparece no item. A observação antiga da conferência é substituída pela atual, preservando comentários escritos pelo usuário.

## Fluxo de trabalho

1. Em **Projetos**, crie um orçamento e importe a pasta do projeto ou um ZIP. O comando **Importar 3 históricos** carrega as três amostras reais de `DADOS`.
2. Em **Lista de materiais**, revise quantidades, grupo, medidas, peso, unidade, impressão e o link para a página de origem. Adicione, corrija ou remova itens; alterações ficam registradas.

Quando a lista técnica traz lados direito e esquerdo, mas apenas um deles tem lista de componentes, o leitor usa o desenho detalhado para o outro lado somente se houver instrução explícita de montagem espelhada no PDF. Se as peças espelhadas tiverem a mesma geometria, peso e preço unitário, cada par fica em uma linha: a quantidade, o peso e o custo incluem os dois lados. Os dois subconjuntos continuam identificados na árvore, com o lado espelhado vinculado à linha consolidada. Desenhos distintos ou preços diferentes continuam em linhas separadas. Se o desenho pede espelho sem identificar a contraparte na lista, o app abre uma pendência para confirmar a quantidade e o código antes de incluir peças.

Subconjuntos aparecem na **estrutura do produto** para explicar a composição e editar sua quantidade; a **lista de materiais** e as planilhas mostram somente as peças físicas. Na importação, cada quantidade de peça é multiplicada pelas quantidades de todos os subconjuntos acima dela. Se a quantidade de um subconjunto salvo for alterada, o app atualiza recursivamente as peças e subconjuntos internos, seus pesos, áreas e custos, registrando as alterações. A árvore mostra a quantidade por pai e o total no produto. Peças consolidadas de direita/esquerda preservam a parcela do lado que não foi alterado. Subconjuntos sem desenho detalhado continuam como pendência de composição; o app não inventa peças.
3. Em **Conferência**, compare o peso acabado com o carimbo do PDF. O comprimento de corte do arame recebe 20 mm extras por peça para a solda; esse excesso entra no peso de consumo e no custo, mas não no peso do produto pronto. A comparação fica **incompleta** enquanto houver itens sem peso, e o app mostra quais são.
4. Em **Regras e preços**, confira a fonte, a data e a unidade, e aprove somente as referências vigentes. O catálogo histórico precisa de aprovação por item. Em **Custos**, revise os custos de matéria-prima e comprados. O markup é preenchido separadamente por você.
5. Resolva as **Pendências** após revisar o desenho e completar unidade, peso e preços. Valores desconhecidos aparecem como pendentes; uma quantidade fracionária extraída sem unidade explícita exige definição manual.
6. Em **Orçamento final**, baixe os dois modelos da empresa: `CÁLCULO+N. -1.xls` e `PLANILHA DE CUSTO -.xlsx`. O app preenche apenas a aba `Total` do CÁLCULO, preservando as outras sete abas e o layout original. Cada família aceita oito peças por arquivo; quando excede esse limite, o app gera CÁLCULOS numerados no ZIP. PSAI aparece somente em material comprado. A planilha de custo conserva as duas abas e amplia as linhas dentro das tabelas para incluir todos os itens. O usuário preenche o FATOR MARKUP separadamente.

As planilhas de custo separam matéria-prima de comprados e não cobram subconjuntos novamente. Preços desconhecidos ficam vazios. O CÁLCULO conserva as fórmulas geométricas originais; a planilha de custo usa o peso validado do app, que pode ser maior que o peso geométrico quando o PDF assim exige. O Excel instalado no Windows é necessário para preservar exatamente o arquivo `.xls`, suas fórmulas e a formatação durante a exportação.

Para metal, o aplicativo usa o peso unitário calculado ou lido do desenho. Chapa de aço carbono custa R$ 7,02/kg. Arame custa R$ 6,34/kg bruto × 0,7875. Tubo usa o preço por kg do perfil com as mesmas medidas na tabela de comprados, acrescido de IPI de 3,25% e multiplicado por 0,7875. A planilha de custo exportada mostra preço base, IPI, fator e peso nas colunas L–O, com o custo unitário calculado por fórmula. Perfis sem correspondência única continuam pendentes para revisão.

Para arames com diâmetro e comprimento identificados, a quantidade de material e as planilhas usam o comprimento do desenho mais 20 mm por peça. Quando falta a cota, o comprimento nominal pode ser estimado pelo peso e diâmetro do desenho de uma peça única; grades ou montagens de vários arames permanecem para revisão.

**Porta preço** e **porta etiqueta** são o mesmo acessório comprado para cotação: ambos usam a regra aprovada de R$ 6,80 por metro linear. O custo unitário é o comprimento da peça em milímetros dividido por 1.000, multiplicado por R$ 6,80. O leitor aproveita a cota já extraída ou uma medida explícita na descrição; sem comprimento confiável, o preço fica pendente. Peças de arame chamadas “porta etiqueta gancho” seguem a regra de arame.

PSAI fica em **material comprado**. O app lê a tabela CONTROLV por cor e espessura (coluna D), multiplica pelo m² da peça e soma R$ 25/m² por face para impressão `4x0` ou `4x4`. Quando a espessura do desenho não existe na tabela, usa a menor espessura disponível **igual ou maior** para a mesma cor; por exemplo, 0,9 mm usa o preço de 1 mm. Para PSAI colorido, usa a base branca dessa espessura com acréscimo de 10%, conforme a coluna K. A origem do preço mostra a espessura original e a utilizada. Sem cor, sem espessura disponível acima ou com `4x1`, o preço fica pendente para revisão. Se a tabela CONTROLV for alterada, execute `python refresh_controlv.py` para atualizar os preços locais e guardar um backup do banco.

As versões guardam uma fotografia dos materiais, cálculos, regras e preços aprovados. Uma edição posterior devolve o projeto à condição preliminar; versões anteriores permanecem no banco.

## Instalação manual e teste

```powershell
python -m pip install -r requirements.txt
python app.py
```

Depois de cada correção, execute `verificar_regressoes.bat` para rodar toda a suíte, incluindo importação, cotas nos desenhos, preços, hierarquia, espelhamento e modelos. O banco de teste fica em `data/test_runs`; o banco principal não é alterado. Para mudanças de PDF ou planilha, confira também um exemplo real da variante afetada.

Veja [MAPA_FONTES.md](MAPA_FONTES.md) para fórmulas/unidades, [REGRESSOES.md](REGRESSOES.md) para bugs e testes que devem acompanhar cada correção, e [VALIDACAO.md](VALIDACAO.md) para as diferenças encontradas nos históricos.

## Estrutura

- `app.py`: interface/API local e aprovações.
- `reader_v3.py`: leitura de PDFs e árvore de conjuntos.
- `sync_mirrored_parts.py`: complementa um projeto já importado com componentes espelhados, preservando ajustes e preços existentes e criando cópia de segurança do banco antes da alteração.
- `migrate_side_quantities.py`: consolida pares espelhados já salvos, registra as alterações e cria backup antes da migração.
- `repair_existing_weight_data.py`: atualiza projetos salvos com o corte de arame e peças parametrizadas identificadas no PDF, preservando os ajustes manuais do orçamento RECKITT antigo e criando backup.
- `calc_engine.py`, `pricing.py`, `markup_engine.py`, `comparator.py`: geometria, preços, venda e peso.
- `database.py`: banco SQLite e migração.
- `exporter.py`: PDF, XLSX e CSV.
- `template_reports.py`, `fill_company_templates.ps1` e `templates/spreadsheets`: preenchimento dos dois modelos originais usados pela equipe.
- `data/orcamento.db`: projetos de exemplo; faça cópia deste arquivo para backup dos seus orçamentos.

O aplicativo funciona sem Notion ou arquivos originais após a importação de cada projeto. A exportação exata dos dois modelos exige Microsoft Excel instalado no Windows; abrir a página PDF de origem depende de a pasta do projeto continuar no mesmo caminho. Preços aprovados são copiados ao banco.
