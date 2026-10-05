---
name: consultas-sql
description: Use ao escrever, revisar ou executar consultas SQL sobre a base Dunnhumby deste projeto (views no DuckDB), seja construindo o ETL e as views, seja respondendo perguntas de negócio pontuais com a ferramenta executar_consulta. Cobre métricas de varejo, comparação com o ano anterior e regras de segurança.
---

# Consultas SQL — base Dunnhumby

Fonte das regras: `docs/spec_ferramentas_mcp.md`. Se algo aqui contradisser a spec, vale a spec.

## Antes de escrever qualquer consulta
1. Rode `descrever_dados()` (ou leia as views) para saber qual view e qual métrica usar.
2. Escreva a pergunta de negócio em uma frase e qual decisão ela apoia.
3. Defina a granularidade do resultado: por loja, por semana, por household, por departamento?

## Regras
- Use **sempre as views de métricas** (`vw_*`). Nunca recalcule faturamento, ticket médio ou desconto à mão.
- Faturamento = `SALES_VALUE` (já líquido). Descontos servem para decompor, não para recalcular o líquido.
- Ticket médio = faturamento / cestas distintas (`BASKET_ID`).
- "Loja", "unidade", "filial" → `STORE_ID`. "Categoria", "seção" → `DEPARTMENT` / `COMMODITY_DESC`, com `ILIKE '%...%'`.
- "Último mês" e "ano passado" são relativos à data máxima da base, não à data de hoje.
- **Comparação com o ano anterior:** mesmas semanas (`WEEK_NO - 52`), mesmas lojas presentes nos dois períodos. Diga quantas lojas ficaram de fora.
- Listagens de registros: `LIMIT 20` (máximo 200).
- Só `SELECT` / `WITH`. Uma instrução por consulta.
- Use `COUNT(*)` ao contar linhas; `COUNT(coluna)` ignora nulos.

## Ao construir (ETL e views)
- Conte linhas antes e depois de cada JOIN. Se multiplicou, a chave não é única: investigar antes de seguir.
- Confira se `PRODUCT_ID` é único em `product` antes do JOIN.
- Toda view de métrica tem um comentário com a definição de negócio.
- Escreva um teste que compare cada view com um cálculo feito à mão numa amostra.

## Ao responder perguntas com executar_consulta
- Se a pergunta for ambígua (qual loja? qual período?), pergunte antes de consultar.
- Mostre a query usada junto com a resposta.
- Responda em linguagem de negócio, com o número e o contexto (contra o ano anterior, quando fizer sentido).
- Faça sanity check: ticket médio de supermercado na casa de dezenas de dólares, não milhares.
- Para segmentação, CLV, churn ou testes estatísticos, use as ferramentas próprias, não SQL.

## Armadilhas desta base
- `DAY` é inteiro relativo: precisa da tabela de datas.
- Nem todo household tem demografia: use LEFT JOIN com `hh_demographic`.
- Linhas com valor zero, combustível ou quantidade estranha podem existir: confira o relatório de qualidade.
- As primeiras semanas do painel podem estar incompletas.
