"""Cada view contra um cálculo feito à mão, numa base mínima com janela encolhida.

Janela do teste: 2 semanas atuais (9-10), offset de 4 (base = semanas 5-6), cliente ativo = 1 semana,
loja pequena = menos de 2 cestas. Semana s cobre os dias 7*(s-1)+1 .. 7*s; semana 1 = dia 1.
Lojas: 1 em ambos os períodos, 2 só na atual, 3 só na base.
"""

import duckdb
import pytest

from src import views

from tests import sintetico
from tests.sintetico import LINHAS


@pytest.fixture(scope="module")
def con():
    c = duckdb.connect()
    sintetico.montar(c)
    yield c
    c.close()


def linhas(con, sql):
    return con.execute(sql).fetchall()


def um(con, sql):
    return con.execute(sql).fetchone()


def test_janela(con):
    j = con.execute("SELECT * FROM vw_janela").df().iloc[0]
    assert (j.semana_ini_atual, j.semana_fim_atual, j.semana_ini_base, j.semana_fim_base) == (9, 10, 5, 6)
    assert (j.dia_ini_atual, j.dia_fim_atual, j.dia_ini_base, j.dia_fim_base) == (57, 70, 29, 42)
    assert (j.semana_ini_ultimo_mes, j.semana_ini_ultimo_trimestre) == (7, -2)


def test_janela_ignora_semana_final_incompleta(con):
    c = duckdb.connect()
    c.execute("""CREATE TABLE dim_data AS SELECT d AS data_id, DATE '2016-01-01' + CAST(d - 1 AS INTEGER) AS data,
        CAST((d - 1) // 7 + 1 AS INTEGER) AS WEEK_NO, CASE WHEN d > 63 THEN 3 ELSE 7 END AS dias_na_semana,
        d <= 63 AS semana_completa FROM range(1, 67) t(d)""")
    c.execute("CREATE TABLE fato_transacoes (data_id INTEGER)")
    nome, _, sql = views.VIEWS[0]   # vw_janela
    c.execute(sql.format(semanas=2, offset=4, ativo=1, minimo_cestas=2))
    j = c.execute("SELECT semana_fim_atual, semana_max_base FROM vw_janela").fetchone()
    assert j == (9, 10)   # a semana 10 só tem 3 dias: a janela termina na 9


def test_vendas_item_conta_linhas_e_periodos(con):
    assert um(con, "SELECT COUNT(*) FROM vw_vendas_item")[0] == len(LINHAS)
    assert dict(linhas(con, "SELECT COALESCE(periodo, 'fora'), COUNT(*) FROM vw_vendas_item GROUP BY 1")) == {
        "atual": 4, "base": 4, "fora": 1}


def test_vendas_item_desconto_e_bruto(con):
    # b1 linha 1: faturamento 10, retail -1 -> desconto 1, bruto 11; semana 5 -> alinhada 9
    r = um(con, "SELECT desconto_loja, desconto_cupom, desconto_total, valor_bruto, semana_alinhada "
                "FROM vw_vendas_item WHERE BASKET_ID = 1001 AND PRODUCT_ID = 10")
    assert [float(x) for x in r] == [1.0, 0.0, 1.0, 11.0, 9.0]
    # a2: match -1 conta como desconto de cupom
    r = um(con, "SELECT desconto_loja, desconto_cupom, desconto_total FROM vw_vendas_item WHERE BASKET_ID = 2002")
    assert [float(x) for x in r] == [0.0, 1.0, 1.0]


def test_metricas_cesta(con):
    assert um(con, "SELECT COUNT(*) FROM vw_metricas_cesta")[0] == 7
    r = um(con, "SELECT faturamento, itens, desconto_total, valor_bruto, household_key, STORE_ID "
                "FROM vw_metricas_cesta WHERE BASKET_ID = 1001")
    assert [float(x) for x in r] == [14.0, 3.0, 1.0, 15.0, 1, 1]


