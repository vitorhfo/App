# Instruções permanentes para o aplicativo de orçamento

Estas instruções se aplicam a `orcamento_app/` e aos exemplos de `arquivos_raw/` e `../DADOS/`. Leia `orcamento_app/REGRESSOES.md` e `orcamento_app/MAPA_FONTES.md` antes de alterar leitura, cálculo, preço, quantidade ou exportação. A solicitação atual do usuário prevalece sobre este arquivo.

## Regra para cada correção

1. Identifique a família de PDF/planilha afetada e uma amostra real. Não generalize uma regra de um cliente para todos os projetos.
2. Registre no `REGRESSOES.md` o sintoma, a regra esperada, o arquivo real de referência, o estado da correção e o teste que a protege. Distinga **corrigido**, **pendente** e **hipótese de foto**.
3. Quando o bug puder ser reproduzido em código, acrescente um teste que falhe antes da correção e passe depois. Confira também o caso próximo que não deve ser alterado (outra sintaxe, outro lado, outro material, outro arquivo). Não crie testes que apenas repitam uma constante ou a implementação.
4. Rode `py -3 -m unittest discover -p 'test_*.py' -q` em `orcamento_app/` após a mudança. Para exportação, confira também os arquivos gerados no Excel: quantidade de linhas, fórmulas, abas, totais, erros e impressão. Uma suíte verde sozinha não comprova que o PDF foi interpretado corretamente.
5. Compare o resultado com o PDF e, quando houver, com um orçamento histórico da **mesma variante**. Registre diferenças não explicadas como pendências; preços históricos manuais não viram regras universais.
6. Antes de declarar uma correção de projeto salvo concluída, procure **todas as cópias vinculadas à mesma pasta de origem** e confira nelas o mesmo caso. Preserve edições manuais e crie backup do SQLite antes de migrar cada cópia; teste que os outros itens não mudaram. Não altere os arquivos originais de `arquivos_raw/`, `../DADOS/` ou os modelos vazios para fazer um resultado parecer correto.

## Contratos que não podem regredir

- O orçamento inclui **peças físicas**, não cobra subconjuntos. Multiplique cada peça pela quantidade dos subconjuntos ancestrais; trate lados direito/esquerdo conforme o desenho e preserve a parcela do outro lado em edições.
- Leia cada linha de quadro de corte como item próprio. Não junte dois perfis/cortes em uma linha nem use formato da chapa comercial ou cota externa de peça dobrada como corte da peça.
- Use as cotas do desenho da peça quando a lista não as trouxer. Valide peso calculado, peso do carimbo e edições manuais; falta de medida gera pendência, não peso ou preço inventado. Arame recebe **20 mm por corte** apenas no consumo, não na massa acabada.
- Classifique PSAI e acessórios como **comprados**; chapa, tubo e arame como matéria-prima. Use preços e fatores aprovados em `MAPA_FONTES.md`; medida sem tarifa exata usa a próxima espessura **maior** quando essa regra existir. Preço desconhecido permanece pendente.
- Entregue os modelos originais `CÁLCULO+N. -1.xls` (somente aba `Total` preenchida) e `PLANILHA DE CUSTO -.xlsx` (itens separados nas duas abas, linhas ampliadas dentro da tabela). O usuário preenche o markup. Se o CÁLCULO lotar, gere outra cópia numerada; não acrescente abas ou redesenhe o modelo.
- Orçamentos a partir de foto são estimativas identificadas como tal. Guarde as medidas inferidas, a fonte e a divergência com o peso da imagem; não apresente esses valores como desenho técnico validado.
- Em estimativas por foto, nomeie cada linha de custo pela peça física, material e medida (por exemplo, `TUBO QUADRADO 20X20X1,2MM - TRAVESSA - 500MM` e `PSAI TESTEIRA 500X220X2MM`). Não invente uma chapa espessa como lastro sem desenho ou autorização específica; no REHAU de 10 rolos, a base é tubular com fechamento PSAI.

## Antes de dizer que terminou

Informe quais testes e exemplos reais foram conferidos, o que continua pendente e o caminho dos artefatos. Se mudar parser, preço, peso ou exportação, atualize o teste e a linha correspondente do registro de regressões. O estado conhecido em 16/10/2026 é **63 testes aprovados**, com pendências históricas descritas em `REGRESSOES.md` e `VALIDACAO.md`.
