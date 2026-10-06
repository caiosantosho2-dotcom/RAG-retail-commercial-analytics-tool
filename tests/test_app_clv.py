"""Aba "Valor do cliente (CLV)": o "e daí?" vem antes de qualquer gráfico e os números batem com a ferramenta."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import carga
from src.config import CFG, RAIZ
from src.nucleo import banco, cache
from src.nucleo.clv import calcular_clv

CARREGAR_ORIGINAL = carga.carregar    # guardada na importação: o fixture do módulo troca carga.carregar durante os testes
APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


def resultado_real():
    rel = carga.relatorio(BANCO)
    return carga.ResultadoCarga(BANCO, rel["versao_base"], "pasta", True, carga.resumir(BANCO), [])


@pytest.fixture(scope="module")
def tela_real():
    mp = pytest.MonkeyPatch()
    mp.setattr(carga, "carregar", lambda **kw: resultado_real())
    cache.limpar()
    at = AppTest.from_file(APP, default_timeout=600).run()
    yield at
    banco.fechar_todas()
    mp.undo()


def filhos(aba):
    return list(aba.children.values())


@precisa_do_banco
def test_a_aba_abre_sem_erro_na_quarta_posicao_do_menu(tela_real):
    assert not tela_real.exception and not tela_real.error
    assert [t.label for t in tela_real.tabs] == ["Chat", "Segmentos (RFM)", "Valor do cliente (CLV)", "Dados e qualidade"]


@precisa_do_banco
def test_o_e_dai_e_o_primeiro_elemento_antes_de_qualquer_grafico(tela_real):
    elementos = filhos(tela_real.tabs[2])
    assert type(elementos[0]).__name__ == "Subheader" and elementos[0].value == "E daí?"
    tipos = [getattr(e, "type", "") for e in elementos]
    assert tipos.count("vega_lite_chart") == 3 and tipos.index("vega_lite_chart") > 1


@precisa_do_banco
def test_a_aba_mostra_o_mesmo_e_dai_e_os_mesmos_numeros_da_ferramenta(tela_real):
    banco.definir_banco(BANCO)
    r = calcular_clv()
    textos = " ".join(m.value for m in tela_real.tabs[2].markdown)
    for bloco in ("conclusao", "acao_recomendada", "impacto_estimado"):
        assert r["e_dai"][bloco] in textos
    metricas = {m.label: m.value for m in tela_real.tabs[2].metric}
    usd = lambda x: "US$ " + f"{x:,.0f}".replace(",", ".")
    assert metricas["Valor esperado (margem, 52 semanas)"] == usd(r["total"]["clv_total_usd"])
    assert metricas["Receita esperada (52 semanas)"] == usd(r["total"]["receita_esperada_total_usd"])
    assert metricas["Margem assumida (premissa)"] == "25%"


@precisa_do_banco
def test_os_titulos_dos_graficos_dizem_a_conclusao(tela_real):
    titulos = [json.loads(g.proto.spec)["title"] for g in tela_real.tabs[2].get("vega_lite_chart")]
    titulos = [t["text"] if isinstance(t, dict) else t for t in titulos]
    assert titulos[0].startswith("Um household do grupo Fiéis vale US$") and "em 52 semanas" in titulos[0]
    assert "gastam" in titulos[1] and "ritmo atual" in titulos[1]
    assert titulos[2].startswith("No teste de 26 semanas o método errou")


@precisa_do_banco
def test_cada_grafico_tem_tabela_e_ha_um_expander_de_premissas(tela_real):
    rotulos = [e.label for e in tela_real.tabs[2].expander]
    assert rotulos.count("Ver os dados do gráfico") == 3 and "Premissas e método" in rotulos


@precisa_do_banco
def test_as_legendas_explicam_o_intervalo_a_regressao_a_media_e_o_uso_como_media_de_grupo(tela_real):
    legendas = " ".join(c.value for c in tela_real.tabs[2].caption)
    assert "intervalo de confiança de 95%" in legendas and "regressão à média" in legendas and "não como previsão individual" in legendas


@precisa_do_banco
def test_a_tabela_de_calibracao_cobre_os_2500_households(tela_real):
    calibracao = next(d for d in tela_real.tabs[2].dataframe if "Gasto passado (US$)" in d.value.columns)
    assert calibracao.value["Households"].sum() == 2500 and len(calibracao.value) == 5


def test_base_pequena_demais_mostra_erro_legivel_sem_quebrar(monkeypatch, tmp_path):
    from tests.test_carga import upload_csv
    pequena = CARREGAR_ORIGINAL(upload=upload_csv(), pasta_bancos=tmp_path)
    monkeypatch.setattr(carga, "carregar", lambda **kw: pequena)
    cache.limpar()
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception
    assert [e.value for e in at.tabs[2].error], "a aba deveria mostrar a mensagem do erro"
    banco.fechar_todas()


def test_sem_dados_a_aba_pede_para_carregar(monkeypatch):
    from src.etl import ErroCarga

    def sem_dados(**kw):
        raise ErroCarga("Nenhum dado encontrado. Arraste os arquivos exportados do BI.")

    monkeypatch.setattr(carga, "carregar", sem_dados)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and any("Carregue os dados na aba Chat" in i.value for i in at.tabs[2].info)
