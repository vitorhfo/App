# Referências de comportamento da leitura

Capturadas em 06/11/2026 **antes** da separação do `reader_v3.py` em módulos.
A amostra digitalizada foi capturada executando o código anterior guardado no Git,
com os mesmos PDFs, após a primeira rodada de testes detectar uma dependência
ausente no módulo OCR. Não são uma nova aprovação técnica de cotas, pesos ou preços. As pendências do
registro de regressões e da validação histórica continuam valendo.

| Amostra | Cobertura | Linhas registradas |
|---|---|---:|
| `veja.json` | Pacote CAD com desenhos filhos e cortes | 44 |
| `reckitt.json` | Hierarquia CAD de quatro módulos, referência digitalizada na mesma pasta | 202 |
| `outpromo.json` | Lista de sete colunas e detalhes de comunicação | 34 |
| `alpa.json` | Grade técnica de 14 colunas, células vazias e componentes espelhados | 28 |
| `docile.json` | Grade RISE com desenho antes da descrição e hierarquia | 131 |
| `score.json` | Pacote SCORE, lista continuada e cortes de tubos | 74 |
| `scanned_reckitt.json` | PDF RISE isolado com lista digitalizada nas páginas 5–6 | 66 |

Cada JSON contém o caminho relativo da pasta, SHA256 dos PDFs e todos os campos
produzidos para cada item, além dos pesos/áreas de referência. O comparador
distingue leitura diferente, amostra ausente, amostra modificada e erro de execução.
Nenhum desses estados passa pela verificação. A ordem das linhas também é protegida.

Os testes específicos de cada família continuam responsáveis pelos valores
conferidos no desenho. A comparação completa detecta mudanças fora desses pontos;
ela não substitui a conferência humana. Não copie automaticamente o resultado de
uma versão nova sobre os arquivos esperados. Uma mudança intencional exige revisar
os campos diferentes contra o PDF e registrar a justificativa em `REGRESSOES.md`.

Para gerar um relatório sem alterar os orçamentos salvos:

```powershell
py -3 reading_regression.py --output data/audits/comparacao_leituras.json
```

Para conferir apenas uma família, acrescente `--case alpa` (pode repetir `--case`).
O comparador completo também faz parte de `verificar_regressoes.bat` por meio de
`test_reading_regression.py`. Ausência de amostra não é tratada como teste pulado.
