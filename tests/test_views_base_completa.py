"""Views sobre a base completa, conferidas contra os CSVs brutos por um caminho independente
(read_csv_auto + pandas), e contra a consistência interna (aditividade, árvore de vendas).
Pula se o banco não existir; rode `python -m src.etl` (ou `python -m src.views` num banco existente)."""

import duckdb
import pandas as pd
import pytest

from src.config import CFG, RAIZ

BANCO = RAIZ / CFG["banco"]["arquivo"]
RAW = RAIZ / CFG["dados"]["pasta_raw"]
pytestmark = pytest.mark.skipif(not (BANCO.exists() and (RAW / "transaction_data.csv").exists()),
                                reason="rode `python -m src.etl` com os dados em data/raw")

ATUAL, BASE = (76, 101), (24, 49)
NAO_MERCADORIA = ("UPPER(TRIM(p.DEPARTMENT)) IN ('KIOSK-GAS','MISC SALES TRAN','MISC. TRANS.','COUP/STR & MFG') "
                  "OR UPPER(TRIM(p.COMMODITY_DESC)) = 'COUPON/MISC ITEMS'")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(BANCO), read_only=True)
    c.execute(f"CREATE TEMP VIEW csv_t AS SELECT * FROM read_csv_auto('{(RAW / 'transaction_data.csv').as_posix()}')")
    c.execute(f"CREATE TEMP VIEW csv_p AS SELECT * FROM read_csv_auto('{(RAW / 'product.csv').as_posix()}')")
    # Vendas válidas segundo a regra de negócio, direto do CSV (independente do ETL e das views).
    c.execute(f"""CREATE TEMP VIEW csv_validas AS SELECT t.* FROM csv_t t JOIN csv_p p USING (PRODUCT_ID)
                  WHERE t.QUANTITY > 0 AND NOT ({NAO_MERCADORIA})""")
    yield c
    c.close()


def um(con, sql):
    return con.execute(sql).fetchone()


def df(con, sql):
    return con.execute(sql).df()


def test_janela_e_a_combinada(con):
    j = df(con, "SELECT * FROM vw_janela").iloc[0]
    assert (j.semana_ini_atual, j.semana_fim_atual, j.semana_ini_base, j.semana_fim_base) == (*ATUAL, *BASE)
    assert j.semana_max_base == 102   # a semana 102 (6 dias) fica fora da janela


def test_vendas_item_nao_multiplica_linhas(con):
    assert um(con, "SELECT COUNT(*) FROM vw_vendas_item")[0] == um(con, "SELECT COUNT(*) FROM fato_transacoes")[0]
    assert float(um(con, "SELECT SUM(faturamento) FROM vw_vendas_item")[0]) == pytest.approx(
        float(um(con, "SELECT SUM(SALES_VALUE) FROM fato_transacoes")[0]))


@pytest.mark.parametrize("periodo,semanas", [("atual", ATUAL), ("base", BASE)])
def test_faturamento_cestas_ticket_batem_com_o_csv(con, periodo, semanas):
    ini, fim = semanas
    v_csv, c_csv, q_csv = um(con, f"SELECT SUM(SALES_VALUE), COUNT(DISTINCT BASKET_ID), SUM(QUANTITY) "
                                  f"FROM csv_validas WHERE WEEK_NO BETWEEN {ini} AND {fim}")
    v, c, q = um(con, f"SELECT SUM(faturamento), COUNT(*), SUM(itens) FROM vw_metricas_cesta WHERE periodo = '{periodo}'")
    assert float(v) == pytest.approx(float(v_csv), abs=0.01) and c == c_csv and float(q) == pytest.approx(float(q_csv))
    assert float(v) / c == pytest.approx(float(v_csv) / c_csv)


def test_desconto_confere_com_pandas(con):
    """Segundo caminho: pandas sobre o CSV, semanas da janela atual."""
    d = con.execute(f"SELECT SALES_VALUE, RETAIL_DISC, COUPON_DISC, COUPON_MATCH_DISC FROM csv_validas "
                    f"WHERE WEEK_NO BETWEEN {ATUAL[0]} AND {ATUAL[1]}").df()
    desconto = -(d.RETAIL_DISC + d.COUPON_DISC + d.COUPON_MATCH_DISC).sum()
    bruto = d.SALES_VALUE.sum() + desconto
    r = um(con, "SELECT SUM(desconto_total), SUM(valor_bruto), 100 * SUM(desconto_total) / SUM(valor_bruto) "
                "FROM vw_vendas_item WHERE periodo = 'atual'")
    assert float(r[0]) == pytest.approx(desconto, abs=0.05) and float(r[1]) == pytest.approx(bruto, abs=0.05)
    assert r[2] == pytest.approx(100 * desconto / bruto, abs=0.001)


