"""Aba "Resumo": abre sem erro, é a primeira, e cada número bate com a aba/ferramenta de origem (sem análise nova)."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import carga
from src.config import CFG, RAIZ
from src.nucleo import banco, cache
from src.nucleo.churn import prever_churn
from src.nucleo.clv import calcular_clv
from src.nucleo.rfm import segmentar_clientes
from src.nucleo import teste_desconto
from src.ui import graficos
from src.ui.aba_resumo import primeira_frase

CARREGAR_ORIGINAL = carga.carregar
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


class _Valor:
    """O Streamlit entrega o texto com o cifrão escapado para o markdown (barra e cifrão): compara o texto que o usuário vê."""
    def __init__(self, m):
        self.label, self.value, self.delta = (x.replace("\\$", "$") if isinstance(x, str) else x
                                              for x in (m.label, m.value, m.delta))


def metricas(tela):
    return {_Valor(m).label: _Valor(m) for m in tela.tabs[0].metric}


def _junta(titulo):
    return " ".join(titulo) if isinstance(titulo, list) else titulo


def milhar(n):
    return f"{round(n):,}".replace(",", ".")


def test_primeira_frase_nao_quebra_em_numeros():
    assert primeira_frase("Priorizar os Fiéis: US$ 1.103.220 de margem. Depois reativar.") == \
        "Priorizar os Fiéis: US$ 1.103.220 de margem."
    assert primeira_frase("Só uma frase com 14,1% e 1,2 ponto") == "Só uma frase com 14,1% e 1,2 ponto"


@precisa_do_banco
def test_resumo_e_a_primeira_aba_e_abre_sem_erro(tela_real):
    assert not tela_real.exception and not tela_real.error
    assert [t.label for t in tela_real.tabs][:2] == ["Resumo", "Chat"]


@precisa_do_banco
def test_indicadores_batem_com_as_ferramentas(tela_real):
    banco.definir_banco(BANCO)
    seg, clv, ch, de = segmentar_clientes(), calcular_clv(), prever_churn(), teste_desconto.testar_desconto_entre_segmentos()
    m = metricas(tela_real)
    assert len(m) == 6, list(m)
    topo = max(seg["segmentos"], key=lambda s: s["valor_medio_usd"])
    assert m[f"Parcela do faturamento: {topo['nome']}"].value == f"{topo['pct_faturamento']:.1f}".replace(".", ",") + "%"
    t, pr = clv["total"], clv["premissas"]
    rotulo = f"Margem esperada (premissa de {pr['margem'] * 100:.0f}%)"
    assert f"Margem em {pr['horizonte_semanas']} semanas, não faturamento." in " ".join(
        c.value for c in tela_real.tabs[0].caption)
    assert m[rotulo].value == "US$ " + milhar(t["clv_total_usd"])          # rotulado como margem, nunca como faturamento
    assert milhar(t["ic_95"][0]) in m[rotulo].delta and milhar(t["ic_95"][1]) in m[rotulo].delta
    segs = ch["risco_por_segmento"]
    pausa = next(v for k, v in m.items() if k.startswith("Pausa longa esperada"))
    esperado = 100 * sum(s["pausas_esperadas"] for s in segs) / sum(s["households"] for s in segs)
    assert pausa.value == f"{esperado:.1f}".replace(".", ",") + "%"
    assert f"de {milhar(sum(s['households'] for s in segs))} ativos" in pausa.delta
    # a diferença entre os ativos do indicador e a população do modelo é explicada na própria coluna
    ativos = int(m["Clientes ativos"].value.replace(".", ""))
    fora = ativos - sum(s["households"] for s in segs)
    legendas = " ".join(c.value for c in tela_real.tabs[0].caption)
    if fora > 0:
        assert f"{fora} têm menos de" in legendas and "ficam fora" in legendas


@precisa_do_banco
def test_desconto_em_linguagem_de_negocio_com_eta_e_p_em_texto_pequeno(tela_real):
    banco.definir_banco(BANCO)
    de = teste_desconto.testar_desconto_entre_segmentos()
    frases = {"diferenca_desprezivel": "Diferença estatisticamente detectável, mas pequena demais para importar na prática."}
    titulos = " ".join(m.value for m in tela_real.tabs[0].markdown)
    if de["veredito"] in frases:
        assert frases[de["veredito"]] in titulos
    legendas = " ".join(c.value for c in tela_real.tabs[0].caption)
    assert "eta²" in legendas and "p = " in legendas


@precisa_do_banco
def test_faturamento_e_clientes_ativos_batem_com_as_views_oficiais(tela_real):
    banco.definir_banco(BANCO)
    cur = banco.cursor()
    total = cur.execute("SELECT SUM(faturamento) FROM vw_vendas_item WHERE periodo = 'atual'").fetchone()[0]
    var = cur.execute("SELECT var_faturamento_pct FROM vw_yoy_resumo").fetchone()[0]
    ativos = cur.execute("SELECT COUNT(*) FROM vw_metricas_cliente WHERE periodo = 'atual' AND cliente_ativo").fetchone()[0]
    m = metricas(tela_real)
    assert m["Faturamento total"].value == "US$ " + milhar(total)               # o total geral, não o like-for-like
    assert m["Variação nas mesmas lojas"].value == ("+" if var > 0 else "") + f"{var:.1f}".replace(".", ",") + "%"
    assert m["Clientes ativos"].value == milhar(ativos)


@precisa_do_banco
def test_quatro_graficos_com_o_titulo_conclusao_das_abas_de_origem(tela_real):
    banco.definir_banco(BANCO)
    seg, clv, ch, de = segmentar_clientes(), calcular_clv(), prever_churn(), teste_desconto.testar_desconto_entre_segmentos()
    titulos = [_junta(json.loads(g.proto.spec)["title"]) for g in tela_real.tabs[0].get("vega_lite_chart")]
    assert len(titulos) == 4
    esperados = [graficos.titulo_segmentos(seg["segmentos"]), graficos.titulo_clv(clv["segmentos"])]
    assert titulos[0] == esperados[0] and titulos[1] == esperados[1]
    assert titulos[2] == graficos.titulo_risco(graficos.tabela_risco(ch["risco_por_segmento"]), ch["horizonte_semanas"])
    assert titulos[3] == graficos.titulo_distribuicao(de["grupos"], de["veredito"])


@precisa_do_banco
def test_cada_bloco_traz_uma_frase_e_dai_da_acao_recomendada(tela_real):
    banco.definir_banco(BANCO)
    textos = " ".join(m.value for m in tela_real.tabs[0].markdown)
    for r in (segmentar_clientes(), calcular_clv(), prever_churn(), teste_desconto.testar_desconto_entre_segmentos()):
        assert primeira_frase(r["e_dai"]["acao_recomendada"]) in textos
    assert textos.count("**E daí?**") == 4


def test_sem_dados_o_resumo_pede_para_carregar(monkeypatch):
    def sem_dados(**kw):
        raise carga.ErroCarga("Nenhum dado encontrado. Arraste os arquivos.")
    monkeypatch.setattr(carga, "carregar", sem_dados)
    at = AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    assert any("Carregue os dados na aba Chat para ver o resumo" in i.value for i in at.tabs[0].info)
