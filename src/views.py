"""Views de métricas: a definição única de cada métrica.

Chat, abas de análise e notebook leem estas views. Nenhum outro lugar do projeto recalcula
faturamento, ticket, desconto ou comparação com o ano anterior. A definição de negócio de
cada view fica em COMMENT ON VIEW e a de cada métrica na tabela `metricas_definicao`
(que alimenta descrever_dados, o glossário e o README).

Convenções:
- Só `fato_transacoes` e dimensões: nunca `raw_*` nem `fato_ajustes`.
- Descontos viram valores positivos (US$ concedidos): desconto_total = -(RETAIL + COUPON + MATCH).
- Percentuais saem em 0-100.
- `periodo` é 'atual' ou 'base'; linhas fora das duas janelas só existem em vw_vendas_item
  (periodo nulo). As views agregadas usam apenas as duas janelas.

Uso: python -m src.views   (recria as views no banco existente)
"""

from pathlib import Path

import duckdb

from src.config import CFG, RAIZ

# (nome, descrição, SQL com {parametros}). A ordem respeita as dependências.
VIEWS = [
    ("vw_janela",
     "Uma linha com as semanas, dias e datas da janela atual (últimas N semanas completas) e da base do "
     "ano anterior (mesmas semanas menos 52). A janela termina na última WEEK_NO com 7 dias.",
     """
CREATE OR REPLACE VIEW vw_janela AS
WITH fim AS (
    SELECT MAX(WEEK_NO) AS semana_fim_atual FROM dim_data
    WHERE semana_completa AND WEEK_NO IS NOT NULL),
j AS (
    SELECT semana_fim_atual - {semanas} + 1 AS semana_ini_atual,
           semana_fim_atual,
           semana_fim_atual - {semanas} + 1 - {offset} AS semana_ini_base,
           semana_fim_atual - {offset} AS semana_fim_base,
           {offset} AS offset_semanas, {semanas} AS semanas,
           {ativo} AS cliente_ativo_semanas,
           semana_fim_atual - 3 AS semana_ini_ultimo_mes,
           semana_fim_atual - 12 AS semana_ini_ultimo_trimestre
    FROM fim)
SELECT j.*,
       MIN(d.data_id) FILTER (WHERE d.WEEK_NO BETWEEN j.semana_ini_atual AND j.semana_fim_atual) AS dia_ini_atual,
       MAX(d.data_id) FILTER (WHERE d.WEEK_NO BETWEEN j.semana_ini_atual AND j.semana_fim_atual) AS dia_fim_atual,
       MIN(d.data_id) FILTER (WHERE d.WEEK_NO BETWEEN j.semana_ini_base AND j.semana_fim_base) AS dia_ini_base,
       MAX(d.data_id) FILTER (WHERE d.WEEK_NO BETWEEN j.semana_ini_base AND j.semana_fim_base) AS dia_fim_base,
       MIN(d.data) FILTER (WHERE d.WEEK_NO BETWEEN j.semana_ini_atual AND j.semana_fim_atual) AS data_ini_atual,
       MAX(d.data) FILTER (WHERE d.WEEK_NO BETWEEN j.semana_ini_atual AND j.semana_fim_atual) AS data_fim_atual,
       MIN(d.data) FILTER (WHERE d.WEEK_NO BETWEEN j.semana_ini_base AND j.semana_fim_base) AS data_ini_base,
       MAX(d.data) FILTER (WHERE d.WEEK_NO BETWEEN j.semana_ini_base AND j.semana_fim_base) AS data_fim_base,
       MAX(d.WEEK_NO) AS semana_max_base,
       MAX(d.data) AS data_max_base
FROM j CROSS JOIN dim_data d
GROUP BY ALL
"""),

    ("vw_vendas_item",
     "Uma linha por item de cesta de mercadoria, com a data, o produto, o período (atual/base), a semana "
     "alinhada (base = WEEK_NO + 52) e os valores. Único lugar onde desconto e valor bruto são calculados. "
     "Linhas fora das duas janelas têm periodo nulo.",
     """
CREATE OR REPLACE VIEW vw_vendas_item AS
SELECT f.household_key, f.BASKET_ID, f.STORE_ID, f.PRODUCT_ID, f.data_id, d.data, d.WEEK_NO,
       CASE WHEN d.WEEK_NO BETWEEN j.semana_ini_atual AND j.semana_fim_atual THEN 'atual'
            WHEN d.WEEK_NO BETWEEN j.semana_ini_base AND j.semana_fim_base THEN 'base' END AS periodo,
       CASE WHEN d.WEEK_NO BETWEEN j.semana_ini_atual AND j.semana_fim_atual THEN d.WEEK_NO
            WHEN d.WEEK_NO BETWEEN j.semana_ini_base AND j.semana_fim_base THEN d.WEEK_NO + j.offset_semanas
       END AS semana_alinhada,
       p.DEPARTMENT, p.COMMODITY_DESC, p.SUB_COMMODITY_DESC, p.BRAND, p.MANUFACTURER,
       f.QUANTITY AS quantidade,
       f.SALES_VALUE AS faturamento,
       -f.RETAIL_DISC AS desconto_loja,
       -(f.COUPON_DISC + f.COUPON_MATCH_DISC) AS desconto_cupom,
       -(f.RETAIL_DISC + f.COUPON_DISC + f.COUPON_MATCH_DISC) AS desconto_total,
       f.SALES_VALUE - (f.RETAIL_DISC + f.COUPON_DISC + f.COUPON_MATCH_DISC) AS valor_bruto
FROM fato_transacoes f
JOIN dim_data d ON d.data_id = f.data_id
LEFT JOIN dim_produto p ON p.PRODUCT_ID = f.PRODUCT_ID
CROSS JOIN vw_janela j
"""),

    ("vw_metricas_cesta",
     "Uma linha por cesta (BASKET_ID) dentro das duas janelas: faturamento, itens, desconto e valor bruto. "
     "Uma cesta pertence a uma loja, um cliente e um dia.",
     """
CREATE OR REPLACE VIEW vw_metricas_cesta AS
SELECT BASKET_ID, ANY_VALUE(household_key) AS household_key, ANY_VALUE(STORE_ID) AS STORE_ID,
       MIN(data) AS data, MIN(WEEK_NO) AS WEEK_NO, periodo, semana_alinhada,
       SUM(faturamento) AS faturamento, SUM(quantidade) AS itens, COUNT(*) AS linhas,
       SUM(desconto_total) AS desconto_total, SUM(valor_bruto) AS valor_bruto
FROM vw_vendas_item
WHERE periodo IS NOT NULL
GROUP BY BASKET_ID, periodo, semana_alinhada
"""),

    ("vw_metricas_loja_semana",
     "Uma linha por loja, período e semana alinhada: faturamento, cestas, clientes, ticket médio, itens por "
     "cesta e % de desconto. amostra_pequena marca lojas com poucas cestas na janela (números instáveis). "
     "Cestas e faturamento somam entre semanas; clientes, não.",
     """
CREATE OR REPLACE VIEW vw_metricas_loja_semana AS
WITH s AS (
    SELECT STORE_ID, periodo, semana_alinhada,
           SUM(faturamento) AS faturamento, COUNT(*) AS cestas, SUM(itens) AS itens,
           COUNT(DISTINCT household_key) AS clientes,
           SUM(desconto_total) AS desconto_total, SUM(valor_bruto) AS valor_bruto
    FROM vw_metricas_cesta GROUP BY ALL)
SELECT s.*,
       CAST(faturamento AS DOUBLE) / NULLIF(cestas, 0) AS ticket_medio,
       CAST(itens AS DOUBLE) / NULLIF(cestas, 0) AS itens_por_cesta,
       100.0 * CAST(desconto_total AS DOUBLE) / NULLIF(CAST(valor_bruto AS DOUBLE), 0) AS pct_desconto,
       SUM(cestas) OVER (PARTITION BY STORE_ID, periodo) < {minimo_cestas} AS amostra_pequena
FROM s
"""),

    ("vw_metricas_loja_depto_semana",
     "Uma linha por loja, departamento, commodity, marca (Private/National), período e semana alinhada. "
     "cestas_com_compra e clientes são distintos dentro do grão e não somam entre commodities.",
     """
CREATE OR REPLACE VIEW vw_metricas_loja_depto_semana AS
SELECT STORE_ID, DEPARTMENT, COMMODITY_DESC, BRAND, periodo, semana_alinhada,
       SUM(faturamento) AS faturamento, SUM(quantidade) AS quantidade,
       COUNT(DISTINCT BASKET_ID) AS cestas_com_compra, COUNT(DISTINCT household_key) AS clientes,
       SUM(desconto_total) AS desconto_total, SUM(desconto_cupom) AS desconto_cupom,
       SUM(valor_bruto) AS valor_bruto
FROM vw_vendas_item
WHERE periodo IS NOT NULL
GROUP BY ALL
"""),

    ("vw_metricas_cliente",
     "Uma linha por household e período: recência (dias até o fim do período), frequência (cestas), valor "
     "(faturamento), ticket, % de desconto e cliente_ativo (>= 1 compra nas últimas N semanas do período). "
     "Base do RFM, CLV, churn e teste de desconto.",
     """
CREATE OR REPLACE VIEW vw_metricas_cliente AS
WITH c AS (
    SELECT household_key, periodo,
           SUM(faturamento) AS valor, COUNT(*) AS frequencia, SUM(itens) AS itens,
           MAX(data) AS ultima_compra, MAX(WEEK_NO) AS ultima_semana,
           COUNT(DISTINCT semana_alinhada) AS semanas_com_compra,
           SUM(desconto_total) AS desconto_total, SUM(valor_bruto) AS valor_bruto
    FROM vw_metricas_cesta GROUP BY ALL)
SELECT c.household_key, c.periodo, c.valor, c.frequencia, c.itens, c.ultima_compra, c.semanas_com_compra,
       date_diff('day', c.ultima_compra, CASE c.periodo WHEN 'atual' THEN j.data_fim_atual ELSE j.data_fim_base END)
           AS recencia_dias,
       c.ultima_semana >= (CASE c.periodo WHEN 'atual' THEN j.semana_fim_atual ELSE j.semana_fim_base END)
           - j.cliente_ativo_semanas + 1 AS cliente_ativo,
       CAST(c.valor AS DOUBLE) / NULLIF(c.frequencia, 0) AS ticket_medio,
       c.desconto_total, c.valor_bruto,
       100.0 * CAST(c.desconto_total AS DOUBLE) / NULLIF(CAST(c.valor_bruto AS DOUBLE), 0) AS pct_desconto,
       h.tem_demografia
FROM c CROSS JOIN vw_janela j
LEFT JOIN dim_household h ON h.household_key = c.household_key
"""),

    ("vw_cliente_semana",
     "Uma linha por household e semana (WEEK_NO) com compra, desde a primeira semana até a última completa: "
     "cestas, faturamento, itens, desconto, valor bruto e a data da última compra na semana. Definição única do "
     "histórico que alimenta coorte, CLV e churn (inclusive o RFM de qualquer janela); as semanas não vêm "
     "limitadas às janelas atual e base.",
     """
CREATE OR REPLACE VIEW vw_cliente_semana AS
SELECT i.household_key, i.WEEK_NO,
       COUNT(DISTINCT i.BASKET_ID) AS cestas, SUM(i.faturamento) AS faturamento, SUM(i.quantidade) AS itens,
       SUM(i.desconto_total) AS desconto_total, SUM(i.valor_bruto) AS valor_bruto, MAX(i.data) AS ultima_data
FROM vw_vendas_item i CROSS JOIN vw_janela j
WHERE i.WEEK_NO <= j.semana_fim_atual
GROUP BY i.household_key, i.WEEK_NO
"""),

    ("vw_lojas_like_for_like",
     "Lojas com pelo menos uma cesta nos dois períodos (atual e base): o conjunto usado em toda comparação "
     "com o ano anterior.",
     """
CREATE OR REPLACE VIEW vw_lojas_like_for_like AS
SELECT STORE_ID FROM vw_metricas_cesta
GROUP BY STORE_ID
HAVING COUNT(*) FILTER (WHERE periodo = 'atual') > 0 AND COUNT(*) FILTER (WHERE periodo = 'base') > 0
"""),

    ("vw_yoy_loja",
     "Uma linha por loja like-for-like: faturamento, cestas, clientes e ticket na janela atual contra a base "
     "do ano anterior, com a variação percentual. amostra_pequena vale se qualquer período tem poucas cestas.",
     """
CREATE OR REPLACE VIEW vw_yoy_loja AS
WITH s AS (
    SELECT STORE_ID, periodo, SUM(faturamento) AS f, COUNT(*) AS c, SUM(itens) AS i,
           COUNT(DISTINCT household_key) AS cl
    FROM vw_metricas_cesta WHERE STORE_ID IN (SELECT STORE_ID FROM vw_lojas_like_for_like)
    GROUP BY ALL),
p AS (
    SELECT STORE_ID,
           SUM(f) FILTER (WHERE periodo = 'atual') AS faturamento_atual,
           SUM(f) FILTER (WHERE periodo = 'base') AS faturamento_base,
           SUM(c) FILTER (WHERE periodo = 'atual') AS cestas_atual,
           SUM(c) FILTER (WHERE periodo = 'base') AS cestas_base,
           SUM(cl) FILTER (WHERE periodo = 'atual') AS clientes_atual,
           SUM(cl) FILTER (WHERE periodo = 'base') AS clientes_base,
           SUM(i) FILTER (WHERE periodo = 'atual') AS itens_atual,
           SUM(i) FILTER (WHERE periodo = 'base') AS itens_base
    FROM s GROUP BY STORE_ID)
SELECT STORE_ID, faturamento_atual, faturamento_base,
       100.0 * (CAST(faturamento_atual AS DOUBLE) / NULLIF(CAST(faturamento_base AS DOUBLE), 0) - 1) AS var_faturamento_pct,
       cestas_atual, cestas_base,
       100.0 * (CAST(cestas_atual AS DOUBLE) / NULLIF(cestas_base, 0) - 1) AS var_cestas_pct,
       clientes_atual, clientes_base,
       100.0 * (CAST(clientes_atual AS DOUBLE) / NULLIF(clientes_base, 0) - 1) AS var_clientes_pct,
       CAST(faturamento_atual AS DOUBLE) / NULLIF(cestas_atual, 0) AS ticket_atual,
       CAST(faturamento_base AS DOUBLE) / NULLIF(cestas_base, 0) AS ticket_base,
       100.0 * ((CAST(faturamento_atual AS DOUBLE) / NULLIF(cestas_atual, 0))
                / NULLIF(CAST(faturamento_base AS DOUBLE) / NULLIF(cestas_base, 0), 0) - 1) AS var_ticket_pct,
       (cestas_atual < {minimo_cestas} OR cestas_base < {minimo_cestas}) AS amostra_pequena
FROM p
"""),

    ("vw_yoy_resumo",
     "Uma linha com o total like-for-like (atual contra base) e a árvore de vendas: variação do faturamento "
     "= clientes x idas por cliente (cestas/cliente) x ticket médio. Traz também quantas lojas ficaram de fora "
     "e quanto do faturamento elas representam.",
     """
CREATE OR REPLACE VIEW vw_yoy_resumo AS
WITH lfl AS (SELECT STORE_ID FROM vw_lojas_like_for_like),
c AS (
    SELECT periodo, SUM(faturamento) AS f, COUNT(*) AS cestas, COUNT(DISTINCT household_key) AS clientes
    FROM vw_metricas_cesta WHERE STORE_ID IN (SELECT STORE_ID FROM lfl) GROUP BY periodo),
tot AS (
    SELECT SUM(faturamento) FILTER (WHERE periodo = 'atual') AS f_atual_todas,
           SUM(faturamento) FILTER (WHERE periodo = 'base') AS f_base_todas,
           COUNT(DISTINCT STORE_ID) FILTER (WHERE periodo = 'atual') AS lojas_atual,
           COUNT(DISTINCT STORE_ID) FILTER (WHERE periodo = 'base') AS lojas_base
    FROM vw_metricas_cesta),
hh AS (SELECT COUNT(*) AS clientes_nos_dois_periodos FROM (
           SELECT household_key FROM vw_metricas_cesta GROUP BY 1 HAVING COUNT(DISTINCT periodo) = 2)),
a AS (SELECT * FROM c WHERE periodo = 'atual'),
b AS (SELECT * FROM c WHERE periodo = 'base'),
r AS (
    SELECT j.semana_ini_atual, j.semana_fim_atual, j.semana_ini_base, j.semana_fim_base,
           a.f AS faturamento_atual, b.f AS faturamento_base,
           a.cestas AS cestas_atual, b.cestas AS cestas_base,
           a.clientes AS clientes_atual, b.clientes AS clientes_base,
           CAST(a.cestas AS DOUBLE) / NULLIF(a.clientes, 0) AS idas_por_cliente_atual,
           CAST(b.cestas AS DOUBLE) / NULLIF(b.clientes, 0) AS idas_por_cliente_base,
           CAST(a.f AS DOUBLE) / NULLIF(a.cestas, 0) AS ticket_atual,
           CAST(b.f AS DOUBLE) / NULLIF(b.cestas, 0) AS ticket_base,
           (SELECT COUNT(*) FROM lfl) AS lojas_like_for_like,
           tot.lojas_atual, tot.lojas_base,
           tot.lojas_atual - (SELECT COUNT(*) FROM lfl) AS lojas_so_atual,
           tot.lojas_base - (SELECT COUNT(*) FROM lfl) AS lojas_so_base,
           100.0 * CAST(a.f AS DOUBLE) / NULLIF(CAST(tot.f_atual_todas AS DOUBLE), 0) AS pct_vendas_atual_em_lfl,
           100.0 * CAST(b.f AS DOUBLE) / NULLIF(CAST(tot.f_base_todas AS DOUBLE), 0) AS pct_vendas_base_em_lfl,
           hh.clientes_nos_dois_periodos,
           (SELECT COUNT(*) FROM vw_yoy_loja WHERE amostra_pequena) AS lojas_lfl_amostra_pequena
    FROM vw_janela j CROSS JOIN a CROSS JOIN b CROSS JOIN tot CROSS JOIN hh)
SELECT r.*,
       100.0 * (CAST(faturamento_atual AS DOUBLE) / NULLIF(CAST(faturamento_base AS DOUBLE), 0) - 1) AS var_faturamento_pct,
       100.0 * (CAST(clientes_atual AS DOUBLE) / NULLIF(clientes_base, 0) - 1) AS var_clientes_pct,
       100.0 * (idas_por_cliente_atual / NULLIF(idas_por_cliente_base, 0) - 1) AS var_idas_por_cliente_pct,
       100.0 * (ticket_atual / NULLIF(ticket_base, 0) - 1) AS var_ticket_pct
FROM r
"""),

    ("vw_yoy_categoria",
     "Uma linha por departamento, commodity e marca (Private, National ou TODAS), só nas lojas like-for-like: "
     "faturamento, clientes e penetração (% dos clientes das lojas like-for-like que compraram a categoria) "
     "na janela atual contra a base.",
     """
CREATE OR REPLACE VIEW vw_yoy_categoria AS
WITH it AS (
    SELECT * FROM vw_vendas_item
    WHERE periodo IS NOT NULL AND STORE_ID IN (SELECT STORE_ID FROM vw_lojas_like_for_like)),
ativos AS (SELECT periodo, COUNT(DISTINCT household_key) AS clientes_ativos FROM it GROUP BY periodo),
cat AS (
    SELECT DEPARTMENT, COMMODITY_DESC,
           CASE WHEN GROUPING(BRAND) = 1 THEN 'TODAS' ELSE BRAND END AS marca, periodo,
           SUM(faturamento) AS f, SUM(quantidade) AS q, COUNT(DISTINCT household_key) AS cl
    FROM it
    GROUP BY GROUPING SETS ((DEPARTMENT, COMMODITY_DESC, BRAND, periodo), (DEPARTMENT, COMMODITY_DESC, periodo))),
p AS (
    SELECT DEPARTMENT, COMMODITY_DESC, marca,
           SUM(f) FILTER (WHERE cat.periodo = 'atual') AS faturamento_atual,
           SUM(f) FILTER (WHERE cat.periodo = 'base') AS faturamento_base,
           SUM(q) FILTER (WHERE cat.periodo = 'atual') AS quantidade_atual,
           SUM(q) FILTER (WHERE cat.periodo = 'base') AS quantidade_base,
           SUM(cl) FILTER (WHERE cat.periodo = 'atual') AS clientes_atual,
           SUM(cl) FILTER (WHERE cat.periodo = 'base') AS clientes_base
    FROM cat GROUP BY DEPARTMENT, COMMODITY_DESC, marca)
SELECT p.DEPARTMENT, p.COMMODITY_DESC, p.marca,
       COALESCE(faturamento_atual, 0) AS faturamento_atual, COALESCE(faturamento_base, 0) AS faturamento_base,
       100.0 * (CAST(faturamento_atual AS DOUBLE) / NULLIF(CAST(faturamento_base AS DOUBLE), 0) - 1) AS var_faturamento_pct,
       COALESCE(quantidade_atual, 0) AS quantidade_atual, COALESCE(quantidade_base, 0) AS quantidade_base,
       COALESCE(clientes_atual, 0) AS clientes_atual, COALESCE(clientes_base, 0) AS clientes_base,
       100.0 * COALESCE(clientes_atual, 0) / NULLIF((SELECT clientes_ativos FROM ativos WHERE periodo = 'atual'), 0)
           AS penetracao_atual,
       100.0 * COALESCE(clientes_base, 0) / NULLIF((SELECT clientes_ativos FROM ativos WHERE periodo = 'base'), 0)
           AS penetracao_base
FROM p
"""),

    ("vw_contexto_periodo",
     "Uma linha por período (atual e base) com o que pode inflar ou deprimir a base de comparação: campanhas "
     "ativas, households-alvo, resgates de cupom, % de linhas produto-loja em display e em mailer e % de "
     "desconto. Use junto com qualquer variação contra o ano anterior.",
     """
CREATE OR REPLACE VIEW vw_contexto_periodo AS
WITH per AS (
    SELECT 'atual' AS periodo, semana_ini_atual AS semana_ini, semana_fim_atual AS semana_fim,
           dia_ini_atual AS dia_ini, dia_fim_atual AS dia_fim, data_ini_atual AS data_ini, data_fim_atual AS data_fim
    FROM vw_janela
    UNION ALL
    SELECT 'base', semana_ini_base, semana_fim_base, dia_ini_base, dia_fim_base, data_ini_base, data_fim_base
    FROM vw_janela)
SELECT p.periodo, p.semana_ini, p.semana_fim, p.data_ini, p.data_fim,
       (SELECT COUNT(*) FROM campaign_desc c WHERE c.START_DAY <= p.dia_fim AND c.END_DAY >= p.dia_ini)
           AS campanhas_ativas,
       (SELECT COUNT(DISTINCT t.household_key) FROM campaign_table t
        JOIN campaign_desc c ON c.CAMPAIGN = t.CAMPAIGN
        WHERE c.START_DAY <= p.dia_fim AND c.END_DAY >= p.dia_ini) AS households_alvo_campanha,
       (SELECT COUNT(*) FROM coupon_redempt r WHERE r.DAY BETWEEN p.dia_ini AND p.dia_fim) AS resgates_cupom,
       (SELECT COUNT(DISTINCT r.household_key) FROM coupon_redempt r
        WHERE r.DAY BETWEEN p.dia_ini AND p.dia_fim) AS households_que_resgataram,
       (SELECT COUNT(DISTINCT z.WEEK_NO) FROM causal_semana_loja z
        WHERE z.WEEK_NO BETWEEN p.semana_ini AND p.semana_fim) AS semanas_com_dado_causal,
       (SELECT 100.0 * SUM(z.linhas_display) / NULLIF(SUM(z.linhas), 0) FROM causal_semana_loja z
        WHERE z.WEEK_NO BETWEEN p.semana_ini AND p.semana_fim) AS pct_linhas_display,
       (SELECT 100.0 * SUM(z.linhas_mailer) / NULLIF(SUM(z.linhas), 0) FROM causal_semana_loja z
        WHERE z.WEEK_NO BETWEEN p.semana_ini AND p.semana_fim) AS pct_linhas_mailer,
       (SELECT 100.0 * CAST(SUM(i.desconto_total) AS DOUBLE) / NULLIF(CAST(SUM(i.valor_bruto) AS DOUBLE), 0)
        FROM vw_vendas_item i WHERE i.periodo = p.periodo) AS pct_desconto
FROM per p
"""),
]