def test_loja_semana(con):
    r = um(con, "SELECT faturamento, cestas, itens, clientes, desconto_total, valor_bruto, ticket_medio, "
                "itens_por_cesta, pct_desconto, amostra_pequena FROM vw_metricas_loja_semana "
                "WHERE STORE_ID = 1 AND periodo = 'atual' AND semana_alinhada = 9")
    assert [float(x) for x in r[:6]] == [19.0, 2.0, 4.0, 2.0, 3.0, 22.0]
    assert r[6] == pytest.approx(9.5) and r[7] == pytest.approx(2.0) and r[8] == pytest.approx(100 * 3 / 22)
    assert r[9] is False   # loja 1 tem 3 cestas na janela atual (mínimo 2)
    # semanas da base aparecem alinhadas: semana 5 -> 9, semana 6 -> 10
    assert float(um(con, "SELECT faturamento FROM vw_metricas_loja_semana "
                         "WHERE STORE_ID = 1 AND periodo = 'base' AND semana_alinhada = 10")[0]) == 5.0
    assert um(con, "SELECT amostra_pequena FROM vw_metricas_loja_semana WHERE STORE_ID = 2")[0] is True


def test_loja_depto_semana(con):
    r = um(con, "SELECT faturamento, quantidade, cestas_com_compra, clientes, desconto_cupom "
                "FROM vw_metricas_loja_depto_semana WHERE STORE_ID = 1 AND COMMODITY_DESC = 'MILK' "
                "AND periodo = 'atual' AND semana_alinhada = 10")
    assert [float(x) for x in r] == [8.0, 2.0, 1.0, 1.0, 1.0]


def test_metricas_cliente(con):
    r = um(con, "SELECT valor, frequencia, itens, semanas_com_compra, recencia_dias, cliente_ativo, ticket_medio, "
                "pct_desconto, tem_demografia FROM vw_metricas_cliente WHERE household_key = 1 AND periodo = 'atual'")
    assert [float(x) for x in r[:5]] == [23.0, 2.0, 5.0, 2.0, 6.0]   # recência: dia 70 - dia 64
    assert r[5] is True and r[6] == pytest.approx(11.5) and r[7] == pytest.approx(100 * 4 / 27) and r[8] is True
    ativos = dict(linhas(con, "SELECT household_key || periodo, cliente_ativo FROM vw_metricas_cliente"))
    # ativo = comprou na última semana do período (cliente_ativo_semanas = 1)
    assert ativos == {"1atual": True, "2atual": False, "3atual": False, "1base": False, "2base": True, "3base": False}
    assert um(con, "SELECT recencia_dias FROM vw_metricas_cliente WHERE household_key = 2 AND periodo = 'base'")[0] == 6


def test_lojas_like_for_like(con):
    assert linhas(con, "SELECT STORE_ID FROM vw_lojas_like_for_like") == [(1,)]


def test_yoy_loja(con):
    r = um(con, "SELECT faturamento_atual, faturamento_base, var_faturamento_pct, cestas_atual, cestas_base, "
                "clientes_atual, clientes_base, ticket_atual, ticket_base, var_ticket_pct, amostra_pequena "
                "FROM vw_yoy_loja WHERE STORE_ID = 1")
    assert [float(x) for x in r[:2]] == [27.0, 19.0]
    assert r[2] == pytest.approx(100 * (27 / 19 - 1))
    assert [float(x) for x in r[3:7]] == [3.0, 2.0, 2.0, 2.0]
    assert r[7] == pytest.approx(9.0) and r[8] == pytest.approx(9.5) and r[9] == pytest.approx(100 * (9 / 9.5 - 1))
    assert r[10] is False
    assert um(con, "SELECT COUNT(*) FROM vw_yoy_loja")[0] == 1   # lojas 2 e 3 ficam de fora


def test_yoy_resumo_e_arvore_de_vendas(con):
    y = con.execute("SELECT * FROM vw_yoy_resumo").df().iloc[0]
    assert (y.lojas_like_for_like, y.lojas_atual, y.lojas_base, y.lojas_so_atual, y.lojas_so_base) == (1, 2, 2, 1, 1)
    assert y.pct_vendas_atual_em_lfl == pytest.approx(100 * 27 / 34)
    assert y.pct_vendas_base_em_lfl == pytest.approx(100 * 19 / 25)
    assert y.clientes_nos_dois_periodos == 3 and y.lojas_lfl_amostra_pequena == 0
    assert y.var_clientes_pct == pytest.approx(0.0)
    assert y.var_idas_por_cliente_pct == pytest.approx(50.0)      # 1,5 contra 1,0 cestas por cliente
    assert y.var_ticket_pct == pytest.approx(100 * (9 / 9.5 - 1))
    produto = ((1 + y.var_clientes_pct / 100) * (1 + y.var_idas_por_cliente_pct / 100)
               * (1 + y.var_ticket_pct / 100))
    assert produto == pytest.approx(1 + y.var_faturamento_pct / 100)   # a árvore reproduz a variação


