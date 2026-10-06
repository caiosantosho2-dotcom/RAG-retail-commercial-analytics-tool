"""Aba "Risco de pausa (churn)": o "e daí?" vem antes de qualquer gráfico e os números batem com a ferramenta."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import carga
from src.config import CFG, RAIZ
from src.nucleo import banco, cache
from src.nucleo.churn import prever_churn

CARREGAR_ORIGINAL = carga.carregar    # guardada na importação: o fixture do módulo troca carga.carregar durante os testes
APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")
ABAS = ["Chat", "Segmentos (RFM)", "Valor do cliente (CLV)", "Risco de pausa (churn)", "Desconto por segmento", "Dados e qualidade"]


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
def test_a_aba_abre_sem_erro_na_quarta_posicao(tela_real):
    assert not tela_real.exception and not tela_real.error
    assert [t.label for t in tela_real.tabs] == ABAS


@precisa_do_banco
def test_o_e_dai_e_o_primeiro_elemento_antes_de_qualquer_grafico(tela_real):
    elementos = filhos(tela_real.tabs[3])
    assert type(elementos[0]).__name__ == "Subheader" and elementos[0].value == "E daí?"
    tipos = [getattr(e, "type", "") for e in elementos]
    assert tipos.count("vega_lite_chart") == 4 and tipos.index("vega_lite_chart") > 1


@precisa_do_banco
def test_a_aba_mostra_o_mesmo_e_dai_e_os_mesmos_numeros_da_ferramenta(tela_real):
    banco.definir_banco(BANCO)
    r = prever_churn()
    textos = " ".join(m.value for m in tela_real.tabs[3].markdown)
    for bloco in ("conclusao", "acao_recomendada", "impacto_estimado"):
        assert r["e_dai"][bloco] in textos
    metricas = {m.label: m.value for m in tela_real.tabs[3].metric}
    assert metricas["Households ativos avaliados"] == "2.203"
    assert metricas["Em alerta hoje"] == str(sum(s["alertas"] for s in r["risco_por_segmento"]))
    assert metricas["AUC do modelo × regra simples"] == f"{r['auc_modelo']:.2f}".replace(".", ",") + " × " + f"{r['auc_baseline']:.2f}".replace(".", ",")


@precisa_do_banco
def test_os_titulos_dos_quatro_graficos_dizem_a_conclusao(tela_real):
    titulos = [json.loads(g.proto.spec)["title"] for g in tela_real.tabs[3].get("vega_lite_chart")]
    titulos = [t["text"] if isinstance(t, dict) else t for t in titulos]
    assert titulos[0].startswith("Esporádicos têm ") and "de risco de ficar 8 semanas sem comprar" in titulos[0]
    assert titulos[1].startswith("No limiar ") and "troca recall por precisão" in titulos[1]
    assert titulos[2].startswith("As probabilidades são confiáveis")
    assert titulos[3].startswith("O maior sinal é ") and "constância" in titulos[3]


@precisa_do_banco
def test_a_tabela_de_risco_soma_a_populacao_e_mostra_pausas_e_dinheiro_em_risco(tela_real):
    tabela = next(d for d in tela_real.tabs[3].dataframe if "% das pausas" in d.value.columns)
    assert tabela.value["Households"].sum() == 2203 and list(tabela.value["Segmento"]) == ["Fiéis", "Regulares", "Esporádicos"]
    assert tabela.value["% das pausas"].sum() == pytest.approx(100) and tabela.value["% do valor em risco"].sum() == pytest.approx(100)


@precisa_do_banco
def test_ha_comparacao_com_a_regra_simples_matriz_de_confusao_e_tabelas_gemeas(tela_real):
    comparacao = next(d for d in tela_real.tabs[3].dataframe if "Regra simples" in d.value.columns)
    assert list(comparacao.value["Medida"])[0] == "AUC" and len(comparacao.value) == 6
    rotulos = [e.label for e in tela_real.tabs[3].expander]
    assert rotulos.count("Ver os dados do gráfico") == 3 and "Definição, validação e limitações" in rotulos
    matriz = next(d for d in tela_real.tabs[3].dataframe if "Verdadeiros positivos" in d.value.columns)
    assert list(matriz.value["Previsão"]) == ["Modelo", "Regra simples"]


@precisa_do_banco
def test_as_legendas_explicam_pausa_limiar_e_associacao_nao_causa(tela_real):
    legendas = " ".join(c.value for c in tela_real.tabs[3].caption)
    assert "já estão em pausa" in legendas and "maximiza o F1" in legendas and "Associação, não causa" in legendas
    assert "Diferença de AUC" in legendas and "por household" in legendas


@precisa_do_banco
def test_a_aba_nao_chama_a_pausa_de_saida_definitiva(tela_real):
    texto = " ".join(m.value for m in tela_real.tabs[3].markdown).lower()
    assert "pausa não é saída" in texto and "voltam" in texto or "volta em até 18 semanas" in texto


def test_base_pequena_demais_mostra_erro_legivel_sem_quebrar(monkeypatch, tmp_path):
    from tests.test_carga import upload_csv
    pequena = CARREGAR_ORIGINAL(upload=upload_csv(), pasta_bancos=tmp_path)
    monkeypatch.setattr(carga, "carregar", lambda **kw: pequena)
    cache.limpar()
    at = AppTest.from_file(APP, default_timeout=300).run()
    assert not at.exception
    assert [e.value for e in at.tabs[3].error], "a aba deveria mostrar a mensagem do erro"
    banco.fechar_todas()


def test_sem_dados_a_aba_pede_para_carregar(monkeypatch):
    from src.etl import ErroCarga

    def sem_dados(**kw):
        raise ErroCarga("Nenhum dado encontrado. Arraste os arquivos exportados do BI.")

    monkeypatch.setattr(carga, "carregar", sem_dados)
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception and any("Carregue os dados na aba Chat" in i.value for i in at.tabs[3].info)
