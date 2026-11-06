# Leitores por formato

| Módulo | Responsabilidade |
|---|---|
| `common.py` | Normalização, unidades e identificação de medidas do material comercial |
| `cad.py`, `cad_part_number.py`, `cad_grids.py` | Listas CAD por texto e por células, incluindo número de peça, descrições quebradas e grades de componentes |
| `selection.py` | Seleção por rótulos explícitos; nomes técnicos como PARTES não são arte |
| `technical.py` | Grades técnicas ordenadas, grade de 14 colunas, quadro compacto e alternativa textual |
| `scanned.py` | OCR local Windows e listas digitalizadas; imagens temporárias continuam em `data/` |
| `rise_text.py` | Lista RISE textual com grupos e códigos de componentes |
| `outpromo.py` | Lista de sete colunas e vínculos com detalhes de comunicação |
| `router.py` | Resultado identificado e precedência das grades técnicas; eventos de leitura |

O leitor SCORE continua no módulo existente `score_package.py`. A seleção do
produto principal, expansão de conjuntos, espelhamento e conferência de massa
continuam em `reader_v3.py`; os scripts existentes ainda podem importar os nomes
públicos desse arquivo. Esta etapa não reescreve a montagem do produto.

## Ao corrigir ou incluir um formato

1. Reproduza com um arquivo real da mesma variante e identifique seu cabeçalho e
   sua estrutura de células. Não escolha por nome do cliente ou por palavra solta.
2. Corrija o leitor específico. Se mudar a precedência no `router.py`, teste também
   a grade vizinha que compartilha nomes de colunas. Grade completa e quadro
   compacto precisam continuar distintos; grades múltiplas não podem se fundir.
3. Compare os valores com o desenho. Acrescente o contrato verificado ao teste da
   família e registre a mudança em `REGRESSOES.md`.
4. Execute `verificar_regressoes.bat`. As referências completas em
   `regression_baselines/` detectam campos alterados fora do contrato específico.
   Mudança esperada deve ser justificada contra o PDF antes de revisar a referência.

## Evidência de leitura

`reading_report` acompanha a importação e é guardado junto com os materiais.
`recognized` significa que uma lista foi lida; não garante que suas linhas tenham
sido somadas ao orçamento. `selected` identifica a lista usada como principal
(incluindo páginas de continuação no SCORE). `unresolved` e `error` sinalizam
composição desconhecida e falha de leitura. Cada evento contém formato, motivo,
linhas e origem. As pendências existentes continuam responsáveis por impedir uma
interpretação incerta de parecer aprovada.

O relatório descreve a **última importação**, não substitui o histórico de edições
manuais ou a conferência posterior da IA. Para projetos anteriores sem relatório,
o aplicativo informa a ausência; não reimporta nem inventa evidência retroativa.


Ao reconhecer uma tabela nova, preservar também a seleção de variante: em pasta
ambígua com leitor CAD já suportado, uma grade nova maior não substitui
silenciosamente o produto escolhido. Raiz única comprovada por referências
continua prevalecendo. Listas de detalhe de um novo formato em outras páginas do
mesmo PDF permanecem como evidência pendente até o conjunto dono e os fatores
serem conhecidos; não se somam às quantidades da lista principal.
