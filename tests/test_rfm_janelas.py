"""RFM de janelas arbitrárias: idêntico ao das views nas janelas atual e base, e o refator não mudou o resultado da 5a."""

import pandas as pd
import pytest

from src.config import CFG, RAIZ
from src.nucleo import banco, cache
from src.nucleo.rfm import ajustar_segmentos, base_rfm, carregar_base, segmentar_clientes

BANCO = RAIZ / CFG["banco"]["arquivo"]
pytestmark = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


@pytest.fixture(scope="module")
def cur():
    banco.definir_banco(BANCO)
    yield banco.cursor()
    banco.fechar_todas()
    banco.definir_banco(None)


@pytest.mark.parametrize("periodo,janela", [("atual", (76, 101)), ("base", (24, 49))])
def test_base_rfm_e_identica_a_vw_metricas_cliente(cur, periodo, janela):
    da_view, exc_view = carregar_base(cur, periodo)
    da_janela, exc_janela = base_rfm(cur, *janela)
    colunas = ["household_key", "recencia_dias", "frequencia", "valor", "ticket_medio", "pct_desconto"]
    pd.testing.assert_frame_equal(da_view[colunas], da_janela[colunas], check_exact=False, rtol=1e-9, atol=1e-9)
    assert (da_view["tem_demografia"].astype(bool) == da_janela["tem_demografia"].astype(bool)).all()
    assert [e["households"] for e in exc_view] == [e["households"] for e in exc_janela]


def test_janela_base_tem_os_households_esperados(cur):
    df, exc = carregar_base(cur, "base")
    assert len(df) == 2384 and exc[0]["households"] == 2500 - 2384 == 116


def test_periodo_invalido_e_recusado(cur):
    with pytest.raises(ValueError):
        carregar_base(cur, "tudo; DROP TABLE x")


def test_janela_intermediaria_calcula_e_a_soma_bate_com_a_view(cur):
    df, _ = base_rfm(cur, 50, 75)
    esperado = cur.execute("SELECT SUM(faturamento) FROM vw_cliente_semana WHERE WEEK_NO BETWEEN 50 AND 75").fetchone()[0]
    assert float(df["valor"].sum()) == pytest.approx(float(esperado))
    assert df["recencia_dias"].between(0, 26 * 7).all() and (df["frequencia"] >= 1).all()


def test_refator_nao_mudou_o_resultado_da_5a(cur):
    cache.limpar()
    r = segmentar_clientes()
    assert r["k_usado"] == 4 and [(s["nome"], s["households"]) for s in r["segmentos"]] == [
        ("Fiéis", 857), ("Regulares", 980), ("Esporádicos", 426), ("Em pausa", 158)]
    df, _ = carregar_base(cur)
    nomes, perfil = ajustar_segmentos(df, 4)
    assert pd.Series(nomes).value_counts().to_dict() == {"Regulares": 980, "Fiéis": 857, "Esporádicos": 426, "Em pausa": 158}
    assert list(perfil["nome"]) == ["Fiéis", "Regulares", "Esporádicos", "Em pausa"]
