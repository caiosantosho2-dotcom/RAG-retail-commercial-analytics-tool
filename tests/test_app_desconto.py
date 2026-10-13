"""Aba "Desconto por segmento": o "e daí?" vem antes de qualquer gráfico e os números batem com a ferramenta."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import carga
from src.config import CFG, RAIZ
from src.nucleo import banco, cache
from src.nucleo.teste_desconto import testar_desconto_entre_segmentos

CARREGAR_ORIGINAL = carga.carregar    # guardada na importação: o fixture do módulo troca carga.carregar durante os testes
APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")
ABAS = ["Resumo", "Chat", "Segmentos (RFM)", "Valor do cliente (CLV)", "Risco de pausa (churn)", "Desconto por segmento", "Dados e qualidade"]
IDX = 5


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


@precisa_do_banco
def test_a_aba_abre_sem_erro_na_quinta_posicao(tela_real):
    assert not tela_real.exception and not tela_real.error
    assert [t.label for t in tela_real.tabs] == ABAS


@precisa_do_banco
def test_o_e_dai_e_o_primeiro_elemento_antes_de_qualquer_grafico(tela_real):
    elementos = list(tela_real.tabs[IDX].children.values())
    assert type(elementos[0]).__name__ == "Subheader" and elementos[0].value == "E daí?"
    tipos = [getattr(e, "type", "") for e in elementos]
    assert tipos.count("vega_lite_chart") == 3 and tipos.index("vega_lite_chart") > 1


@precisa_do_banco
def test_a_aba_mostra_o_mesmo_e_dai_e_os_mesmos_numeros_da_ferramenta(tela_real):
    banco.definir_banco(BANCO)
    r = testar_desconto_entre_segmentos()
    textos = " ".join(m.value for m in tela_real.tabs[IDX].markdown)
    for bloco in ("conclusao", "acao_recomendada", "impacto_estimado", "limitacoes"):
        assert r["e_dai"][bloco] in textos
    metricas = {m.label: m.value for m in tela_real.tabs[IDX].metric}
    assert metricas["Households comparados"] == "2.421" and metricas["Kruskal-Wallis (p-valor)"] == "0,009"
    assert metricas["Tamanho do efeito (eta²)"] == "0,0036" and metricas["Veredito"] == "Diferença desprezível"


@precisa_do_banco
def test_os_titulos_dos_tres_graficos_dizem_a_conclusao(tela_real):
    titulos = [json.loads(g.proto.spec)["title"] for g in tela_real.tabs[IDX].get("vega_lite_chart")]
    titulos = [t["text"] if isinstance(t, dict) else t for t in titulos]
    assert titulos[0].startswith("Os segmentos recebem desconto praticamente igual: medianas de 14,1% a 15,4%")
    assert titulos[1].startswith("Nenhum dos 6 pares tem diferença de mediana distinguível de zero")
    assert titulos[2].startswith("Só com quem comprou 5+ vezes") and "deixa de ser significativa" in titulos[2]


@precisa_do_banco
def test_cada_grafico_tem_tabela_e_ha_o_expander_do_teste(tela_real):
    rotulos = [e.label for e in tela_real.tabs[IDX].expander]
    assert rotulos.count("Ver os dados do gráfico") == 3 and "Teste, post-hoc e limitações" in rotulos
    post_hoc = next(d for d in tela_real.tabs[IDX].dataframe if "p ajustado (Holm)" in d.value.columns)
    assert len(post_hoc.value) == 6 and int(post_hoc.value["Significativo a 5%?"].sum()) == 1
    shapiro = next(d for d in tela_real.tabs[IDX].dataframe if "Normal a 5%?" in d.value.columns)
    assert len(shapiro.value) == 4 and not shapiro.value["Normal a 5%?"].any()


@precisa_do_banco
def test_as_legendas_explicam_a_hipotese_o_bootstrap_e_o_motivo_da_sensibilidade(tela_real):
    legendas = " ".join(c.value for c in tela_real.tabs[IDX].caption)
    assert "Hipótese testada" in legendas and "bootstrap" in legendas and "sem ajuste de Holm" in legendas
    assert "poucas cestas" in legendas and "2.138 de 2.421" in legendas


def test_base_pequena_demais_mostra_erro_legivel_sem_quebrar(monkeypatch, tmp_path):
    from tests.test_carga import upload_csv
    pequena = CARREGAR_ORIGINAL(upload=upload_csv(), pasta_bancos=tmp_path)
    monkeypatch.setattr(carga, "carregar", lambda **kw: pequena)
    cache.limpar()
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception
    assert [e.value for e in at.tabs[IDX].error], "a aba deveria mostrar a mensagem do erro"
    banco.fechar_todas()


def test_sem_dados_a_aba_pede_para_carregar(monkeypatch):
    from src.etl import ErroCarga

    def sem_dados(**kw):
        raise ErroCarga("Nenhum dado encontrado. Arraste os arquivos exportados do BI.")

    monkeypatch.setattr(carga, "carregar", sem_dados)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and any("Carregue os dados na aba Chat" in i.value for i in at.tabs[IDX].info)