# Views caras guardam o resultado numa tabela `_mat_*` (medido antes: vw_yoy_categoria 9,6 s,
# vw_metricas_cliente 2,8 s, vw_yoy_loja/resumo 2 a 5 s por recalcular a agregação de cestas).
# O SQL continua único: a view é criada com a definição e só depois redirecionada.
MATERIALIZAR = {"vw_cliente_semana", "vw_metricas_cesta", "vw_yoy_categoria", "vw_metricas_cliente", "vw_yoy_loja", "vw_yoy_resumo"}

# Métricas de negócio: nome, definição, fórmula, view de origem. Alimenta descrever_dados, o glossário e o README.
METRICAS = [
    ("faturamento", "Valor líquido vendido, já depois de cupom e desconto de fidelidade (SALES_VALUE).",
     "SUM(faturamento)", "vw_vendas_item"),
    ("desconto_total", "Dólares concedidos em desconto: loja/fidelidade + cupom + cupom casado. Positivo.",
     "SUM(desconto_total) = -SUM(RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC)", "vw_vendas_item"),
    ("desconto_loja", "Parte do desconto dada pela loja (cartão de fidelidade), RETAIL_DISC.",
     "SUM(desconto_loja)", "vw_vendas_item"),
    ("desconto_cupom", "Parte do desconto vinda de cupom: COUPON_DISC + COUPON_MATCH_DISC.",
     "SUM(desconto_cupom)", "vw_vendas_item"),
    ("valor_bruto", "Valor antes dos descontos: faturamento + desconto total.",
     "SUM(valor_bruto) = SUM(faturamento) + SUM(desconto_total)", "vw_vendas_item"),
    ("pct_desconto", "Desconto como % do valor bruto (0-100).",
     "100 * SUM(desconto_total) / SUM(valor_bruto)", "vw_metricas_loja_semana"),
    ("cestas", "Número de idas à loja com compra: cestas distintas (BASKET_ID).",
     "COUNT(DISTINCT BASKET_ID)", "vw_metricas_cesta"),
    ("itens", "Unidades vendidas (QUANTITY).", "SUM(quantidade)", "vw_vendas_item"),
    ("ticket_medio", "Quanto cada cesta fatura em média.", "SUM(faturamento) / COUNT(DISTINCT BASKET_ID)",
     "vw_metricas_loja_semana"),
    ("itens_por_cesta", "Unidades por cesta.", "SUM(quantidade) / COUNT(DISTINCT BASKET_ID)",
     "vw_metricas_loja_semana"),
    ("clientes", "Households distintos que compraram. Não soma entre semanas, lojas ou categorias.",
     "COUNT(DISTINCT household_key)", "vw_metricas_cesta"),
    ("idas_por_cliente", "Frequência: cestas por cliente no período.",
     "COUNT(DISTINCT BASKET_ID) / COUNT(DISTINCT household_key)", "vw_yoy_resumo"),
    ("cliente_ativo", "Household com pelo menos uma compra nas últimas N semanas do período (N = 8).",
     "coluna cliente_ativo (booleana): última compra dentro das últimas 8 semanas do período", "vw_metricas_cliente"),
    ("recencia_dias", "Dias entre a última compra do household e o último dia do período.",
     "coluna recencia_dias = dias entre a última compra e o último dia do período", "vw_metricas_cliente"),
    ("semanas_com_compra", "Número de semanas (WEEK_NO) em que o household comprou, em todo o histórico.",
     "COUNT(*) de vw_cliente_semana por household_key", "vw_cliente_semana"),
    ("frequencia_cliente", "Número de cestas do household no período.", "COUNT(DISTINCT BASKET_ID)",
     "vw_metricas_cliente"),
    ("valor_cliente", "Faturamento do household no período.", "SUM(faturamento)", "vw_metricas_cliente"),
    ("janela_atual", "As últimas 26 semanas completas de WEEK_NO (termina na última semana com 7 dias).",
     "semana_ini_atual .. semana_fim_atual", "vw_janela"),
    ("base_ano_anterior", "As mesmas semanas um ano antes (WEEK_NO - 52), alinhadas por semana.",
     "semana_ini_base .. semana_fim_base", "vw_janela"),
    ("semana_alinhada", "Semana da janela atual a que cada semana da base corresponde (base + 52).",
     "WEEK_NO (atual) ou WEEK_NO + 52 (base)", "vw_vendas_item"),
    ("like_for_like", "Comparação só entre lojas com pelo menos uma cesta nos dois períodos.",
     "STORE_ID presente em atual e base", "vw_lojas_like_for_like"),
    ("variacao_ano_anterior", "Variação % da janela atual contra a base, nas lojas like-for-like.",
     "100 * (atual / base - 1)", "vw_yoy_resumo"),
    ("arvore_de_vendas", "Faturamento = clientes x idas por cliente x ticket médio; cada fator tem variação própria.",
     "(1 + var_clientes_pct/100) * (1 + var_idas_por_cliente_pct/100) * (1 + var_ticket_pct/100) "
     "= 1 + var_faturamento_pct/100", "vw_yoy_resumo"),
    ("penetracao", "% dos clientes (que compraram algo no período) que compraram a categoria.",
     "colunas penetracao_atual e penetracao_base = 100 * clientes_atual (ou clientes_base) / clientes com "
     "qualquer compra no período", "vw_yoy_categoria"),
    ("marca_propria", "Produtos com BRAND = 'Private'; os demais são 'National'.", "BRAND = 'Private'",
     "vw_yoy_categoria"),
    ("ultimo_mes", "As últimas 4 semanas completas da janela (relativas ao fim dos dados, não a hoje).",
     "semana_ini_ultimo_mes .. semana_fim_atual", "vw_janela"),
    ("ultimo_trimestre", "As últimas 13 semanas completas da janela.",
     "semana_ini_ultimo_trimestre .. semana_fim_atual", "vw_janela"),
    ("amostra_pequena", "Loja com menos cestas na janela do que o mínimo configurado: números instáveis.",
     "coluna amostra_pequena = total de cestas da loja no período < 100", "vw_metricas_loja_semana"),
]