def test_cesta_pertence_a_um_unico_dia_e_periodo(con):
    assert um(con, "SELECT COUNT(*) FROM (SELECT BASKET_ID FROM vw_vendas_item WHERE periodo IS NOT NULL "
                   "GROUP BY 1 HAVING COUNT(DISTINCT data_id) > 1 OR COUNT(DISTINCT periodo) > 1)")[0] == 0


def test_aditividade_item_cesta_loja_semana(con):
    f_item = float(um(con, "SELECT SUM(faturamento) FROM vw_vendas_item WHERE periodo IS NOT NULL")[0])
    assert float(um(con, "SELECT SUM(faturamento) FROM vw_metricas_cesta")[0]) == pytest.approx(f_item)
    assert float(um(con, "SELECT SUM(faturamento) FROM vw_metricas_loja_semana")[0]) == pytest.approx(f_item)
    assert float(um(con, "SELECT SUM(faturamento) FROM vw_metricas_loja_depto_semana")[0]) == pytest.approx(f_item)
    assert um(con, "SELECT SUM(cestas) FROM vw_metricas_loja_semana")[0] == um(con, "SELECT COUNT(*) FROM vw_metricas_cesta")[0]


def test_loja_semana_confere_com_pandas_numa_loja(con):
    """Loja 367 (maior da janela atual), calculada por pandas sobre o CSV."""
    d = con.execute(f"SELECT BASKET_ID, SALES_VALUE, QUANTITY FROM csv_validas WHERE STORE_ID = 367 "
                    f"AND WEEK_NO BETWEEN {ATUAL[0]} AND {ATUAL[1]}").df()
    cestas = d.BASKET_ID.nunique()
    r = um(con, "SELECT SUM(faturamento), SUM(cestas), SUM(itens) FROM vw_metricas_loja_semana "
                "WHERE STORE_ID = 367 AND periodo = 'atual'")
    assert float(r[0]) == pytest.approx(d.SALES_VALUE.sum(), abs=0.01) and r[1] == cestas
    assert float(r[0]) / r[1] == pytest.approx(d.SALES_VALUE.sum() / cestas)       # ticket médio
    assert float(r[2]) / r[1] == pytest.approx(d.QUANTITY.sum() / cestas)          # itens por cesta
    assert um(con, "SELECT amostra_pequena FROM vw_metricas_loja_semana WHERE STORE_ID = 367 LIMIT 1")[0] is False


def test_semana_alinhada_cobre_26_semanas_nos_dois_periodos(con):
    for periodo in ("atual", "base"):
        assert um(con, f"SELECT COUNT(DISTINCT semana_alinhada), MIN(semana_alinhada), MAX(semana_alinhada) "
                       f"FROM vw_vendas_item WHERE periodo = '{periodo}'") == (26, 76, 101)


def test_like_for_like(con):
    lfl = {r[0] for r in con.execute("SELECT STORE_ID FROM vw_lojas_like_for_like").fetchall()}
    atual = {r[0] for r in con.execute("SELECT DISTINCT STORE_ID FROM vw_metricas_cesta WHERE periodo = 'atual'").fetchall()}
    base = {r[0] for r in con.execute("SELECT DISTINCT STORE_ID FROM vw_metricas_cesta WHERE periodo = 'base'").fetchall()}
    assert lfl == atual & base and len(lfl) == 214
    y = df(con, "SELECT * FROM vw_yoy_resumo").iloc[0]
    assert (y.lojas_atual, y.lojas_base, y.lojas_like_for_like) == (319, 327, 214)
    assert y.lojas_so_atual == 319 - 214 and y.lojas_so_base == 327 - 214
    assert 95 < y.pct_vendas_atual_em_lfl < 97 and 98.5 < y.pct_vendas_base_em_lfl < 99.5
    assert um(con, "SELECT COUNT(*) FROM vw_yoy_loja")[0] == 214


def test_yoy_resumo_bate_com_pandas_e_arvore_fecha(con):
    lfl = [r[0] for r in con.execute("SELECT STORE_ID FROM vw_lojas_like_for_like").fetchall()]
    d = con.execute("SELECT household_key, BASKET_ID, STORE_ID, WEEK_NO, SALES_VALUE FROM csv_validas").df()
    d = d[d.STORE_ID.isin(lfl)]
    a = d[d.WEEK_NO.between(*ATUAL)]
    b = d[d.WEEK_NO.between(*BASE)]
    y = df(con, "SELECT * FROM vw_yoy_resumo").iloc[0]
    assert y.faturamento_atual == pytest.approx(a.SALES_VALUE.sum(), abs=0.05)
    assert y.faturamento_base == pytest.approx(b.SALES_VALUE.sum(), abs=0.05)
    assert (y.cestas_atual, y.cestas_base) == (a.BASKET_ID.nunique(), b.BASKET_ID.nunique())
    assert (y.clientes_atual, y.clientes_base) == (a.household_key.nunique(), b.household_key.nunique())
    produto = ((1 + y.var_clientes_pct / 100) * (1 + y.var_idas_por_cliente_pct / 100)
               * (1 + y.var_ticket_pct / 100))
    assert produto == pytest.approx(1 + y.var_faturamento_pct / 100)
    # households presentes nos dois períodos (em qualquer loja), segundo caminho
    tudo = con.execute("SELECT household_key, WEEK_NO FROM csv_validas").df()
    hh_a = set(tudo[tudo.WEEK_NO.between(*ATUAL)].household_key)
    hh_b = set(tudo[tudo.WEEK_NO.between(*BASE)].household_key)
    assert y.clientes_nos_dois_periodos == len(hh_a & hh_b)


