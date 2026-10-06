---
name: consultas-sql
description: Use ao escrever, revisar ou executar consultas SQL sobre a base Dunnhumby deste projeto (views no DuckDB), seja construindo o ETL e as views, seja respondendo perguntas de negócio pontuais com a ferramenta executar_consulta. Cobre métricas de varejo, comparação com o ano anterior e regras de segurança.
---

# Consultas SQL — base Dunnhumby

Fonte das regras: `docs/spec_ferramentas_mcp.md`. Se algo aqui contradisser a spec, vale a spec.

## Antes de escrever qualquer consulta
1. Chame `descrever_dados()`: a lista curta (cerca de 2 mil tokens) mostra views, tabelas, métricas, janela e limitações. Para as colunas de uma view ou a definição de uma métrica, chame `descrever_dados(detalhe="vw_vendas_item")` ou `detalhe="ticket_medio"`. Evite `detalhe="tudo"` (cerca de 6 mil tokens).
2. Escreva a pergunta de negócio em uma frase e qual decisão ela apoia.
3. Defina a granularidade do resultado: por loja, por semana, por household, por departamento?

## Regras
- Use **sempre as views de métricas** (`vw_*`). Nunca recalcule faturamento, ticket médio ou desconto à mão.
- Faturamento = `SALES_VALUE` (já líquido). Descontos servem para decompor, não para recalcular o líquido.
- Ticket médio = faturamento / cestas distintas (`BASKET_ID`). **% de desconto = 100 × soma do desconto / soma do valor bruto**: some antes de dividir, nunca tire média de percentuais.
- "Loja", "unidade", "filial" → `STORE_ID`. "Categoria", "seção" → `DEPARTMENT` / `COMMODITY_DESC`, com `ILIKE '%...%'`.
- "Último mês" e "ano passado" são relativos ao fim dos dados (`vw_janela`), não à data de hoje.
- **Comparação com o ano anterior:** use `vw_yoy_resumo`, `vw_yoy_loja` ou `vw_yoy_categoria` (mesmas semanas, `WEEK_NO - 52`, só lojas presentes nos dois períodos). Diga quantas lojas ficaram de fora.
- Rankings de loja filtram `amostra_pequena = FALSE`; avise quando uma loja citada tem amostra pequena.
- Listagens de registros: `LIMIT 20` (máximo 200). O código aplica o limite; pedir "a base inteira" devolve só as primeiras linhas, com `truncado = true`.
- Só `SELECT` / `WITH`, uma instrução por consulta. O código bloqueia o resto (escrita, vários comandos, leitura de arquivos, tabelas internas). Se a consulta for bloqueada, leia o `erro` e a `sugestao`, corrija e tente de novo; não tente contornar o bloqueio e não diga que "conseguiu" o que foi recusado.
- Tabelas visíveis: `vw_*`, `dim_*`, `fato_transacoes`, `campaign_*`, `coupon*`, `causal_semana_loja`, `metricas_definicao`.
- Use `COUNT(*)` ao contar linhas; `COUNT(coluna)` ignora nulos.
- **Não existe vendedor.** A menor unidade de equipe é a loja. Diga isso em vez de inventar um ranking.

## Ao construir (ETL e views)
- Conte linhas antes e depois de cada JOIN. Se multiplicou, a chave não é única: investigar antes de seguir.
- Confira se `PRODUCT_ID` é único em `product` antes do JOIN.
- Toda view de métrica tem um comentário com a definição de negócio, e cada métrica é definida uma vez (`views.METRICAS`).
- Escreva um teste que compare cada view com um cálculo feito à mão numa amostra.

## Ao responder perguntas com executar_consulta
- Se a pergunta for ambígua (qual loja? qual período?), pergunte antes de consultar.
- Mostre a query usada junto com a resposta.
- Responda em linguagem de negócio, com o número e o contexto (contra o ano anterior, quando fizer sentido).
- Faça sanity check: ticket médio de supermercado na casa de dezenas de dólares (aqui, cerca de US$ 31), não milhares; % de desconto na casa de 15%.
- Para segmentação, CLV, churn ou testes estatísticos, use as ferramentas próprias (skill `analise-estatistica`), não SQL.

## Armadilhas desta base
- `DAY` é inteiro relativo: as views já convertem para data e semana.
- Nem todo household tem demografia (801 de 2.500): use LEFT JOIN.
- Combustível, transações diversas e pseudo-itens de cupom ficam fora das vendas, em camada separada; o relatório de qualidade reconcilia com o bruto.
- As datas reais são arbitrárias: compare por semana alinhada, não por feriado.
