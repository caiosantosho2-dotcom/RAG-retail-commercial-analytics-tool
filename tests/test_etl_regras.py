"""Testa as regras do ETL em uma base sintética pequena, com resultado esperado conhecido."""

import duckdb
import pytest

from src import etl, qualidade
from src.config import CFG

CABECALHO_TRANS = ("household_key,BASKET_ID,DAY,PRODUCT_ID,QUANTITY,SALES_VALUE,STORE_ID,RETAIL_DISC,"
                   "TRANS_TIME,WEEK_NO,COUPON_DISC,COUPON_MATCH_DISC")
TRANSACOES = [
    "1,100,1,10,2,5.00,1,-1.00,1631,1,0,0",        # venda válida
    "1,100,1,11,1,3.00,1,0,1631,1,-0.50,0",        # venda válida
    "2,101,2,12,0,0,1,0,0905,1,-0.25,0",           # quantidade zero
    "2,101,2,13,1,20.00,1,0,0905,1,0,0",           # KIOSK-GAS: não é mercadoria
    "2,101,2,14,3,1.00,1,0,0905,1,0,0",            # COUPON/MISC ITEMS: não é mercadoria
    "3,102,8,10,1,abc,2,0,2599,2,0,0",             # valor não numérico
    "3,,8,10,1,2.00,2,0,0800,2,0,0",               # cesta ausente
    "3,103,8,10,1,2.00,2,,2599,2,,",               # válida: descontos nulos viram 0, hora inválida
    "3,103,8,11,1,0,2,0,0800,2,0,0",               # item grátis: fica na venda
]
PRODUTOS = [
    "PRODUCT_ID,MANUFACTURER,DEPARTMENT,BRAND,COMMODITY_DESC,SUB_COMMODITY_DESC,CURR_SIZE_OF_PRODUCT",
    "10,1,GROCERY,National,SOUP,SOUP,12 OZ",
    "11,1,GROCERY,Private,MILK,MILK,1 GAL",
    "12,1,GROCERY,National,BREAD,BREAD,16 OZ",
    "13,1,KIOSK-GAS,National,FUEL,FUEL,GAL",
    "14,1,GROCERY,National,COUPON/MISC ITEMS,COUPON,NA",
    "10,1,GROCERY,National,SOUP,SOUP,12 OZ",      # PRODUCT_ID duplicado de propósito
]
OUTROS = {
    "hh_demographic": "AGE_DESC,MARITAL_STATUS_CODE,INCOME_DESC,HOMEOWNER_DESC,HOUSEHOLD_SIZE_DESC,"
                      "KID_CATEGORY_DESC,household_key\n35-44,A,50-74K,Homeowner,2,None/Unknown,1",
    "campaign_table": "DESCRIPTION,household_key,CAMPAIGN\nTypeA,1,1",
    "campaign_desc": "DESCRIPTION,CAMPAIGN,START_DAY,END_DAY\nTypeA,1,1,10",
    "coupon": "COUPON_UPC,PRODUCT_ID,CAMPAIGN\n111,10,1",
    "coupon_redempt": "household_key,DAY,COUPON_UPC,CAMPAIGN\n1,1,111,1",
    "causal_data": "PRODUCT_ID,STORE_ID,WEEK_NO,display,mailer\n10,1,1,0,0\n10,1,1,A,0\n11,1,1,0,A",
}


def _escrever(pasta, cabecalho_trans=CABECALHO_TRANS):
    (pasta / "transaction_data.csv").write_text("\n".join([cabecalho_trans, *TRANSACOES]), encoding="utf-8")
    (pasta / "product.csv").write_text("\n".join(PRODUTOS), encoding="utf-8")
    for nome, conteudo in OUTROS.items():
        (pasta / f"{nome}.csv").write_text(conteudo, encoding="utf-8")
    return etl.localizar_fontes(pasta)