def test_yoy_loja_soma_o_resumo(con):
    s = um(con, "SELECT SUM(faturamento_atual), SUM(faturamento_base), SUM(cestas_atual), SUM(cestas_base) FROM vw_yoy_loja")
    y = df(con, "SELECT * FROM vw_yoy_resumo").iloc[0]
    assert float(s[0]) == pytest.approx(y.faturamento_atual) and float(s[1]) == pytest.approx(y.faturamento_base)
    assert (s[2], s[3]) == (y.cestas_atual, y.cestas_base)


def test_categoria_soma_o_total_e_penetracao_valida(con):
    todas = um(con, "SELECT SUM(faturamento_atual), SUM(faturamento_base) FROM vw_yoy_categoria WHERE marca = 'TODAS'")
    y = df(con, "SELECT * FROM vw_yoy_resumo").iloc[0]
    assert float(todas[0]) == pytest.approx(y.faturamento_atual) and float(todas[1]) == pytest.approx(y.faturamento_base)
    marcas = um(con, "SELECT SUM(faturamento_atual) FROM vw_yoy_categoria WHERE marca <> 'TODAS'")
    assert float(marcas[0]) == pytest.approx(float(todas[0]))
    assert um(con, "SELECT MIN(penetracao_atual) FROM vw_yoy_categoria")[0] >= 0
    assert um(con, "SELECT MAX(penetracao_atual) FROM vw_yoy_categoria")[0] <= 100.0


def test_metricas_cliente_cobre_os_households_da_janela(con):
    n_csv = um(con, f"SELECT COUNT(DISTINCT household_key) FROM csv_validas WHERE WEEK_NO BETWEEN {ATUAL[0]} AND {ATUAL[1]}")[0]
    assert um(con, "SELECT COUNT(*) FROM vw_metricas_cliente WHERE periodo = 'atual'")[0] == n_csv
    assert um(con, "SELECT COUNT(*) - COUNT(DISTINCT (household_key, periodo)) FROM vw_metricas_cliente")[0] == 0
    assert um(con, "SELECT MIN(recencia_dias) FROM vw_metricas_cliente")[0] >= 0
    assert um(con, "SELECT MAX(recencia_dias) FROM vw_metricas_cliente WHERE periodo = 'atual'")[0] <= 26 * 7
    assert float(um(con, "SELECT SUM(valor) FROM vw_metricas_cliente WHERE periodo = 'atual'")[0]) == pytest.approx(
        float(um(con, "SELECT SUM(faturamento) FROM vw_metricas_cesta WHERE periodo = 'atual'")[0]))


def test_contexto_mostra_base_com_menos_acoes(con):
    c = df(con, "SELECT * FROM vw_contexto_periodo").set_index("periodo")
    assert c.loc["atual", "resgates_cupom"] > 5 * c.loc["base", "resgates_cupom"]
    assert c.loc["atual", "campanhas_ativas"] > c.loc["base", "campanhas_ativas"]
    assert (c.semanas_com_dado_causal == 26).all()


def test_sanity_de_negocio_na_janela(con):
    y = df(con, "SELECT * FROM vw_yoy_resumo").iloc[0]
    for ticket in (y.ticket_atual, y.ticket_base):
        assert 15 < ticket < 60                    # ticket de supermercado: dezenas de dólares
    ipc = um(con, "SELECT SUM(itens) / COUNT(*) FROM vw_metricas_cesta")[0]
    assert 5 < float(ipc) < 30                     # unidades por cesta
    pct = um(con, "SELECT 100 * SUM(desconto_total) / SUM(valor_bruto) FROM vw_vendas_item WHERE periodo IS NOT NULL")[0]
    assert 5 < pct < 30                            # desconto sobre o bruto
    assert -30 < y.var_faturamento_pct < 30        # variação anual plausível


def test_lojas_pequenas_marcadas(con):
    r = um(con, "SELECT COUNT(DISTINCT STORE_ID) FILTER (WHERE amostra_pequena), COUNT(DISTINCT STORE_ID) "
                "FROM vw_metricas_loja_semana WHERE periodo = 'atual'")
    assert r[1] == 319 and 200 < r[0] < 220        # 211 das 319 lojas têm menos de 100 cestas na janela
