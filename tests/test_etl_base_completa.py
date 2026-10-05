"""Confere o banco construído sobre a base completa contra os CSVs brutos, por um caminho
independente do ETL (read_csv_auto direto no arquivo). Pula se o banco ou os dados não existirem."""

import duckdb
import pytest

from src.config import CFG, RAIZ

BANCO = RAIZ / CFG["banco"]["arquivo"]
RAW = RAIZ / CFG["dados"]["pasta_raw"]
pytestmark = pytest.mark.skipif(not (BANCO.exists() and (RAW / "transaction_data.csv").exists()),
                                reason="rode `python -m src.etl` com os dados em data/raw")


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect(str(BANCO), read_only=True)
    t = (RAW / "transaction_data.csv").as_posix()
    p = (RAW / "product.csv").as_posix()
    c.execute(f"CREATE TEMP VIEW csv_t AS SELECT * FROM read_csv_auto('{t}')")
    c.execute(f"CREATE TEMP VIEW csv_p AS SELECT * FROM read_csv_auto('{p}')")
    yield c
    c.close()


def one(con, sql):
    return con.execute(sql).fetchone()


def test_total_bruto_bate_com_o_arquivo(con):
    n_csv, v_csv = one(con, "SELECT COUNT(*), SUM(SALES_VALUE) FROM csv_t")
    n_lim, v_lim = one(con, "SELECT COUNT(*), SUM(SALES_VALUE) FROM fato_transacoes")
    n_aj, v_aj = one(con, "SELECT COUNT(*), SUM(SALES_VALUE) FROM fato_ajustes")
    assert n_csv == n_lim + n_aj
    assert float(v_csv) == pytest.approx(float(v_lim) + float(v_aj), abs=0.01)


def test_total_por_semana_bate_com_o_arquivo(con):
    dif = con.execute("""
        WITH a AS (SELECT WEEK_NO, SUM(SALES_VALUE) v, COUNT(*) n FROM csv_t GROUP BY 1),
             b AS (SELECT d.WEEK_NO, SUM(f.SALES_VALUE) v, COUNT(*) n FROM fato_transacoes f
                   JOIN dim_data d ON d.data_id = f.data_id GROUP BY 1),
             c AS (SELECT WEEK_NO, SUM(SALES_VALUE) v, COUNT(*) n FROM fato_ajustes GROUP BY 1)
        SELECT COUNT(*) FROM a LEFT JOIN b USING (WEEK_NO) LEFT JOIN c USING (WEEK_NO)
        WHERE a.n <> COALESCE(b.n, 0) + COALESCE(c.n, 0)
           OR ABS(a.v - COALESCE(b.v, 0) - COALESCE(c.v, 0)) > 0.01""").fetchone()[0]
    assert dif == 0


def test_contagens_das_regras_batem_com_a_auditoria(con):
    assert one(con, "SELECT COUNT(*) FROM csv_t WHERE QUANTITY <= 0")[0] == 14466
    nao_merc = one(con, """SELECT COUNT(*) FROM csv_t t JOIN csv_p p USING (PRODUCT_ID)
        WHERE UPPER(TRIM(p.DEPARTMENT)) IN ('KIOSK-GAS','MISC SALES TRAN','MISC. TRANS.','COUP/STR & MFG')
           OR UPPER(TRIM(p.COMMODITY_DESC)) = 'COUPON/MISC ITEMS'""")[0]
    assert one(con, "SELECT COUNT(*) FROM fato_ajustes WHERE motivo = 'nao_mercadoria'")[0] == nao_merc
    qtd_extra = one(con, """SELECT COUNT(*) FROM csv_t t JOIN csv_p p USING (PRODUCT_ID)
        WHERE t.QUANTITY <= 0 AND NOT (UPPER(TRIM(p.DEPARTMENT)) IN ('KIOSK-GAS','MISC SALES TRAN','MISC. TRANS.','COUP/STR & MFG')
           OR UPPER(TRIM(p.COMMODITY_DESC)) = 'COUPON/MISC ITEMS')""")[0]
    assert one(con, "SELECT COUNT(*) FROM fato_ajustes WHERE motivo = 'quantidade_nao_positiva'")[0] == qtd_extra


def test_fato_so_tem_mercadoria_com_quantidade_positiva(con):
    assert one(con, "SELECT COUNT(*) FROM fato_transacoes WHERE QUANTITY <= 0")[0] == 0
    assert one(con, """SELECT COUNT(*) FROM fato_transacoes f JOIN dim_produto p USING (PRODUCT_ID)
        WHERE UPPER(p.DEPARTMENT) IN ('KIOSK-GAS','MISC SALES TRAN','MISC. TRANS.','COUP/STR & MFG')
           OR UPPER(p.COMMODITY_DESC) = 'COUPON/MISC ITEMS'""")[0] == 0


@pytest.mark.parametrize("tabela,chave", [
    ("dim_produto", "PRODUCT_ID"), ("dim_loja", "STORE_ID"), ("dim_household", "household_key"),
    ("dim_data", "data_id"), ("fato_transacoes", "BASKET_ID, PRODUCT_ID"),
])
def test_chaves_unicas(con, tabela, chave):
    n, d = one(con, f"SELECT COUNT(*), COUNT(DISTINCT ({chave})) FROM {tabela}")
    assert n == d


@pytest.mark.parametrize("coluna,dimensao,chave", [
    ("STORE_ID", "dim_loja", "STORE_ID"), ("PRODUCT_ID", "dim_produto", "PRODUCT_ID"),
    ("data_id", "dim_data", "data_id"), ("household_key", "dim_household", "household_key"),
])
def test_integridade_referencial(con, coluna, dimensao, chave):
    orfaos = one(con, f"SELECT COUNT(*) FROM fato_transacoes f WHERE NOT EXISTS "
                      f"(SELECT 1 FROM {dimensao} d WHERE d.{chave} = f.{coluna})")[0]
    assert orfaos == 0


def test_dim_data_cobre_711_dias_e_102_semanas(con):
    assert one(con, "SELECT COUNT(*), COUNT(DISTINCT WEEK_NO) FROM dim_data") == (711, 102)
    # dim_data tem 1 linha por dia: WEEK_NO 1 (5 dias) + WEEK_NO 102 (6 dias) = 11 dias em semana incompleta
    assert one(con, "SELECT COUNT(*) FROM dim_data WHERE NOT semana_completa")[0] == 11


def test_relatorio_persistido_e_reconciliado(con):
    import json
    rel = json.loads(one(con, "SELECT valor FROM meta WHERE chave = 'relatorio_qualidade'")[0])
    assert rel["reconciliacao"]["ok"] is True
    assert rel["reconciliacao"]["semanas_divergentes"] == 0


def test_sanity_check_de_negocio(con):
    vendas, cestas, qtd, desc = (float(x) for x in one(con, """
        SELECT SUM(SALES_VALUE), COUNT(DISTINCT BASKET_ID), SUM(QUANTITY),
               SUM(RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) FROM fato_transacoes"""))
    assert 10 < vendas / cestas < 100          # ticket de supermercado: dezenas de dólares
    assert 3 < qtd / cestas < 40               # unidades por cesta
    assert 0 < -desc / (vendas - desc) < 0.4   # desconto como fração do bruto