@pytest.fixture(scope="module")
def banco(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("sintetico")
    destino = pasta / "teste.duckdb"
    rel = etl.construir_banco(_escrever(pasta), destino=destino, log=lambda *_: None)
    con = duckdb.connect(str(destino), read_only=True)
    yield con, rel
    con.close()


def test_contagens_por_camada(banco):
    con, rel = banco
    assert rel["linhas_brutas"] == 9
    assert con.execute("SELECT COUNT(*) FROM fato_transacoes").fetchone()[0] == 4
    assert con.execute("SELECT COUNT(*) FROM fato_ajustes").fetchone()[0] == 5


def test_motivo_de_cada_linha_ajustada(banco):
    con, _ = banco
    motivos = dict(con.execute("SELECT motivo, COUNT(*) FROM fato_ajustes GROUP BY 1").fetchall())
    assert motivos == {"quantidade_nao_positiva": 1, "nao_mercadoria": 2,
                       "valor_nao_numerico": 1, "cesta_ausente": 1}


def test_regras_registram_linhas_afetadas(banco):
    _, rel = banco
    por_regra = {r["regra"]: r for r in rel["regras"]}
    assert por_regra["nao_mercadoria"]["linhas_afetadas"] == 2
    assert por_regra["quantidade_nao_positiva"]["linhas_afetadas"] == 1
    assert por_regra["valor_nao_numerico"]["linhas_afetadas"] == 1
    assert por_regra["nao_mercadoria"]["valor_atribuido_usd"] == pytest.approx(21.00)


def test_conversao_numerica_registrada(banco):
    _, rel = banco
    assert rel["conversao_numerica"]["SALES_VALUE"]["nao_numericos"] == 1
    assert rel["conversao_numerica"]["BASKET_ID"]["ausentes"] == 1
    assert rel["descontos_nulos_para_zero"] == {"RETAIL_DISC": 1, "COUPON_DISC": 1, "COUPON_MATCH_DISC": 1}
    assert rel["hora_invalida"] == 1


def test_item_gratis_permanece_na_venda(banco):
    con, rel = banco
    assert con.execute("SELECT COUNT(*) FROM fato_transacoes WHERE SALES_VALUE = 0").fetchone()[0] == 1
    assert rel["casos_mantidos"]["itens_gratis_sales_zero_qtd_positiva"] == 1


def test_reconciliacao_fecha(banco):
    _, rel = banco
    r = rel["reconciliacao"]
    assert r["ok"] and r["semanas_divergentes"] == 0
    assert r["vendas_brutas_usd"] == pytest.approx(r["vendas_limpas_usd"] + r["vendas_ajustes_usd"])
    assert r["vendas_brutas_usd"] == pytest.approx(33.00)


def test_join_com_produto_duplicado_nao_multiplica_linhas(banco):
    con, rel = banco
    assert all(j["ok"] for j in rel["joins"])
    assert con.execute("SELECT COUNT(*) FROM dim_produto").fetchone()[0] == 5
    assert any("duplicados" in a for a in rel["avisos"])


def test_household_sem_demografia_continua_na_dimensao(banco):
    con, _ = banco
    assert con.execute("SELECT COUNT(*) FROM dim_household").fetchone()[0] == 3
    assert con.execute("SELECT COUNT(*) FROM dim_household WHERE tem_demografia").fetchone()[0] == 1


def test_dim_data_converte_day_em_data(banco):
    con, _ = banco
    data = con.execute("SELECT CAST(data AS VARCHAR) FROM dim_data WHERE data_id = 8").fetchone()[0]
    assert data == "2016-01-08"   # data_base 2016-01-01 + (DAY - 1)


def test_causal_agregado(banco):
    con, _ = banco
    assert con.execute("SELECT linhas, linhas_display, linhas_mailer FROM causal_semana_loja "
                       "WHERE WEEK_NO = 1 AND STORE_ID = 1").fetchone() == (3, 1, 1)


def test_log_de_cargas_e_versao(banco):
    con, rel = banco
    assert con.execute("SELECT COUNT(*) FROM log_cargas WHERE versao_base = ?", [rel["versao_base"]]).fetchone()[0] == 8
    assert con.execute("SELECT valor FROM meta WHERE chave = 'versao_base'").fetchone()[0] == rel["versao_base"]


def test_markdown_renderiza(banco):
    _, rel = banco
    texto = qualidade.renderizar_markdown(rel)
    assert "Reconciliação com o bruto:** OK" in texto and "nao_mercadoria" in texto


def test_coluna_ausente_gera_erro_legivel(tmp_path):
    fontes = _escrever(tmp_path, cabecalho_trans=CABECALHO_TRANS.replace("SALES_VALUE,", "VALOR,"))
    with pytest.raises(etl.ErroCarga, match="SALES_VALUE"):
        etl.validar_fontes(fontes)


def test_arquivo_ausente_gera_erro_legivel(tmp_path):
    fontes = _escrever(tmp_path)
    fontes["coupon"].unlink()
    with pytest.raises(etl.ErroCarga, match="coupon.csv"):
        etl.validar_fontes(fontes)


def test_reconciliacao_que_falha_nao_publica_banco(tmp_path, monkeypatch):
    destino = tmp_path / "x.duckdb"
    monkeypatch.setattr(qualidade, "completar_relatorio",
                        lambda con, rel, cfg: {**rel, "reconciliacao": {"ok": False}})
    with pytest.raises(etl.ErroCarga, match="Reconciliação falhou"):
        etl.construir_banco(_escrever(tmp_path), destino=destino, log=lambda *_: None)
    assert not destino.exists()