def test_yoy_categoria_e_penetracao(con):
    def linha(commodity, marca):
        return um(con, "SELECT faturamento_atual, faturamento_base, var_faturamento_pct, penetracao_atual, "
                       f"penetracao_base FROM vw_yoy_categoria WHERE COMMODITY_DESC = '{commodity}' AND marca = '{marca}'")
    soup = linha("SOUP", "National")
    assert [float(x) for x in soup[:2]] == [15.0, 15.0] and soup[2] == pytest.approx(0.0)
    assert soup[3] == pytest.approx(50.0) and soup[4] == pytest.approx(100.0)
    milk = linha("MILK", "Private")
    assert [float(x) for x in milk[:2]] == [12.0, 4.0] and milk[2] == pytest.approx(200.0)
    assert milk[3] == pytest.approx(100.0) and milk[4] == pytest.approx(50.0)
    assert linha("MILK", "TODAS") == milk          # única marca: o total da categoria é igual
    assert um(con, "SELECT COUNT(*) FROM vw_yoy_categoria")[0] == 4   # 2 commodities x (marca + TODAS)


def test_contexto_periodo(con):
    r = {p: (c, a, rc, hr, dc, d, m) for p, c, a, rc, hr, dc, d, m in linhas(
        con, "SELECT periodo, campanhas_ativas, households_alvo_campanha, resgates_cupom, households_que_resgataram, "
             "semanas_com_dado_causal, pct_linhas_display, pct_linhas_mailer FROM vw_contexto_periodo")}
    assert r["atual"] == (1, 2, 1, 1, 2, pytest.approx(10.0), pytest.approx(5.0))
    assert r["base"] == (1, 1, 1, 1, 2, pytest.approx(25.0), pytest.approx(0.0))


def test_metricas_definicao_e_comentarios(con):
    nomes_view = {v[0] for v in views.VIEWS}
    assert {r[0] for r in linhas(con, "SELECT DISTINCT view_origem FROM metricas_definicao")} <= nomes_view
    for nome in nomes_view:
        comentario = con.execute("SELECT comment FROM duckdb_views() WHERE view_name = ?", [nome]).fetchone()[0]
        assert comentario and len(comentario) > 20, f"{nome} sem comentário de definição"
    assert um(con, "SELECT COUNT(*) FROM metricas_definicao")[0] == len(views.METRICAS)


def test_cliente_semana_cobre_todo_o_historico_ate_a_ultima_semana_completa(con):
    # inclui a semana 1 (fora das duas janelas): é o histórico que alimenta coorte, CLV e churn
    assert um(con, "SELECT COUNT(*), MIN(WEEK_NO), MAX(WEEK_NO) FROM vw_cliente_semana") == (8, 1, 10)
    h1_s5 = um(con, "SELECT cestas, faturamento, itens, desconto_total, valor_bruto FROM vw_cliente_semana "
                    "WHERE household_key = 1 AND WEEK_NO = 5")
    assert [float(x) for x in h1_s5] == [1.0, 14.0, 3.0, 1.0, 15.0]
    assert float(um(con, "SELECT faturamento FROM vw_cliente_semana WHERE household_key = 1 AND WEEK_NO = 1")[0]) == 99.0
    assert dict(linhas(con, "SELECT household_key, COUNT(*) FROM vw_cliente_semana GROUP BY 1")) == {1: 4, 2: 2, 3: 2}
    # tem uma linha por household e semana, sem repetir
    assert um(con, "SELECT COUNT(*) - COUNT(DISTINCT (household_key, WEEK_NO)) FROM vw_cliente_semana")[0] == 0
    # soma igual à da view de itens (menos nada: todas as semanas até a 10)
    assert float(um(con, "SELECT SUM(faturamento) FROM vw_cliente_semana")[0]) == float(
        um(con, "SELECT SUM(faturamento) FROM vw_vendas_item WHERE WEEK_NO <= 10")[0])
