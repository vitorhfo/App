# Validação da separação dos leitores — 06/11/2026

## Mudanças entregues

1. Leitores separados em `reader_profiles/`, conforme o formato da lista ou desenho.
   A precedência das grades técnicas ficou no `router.py`; a composição do produto
   permanece em `reader_v3.py`, com as entradas públicas preservadas.
2. Referências completas de comportamento para sete amostras reais, incluindo
   SHA256 dos PDFs e todos os campos de cada item. Elas preservam o comportamento
   anterior e não aprovam automaticamente cotas ou pesos ainda pendentes.
3. Comparação das amostras incorporada à suíte completa. PDF ausente, alterado,
   erro de leitura e campo diferente são resultados distintos que fazem a
   verificação falhar. Não existe atualização automática do resultado esperado.
4. Registro de formato, motivo, linhas e PDF/página, com distinção entre listas
   reconhecidas, usadas como principais e composições pendentes. O aplicativo
   mostra o registro em **Como o projeto foi lido**, na tela de materiais.
5. Teste do caminho PDF → banco isolado → correção manual → reimportação → XLSX,
   além da geração e conferência dos dois modelos da empresa.

## Amostras protegidas

| Amostra | Linhas | Contrato de leitura |
|---|---:|---|
| VEJA PA00000250 | 44 | CAD com peças filhas e cortes |
| ILHA CASH RECKITT completa | 202 | Raiz e quatro módulos, com referência digitalizada na mesma pasta |
| OUTPROMO OP01 | 34 | Lista de sete colunas e detalhes |
| ALPA BASICO 5x5 | 28 | Grade de 14 colunas, células vazias e espelhamento |
| DOCILE RDS007 | 131 | Código de desenho antes da descrição e hierarquia |
| SCORE BRAHMA | 74 | Lista continuada, hierarquia e cortes; evidência nas páginas 36–37 |
| RECKITT digitalizado isolado | 66 | Lista de produção recuperada nas páginas 5–6 |
| **Total** | **579** | Campos completos de cada registro, pesos e áreas de referência |

As primeiras seis referências foram capturadas antes de mover as funções. A
sétima foi obtida executando o código anterior guardado no Git contra a mesma
amostra real, após o teste existente revelar uma dependência ausente no módulo
OCR separado. Essa dependência foi corrigida; o teste do digitalizado voltou a
passar com os 66 registros esperados.

## Conferência do fluxo e das planilhas

O teste `test_reading_pipeline.py` importa o ALPA 5x5 em banco isolado, muda a
largura do TAG para **71 mm apenas para teste**, reimporta, verifica a preservação
da edição e compara medidas, quantidades e pesos das outras peças. O XLSX gerado
é aberto pelo teste para comparar as colunas com os materiais do aplicativo.
Também se confere a entrada dos modelos: subconjuntos fora do custo e PSAI em
comprados. A largura de teste não é uma medida aprovada para um orçamento real.

Os modelos nativos foram preenchidos pelo LibreOffice instalado e lidos pelo
verificador existente: um CÁLCULO com as oito abas originais e apenas entradas de
`Total` alteradas; custo com duas abas, fórmulas, área de impressão e oito linhas
de comprados conferidas, sem erro novo de célula. Os totais parciais de custo
conferiram com o aplicativo. A abertura visual no Microsoft Excel não foi
repetida nesta rodada.

A comparação do verificador foi ajustada para aceitar ruído numérico de
recálculo de até 1e-12 absoluto/relativo, mantendo o mesmo tipo de célula. Duas
células de Alumínio diferiram somente nos últimos bits. Testes adicionais
continuam rejeitando mudanças reais de número, texto e células ausentes.

Artefatos locais da conferência: `data/audits/reader_profiles_export_28cc64c55c/`.
O arquivo `result.json` registra os caminhos do banco e das planilhas de teste.
O relatório comparativo inicial das seis amostras está em
`data/audits/reading_profiles_comparison_20261106.json`; a sétima é protegida
também pela suíte completa.

## Execução final

Comando: `py -3 -u -m unittest discover -p 'test_*.py' -q`.

Resultado observado: **227 testes aprovados, sem falhas**, em 477,585 segundos.
A comparação integral das sete amostras (579 registros) passou, assim como os
contratos anteriores, a reimportação com edição manual e os testes do verificador
dos modelos. A sintaxe do JavaScript e a verificação de diferenças do Git também
foram conferidas.

## Limites preservados

- Pendências técnicas e diferenças históricas de peso/preço continuam abertas,
  conforme `REGRESSOES.md`, `MAPA_FONTES.md` e `VALIDACAO.md`.
- O registro da leitura é da última importação; não descreve edições posteriores
  ou a revisão da IA. Projetos antigos informam a ausência desse registro.
- Orçamentos existentes não foram reimportados ou migrados nesta entrega. As
  verificações usaram bancos isolados e leram as fontes/modelos sem os alterar.
- A suíte ainda emite avisos já existentes de conexões SQLite não fechadas;
  essa limpeza de recursos permanece fora da separação dos formatos.
- O processo do aplicativo precisa ser reiniciado para carregar o código novo.

Para futuras correções, seguir `reader_profiles/README.md` e atualizar a amostra,
o teste específico e o registro de regressões correspondente.