def _lit(texto: str) -> str:
    return "'" + texto.replace("'", "''") + "'"


def criar_views(con, cfg: dict | None = None) -> list[str]:
    """Cria (ou recria) as views, os comentários e a tabela metricas_definicao. Devolve os nomes."""
    cfg = cfg or CFG
    parametros = {
        "semanas": int(cfg["janela"]["semanas_atuais"]),
        "offset": int(cfg["janela"]["offset_ano_anterior"]),
        "ativo": int(cfg["metricas"]["cliente_ativo_semanas"]),
        "minimo_cestas": int(cfg["metricas"]["loja_amostra_minima_cestas"]),
    }
    for nome, descricao, sql in VIEWS:
        con.execute(sql.format(**parametros))
        if nome in MATERIALIZAR:
            # Mesma definição, resultado guardado: a view passa a ler da tabela `_mat_<nome>`.
            con.execute(f"DROP TABLE IF EXISTS _mat_{nome}")
            con.execute(f"CREATE TABLE _mat_{nome} AS SELECT * FROM {nome}")
            con.execute(f"CREATE OR REPLACE VIEW {nome} AS SELECT * FROM _mat_{nome}")
        con.execute(f"COMMENT ON VIEW {nome} IS {_lit(descricao)}")

    con.execute("DROP TABLE IF EXISTS metricas_definicao")
    con.execute("CREATE TABLE metricas_definicao (metrica VARCHAR, definicao VARCHAR, formula VARCHAR, "
                "view_origem VARCHAR)")
    con.executemany("INSERT INTO metricas_definicao VALUES (?, ?, ?, ?)", METRICAS)
    return [v[0] for v in VIEWS]


if __name__ == "__main__":
    caminho = RAIZ / CFG["banco"]["arquivo"]
    con = duckdb.connect(str(caminho))
    criar_views(con)
    print(con.execute("SELECT * FROM vw_janela").df().T.to_string())
    print(con.execute("SELECT * FROM vw_yoy_resumo").df().T.to_string())
    con.close()
