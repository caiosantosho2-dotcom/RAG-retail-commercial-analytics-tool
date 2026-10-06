"""Base sintética mínima, com resultados conhecidos, compartilhada pelos testes das views e do núcleo.

Janela do teste: 2 semanas atuais (9-10), offset de 4 (base = semanas 5-6), cliente ativo = 1 semana,
loja pequena = menos de 2 cestas. Semana s cobre os dias 7*(s-1)+1 .. 7*s; semana 1 = dia 1.
Lojas: 1 em ambos os períodos, 2 só na atual, 3 só na base.
"""

import copy
from pathlib import Path

import duckdb

from src import views
from src.config import CFG

# household, cesta, dia, loja, produto, quantidade, faturamento, retail, coupon, match
LINHAS = [
    (1, 1001, 29, 1, 10, 2, 10.00, -1.00, 0.00, 0.00),   # base, semana 5
    (1, 1001, 29, 1, 11, 1, 4.00, 0.00, 0.00, 0.00),
    (2, 1002, 36, 1, 10, 1, 5.00, 0.00, -0.50, 0.00),    # base, semana 6
    (3, 1003, 30, 3, 10, 1, 6.00, 0.00, 0.00, 0.00),     # base, loja 3
    (1, 2001, 57, 1, 10, 3, 15.00, -3.00, 0.00, 0.00),   # atual, semana 9
    (1, 2002, 64, 1, 11, 2, 8.00, 0.00, 0.00, -1.00),    # atual, semana 10
    (2, 2003, 58, 1, 11, 1, 4.00, 0.00, 0.00, 0.00),     # atual, semana 9
    (3, 2004, 59, 2, 10, 1, 7.00, 0.00, 0.00, 0.00),     # atual, loja 2
    (1, 3001, 1, 1, 10, 1, 99.00, 0.00, 0.00, 0.00),     # fora das janelas (semana 1)
]


def cfg_teste() -> dict:
    cfg = copy.deepcopy(CFG)
    cfg["janela"].update(semanas_atuais=2, offset_ano_anterior=4)
    cfg["metricas"].update(cliente_ativo_semanas=1, loja_amostra_minima_cestas=2)
    return cfg


def montar(c: duckdb.DuckDBPyConnection) -> None:
    """Cria tabelas, views e metadados na conexão (leitura e escrita)."""
    c.execute("""CREATE TABLE dim_data AS
        SELECT d AS data_id, DATE '2016-01-01' + CAST(d - 1 AS INTEGER) AS data,
               CAST((d - 1) // 7 + 1 AS INTEGER) AS WEEK_NO, 7 AS dias_na_semana, TRUE AS semana_completa
        FROM range(1, 71) t(d)""")
    c.execute("""CREATE TABLE fato_transacoes (household_key BIGINT, BASKET_ID BIGINT, data_id INTEGER,
        STORE_ID BIGINT, PRODUCT_ID BIGINT, QUANTITY DOUBLE, SALES_VALUE DECIMAL(18,4), RETAIL_DISC DECIMAL(18,4),
        COUPON_DISC DECIMAL(18,4), COUPON_MATCH_DISC DECIMAL(18,4), hora INTEGER)""")
    c.executemany("INSERT INTO fato_transacoes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)", LINHAS)
    c.execute("""CREATE TABLE dim_produto AS SELECT * FROM (VALUES
        (10, 'GROCERY', 'SOUP', 'SOUP', 'M', 'National', '12 OZ'),
        (11, 'GROCERY', 'MILK', 'MILK', 'M', 'Private', '1 GAL'))
        t(PRODUCT_ID, DEPARTMENT, COMMODITY_DESC, SUB_COMMODITY_DESC, MANUFACTURER, BRAND, CURR_SIZE_OF_PRODUCT)""")
    c.execute("CREATE TABLE dim_household AS SELECT * FROM (VALUES (1, TRUE), (2, FALSE), (3, FALSE)) "
              "t(household_key, tem_demografia)")
    c.execute("CREATE TABLE dim_loja AS SELECT * FROM (VALUES (1), (2), (3)) t(STORE_ID)")
    c.execute("CREATE TABLE campaign_desc AS SELECT * FROM (VALUES (1, 'A', 50, 60), (2, 'B', 100, 110), "
              "(3, 'C', 30, 35)) t(CAMPAIGN, DESCRIPTION, START_DAY, END_DAY)")
    c.execute("CREATE TABLE campaign_table AS SELECT * FROM (VALUES ('A', 1, 1), ('A', 2, 1), ('C', 3, 3)) "
              "t(DESCRIPTION, household_key, CAMPAIGN)")
    c.execute("CREATE TABLE coupon_redempt AS SELECT * FROM (VALUES (1, 58, 111, 1), (3, 31, 111, 3), "
              "(2, 45, 111, 1)) t(household_key, DAY, COUPON_UPC, CAMPAIGN)")
    c.execute("CREATE TABLE causal_semana_loja AS SELECT * FROM (VALUES (9, 1, 10, 2, 1), (10, 1, 10, 0, 0), "
              "(5, 1, 20, 10, 0), (6, 1, 20, 0, 0)) t(WEEK_NO, STORE_ID, linhas, linhas_display, linhas_mailer)")
    # Tabelas que o agente NÃO pode enxergar (existem para provar o bloqueio).
    c.execute("CREATE TABLE raw_transaction_data AS SELECT 1 AS household_key, 'segredo' AS TRANS_TIME")
    c.execute("CREATE TABLE fato_ajustes AS SELECT 1 AS household_key, 'quantidade_nao_positiva' AS motivo")
    c.execute("CREATE TABLE log_cargas AS SELECT 'teste123' AS versao_base, 'transaction_data' AS tabela")
    c.execute("CREATE TABLE meta (chave VARCHAR, valor VARCHAR)")
    c.execute("INSERT INTO meta VALUES ('versao_base', 'teste123')")
    views.criar_views(c, cfg_teste())


def criar_arquivo(destino: Path) -> Path:
    c = duckdb.connect(str(destino))
    montar(c)
    c.close()
    return destino
