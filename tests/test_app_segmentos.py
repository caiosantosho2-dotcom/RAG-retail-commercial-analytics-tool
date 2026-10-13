"""Aba Segmentos (RFM): o "e daí?" vem antes de qualquer gráfico, e a aba mostra os mesmos números da ferramenta."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import carga
from src.config import CFG, RAIZ
from src.etl import ErroCarga
from src.nucleo import banco, cache
from src.nucleo.rfm import segmentar_clientes
from src.ui import graficos
from tests.test_carga import upload_csv

CARREGAR_ORIGINAL = carga.carregar   # guardada na importação: o fixture do módulo troca carga.carregar durante os testes
APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


def resultado_real():
    rel = carga.relatorio(BANCO)
    return carga.ResultadoCarga(BANCO, rel["versao_base"], "pasta", True, carga.resumir(BANCO), [])


@pytest.fixture(scope="module")
def tela_real():
    """O app inteiro, uma vez, sobre a base real (a segmentação leva alguns segundos)."""
    mp = pytest.MonkeyPatch()
    mp.setattr(carga, "carregar", lambda **kw: resultado_real())
    cache.limpar()
    at = AppTest.from_file(APP, default_timeout=300).run()
    yield at
    banco.fechar_todas()
    mp.undo()


def filhos(aba):
    return list(aba.children.values())


@precisa_do_banco
def test_a_aba_abre_sem_erro_com_tres_abas_e_o_chat_primeiro(tela_real):
    assert not tela_real.exception and not tela_real.error
    assert [t.label for t in tela_real.tabs] == ["Resumo", "Chat", "Segmentos (RFM)", "Valor do cliente (CLV)", "Risco de pausa (churn)", "Desconto por segmento", "Dados e qualidade"]
    assert len(tela_real.chat_input) == 1


@precisa_do_banco
def test_o_e_dai_e_o_primeiro_elemento_da_aba_antes_de_qualquer_grafico(tela_real):
    elementos = filhos(tela_real.tabs[2])
    assert type(elementos[0]).__name__ == "Subheader" and elementos[0].value == "E daí?"
    tipos = [getattr(e, "type", "") for e in elementos]
    assert "vega_lite_chart" in tipos
    assert tipos.index("vega_lite_chart") > 1            # depois do subtítulo e do bloco com a conclusão


@precisa_do_banco
def test_o_bloco_e_dai_tem_os_quatro_itens(tela_real):
    texto = " ".join(m.value for m in tela_real.tabs[2].markdown)
    for rotulo in ("Ação recomendada.", "Impacto estimado.", "Limitações."):
        assert rotulo in texto
    assert any(m.value.startswith("### ") and "faturamento da janela" in m.value for m in tela_real.tabs[2].markdown)   # conclusão em destaque


@precisa_do_banco
def test_a_aba_mostra_os_mesmos_numeros_da_ferramenta_e_do_chat(tela_real):
    banco.definir_banco(BANCO)
    r = segmentar_clientes()
    textos = " ".join(m.value for m in tela_real.tabs[2].markdown)
    assert r["e_dai"]["conclusao"] in textos and r["e_dai"]["impacto_estimado"] in textos
    metricas = {m.label: m.value for m in tela_real.tabs[2].metric}
    assert metricas["Segmentos (K)"] == str(r["k_usado"]) == "4"
    assert metricas["Households fora da análise"] == "79"
    perfil = next(d for d in tela_real.tabs[2].dataframe if "Segmento" in d.value.columns)
    assert perfil.value["Households"].sum() == 2421 and list(perfil.value["Segmento"]) == [s["nome"] for s in r["segmentos"]]


@precisa_do_banco
def test_os_tres_graficos_tem_titulo_com_a_conclusao(tela_real):
    graficos_vega = tela_real.tabs[2].get("vega_lite_chart")
    assert len(graficos_vega) == 3
    titulos = [json.loads(g.proto.spec)["title"] for g in graficos_vega]
    titulos = [t["text"] if isinstance(t, dict) else t for t in titulos]
    assert titulos[0].startswith("Fiéis são ") and "do faturamento" in titulos[0]
    assert "A silhueta sozinha escolheria K=2; só K=4 passa" in titulos[1]
    assert titulos[2].startswith("A retenção é estável")


@precisa_do_banco
def test_cada_grafico_tem_a_versao_em_tabela_e_ha_um_expander_de_escolhas(tela_real):
    rotulos = [e.label for e in tela_real.tabs[2].expander]
    assert rotulos.count("Ver os dados do gráfico") == 2 and "Ver a avaliação de cada K" in rotulos
    assert "Escolhas estatísticas e exclusões" in rotulos


@precisa_do_banco
def test_a_legenda_explica_a_regra_do_k_e_a_limitacao_do_coorte(tela_real):
    legendas = " ".join(c.value for c in tela_real.tabs[2].caption)
    assert "Regra combinada" in legendas and "painel em formação" in legendas


def test_base_pequena_demais_mostra_erro_legivel_sem_quebrar(monkeypatch, tmp_path):
    pequena = CARREGAR_ORIGINAL(upload=upload_csv(), pasta_bancos=tmp_path)
    monkeypatch.setattr(carga, "carregar", lambda **kw: pequena)
    cache.limpar()
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    renderizado = [f"{type(c).__name__}: {str(getattr(c, 'value', ''))[:80]}" for c in filhos(at.tabs[2])]
    assert any("Não foi possível segmentar" in e.value or "Nenhuma" in e.value for e in at.tabs[2].error), renderizado
    banco.fechar_todas()


def test_sem_dados_a_aba_pede_para_carregar(monkeypatch):
    def sem_dados(**kw):
        raise ErroCarga("Nenhum dado encontrado. Arraste os arquivos exportados do BI.")
    monkeypatch.setattr(carga, "carregar", sem_dados)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert any("Carregue os dados na aba Chat" in i.value for i in at.tabs[2].info)
