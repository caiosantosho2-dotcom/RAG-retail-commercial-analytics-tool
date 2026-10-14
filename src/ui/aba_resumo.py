"""Aba "Resumo": os destaques das análises para quem não vai ler cada aba.

Só junta o que o núcleo já calcula (as mesmas funções e o mesmo cache das abas de origem) e duas leituras das views
oficiais (faturamento e clientes ativos). Nenhuma análise nova e nenhuma chamada ao modelo.
"""

import re
import textwrap

import streamlit as st

from src.config import CFG
from src.nucleo import banco
from src.nucleo.churn import prever_churn
from src.nucleo.clv import calcular_clv
from src.nucleo.rfm import segmentar_clientes
from src.nucleo.teste_desconto import testar_desconto_entre_segmentos
from src.ui import cores, graficos
from src.ui.componentes import md


FRASE_DESCONTO = {
    "sem_diferenca_detectavel": "Os segmentos recebem desconto parecido: nenhuma diferença estatisticamente detectável.",
    "diferenca_desprezivel": "Diferença estatisticamente detectável, mas pequena demais para importar na prática.",
    "diferenca_relevante": "Os segmentos recebem desconto diferente, e a diferença é grande o bastante para importar."}


def _milhar(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def _usd(x: float) -> str:
    return "US$ " + _milhar(x)


def _pt(x: float, casas: int = 1) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


_md = md   # escapa o cifrão: dois "US$" no mesmo texto viram fórmula no markdown do Streamlit


def _titulo_em_linhas(grafico, largura: int = 44):
    """O título de cada gráfico é a conclusão; em meia largura ele é cortado, então quebra em linhas."""
    titulo = grafico.title if isinstance(grafico.title, str) else None
    return grafico.properties(title=textwrap.wrap(titulo, largura)) if titulo else grafico


def _sinal(x: float, casas: int = 1) -> str:
    return ("+" if x > 0 else "") + _pt(x, casas)


def primeira_frase(texto: str) -> str:
    """A primeira frase do texto (corta em ponto final seguido de maiúscula, sem quebrar números como 1.103.220)."""
    return re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])", texto.strip())[0]


def carregar_resumo(caminho_banco) -> dict:
    """Tudo o que a aba mostra, num dicionário (a aba e os testes leem daqui)."""
    with banco.usando(caminho_banco):
        seg, clv, churn, desc = (segmentar_clientes(), calcular_clv(), prever_churn(), testar_desconto_entre_segmentos())
        cur = banco.cursor()
        try:   # base pequena ou sem a janela do ano anterior: as views voltam vazias e o indicador vira "n/d"
            yoy = cur.execute("SELECT faturamento_atual, faturamento_base, var_faturamento_pct, lojas_like_for_like "
                              "FROM vw_yoy_resumo").fetchone()
            total = cur.execute("SELECT SUM(faturamento) FROM vw_metricas_cesta WHERE periodo = 'atual'").fetchone()[0]
            ativos = dict(cur.execute("SELECT periodo, COUNT(*) FILTER (WHERE cliente_ativo) FROM vw_metricas_cliente "
                                      "WHERE periodo IN ('atual', 'base') GROUP BY periodo").fetchall())
        except Exception:
            yoy, total, ativos = None, None, {}
    return {"seg": seg, "clv": clv, "churn": churn, "desc": desc, "yoy": yoy, "faturamento_total": total, "ativos": ativos}


def _metrica(coluna, rotulo: str, valor: str, delta: str | None = None, ajuda: str | None = None, direcional: bool = False):
    coluna.metric(_md(rotulo), _md(valor), delta=_md(delta) if delta else None,
                  delta_color="normal" if direcional else "off", delta_arrow="auto" if direcional else "off",
                  help=_md(ajuda) if ajuda else None, border=True)


def _bloco(coluna, titulo: str, grafico, e_dai: dict) -> None:
    with coluna:
        st.markdown(f"**{titulo}**")
        st.altair_chart(_titulo_em_linhas(grafico), theme=None, width="stretch")
        st.markdown(_md(f"**E daí?** {primeira_frase(e_dai['acao_recomendada'])}"))


def _erro(coluna, titulo: str, r: dict) -> None:
    with coluna:
        st.markdown(f"**{titulo}**")
        st.info(md(f"{r['erro']} {r.get('sugestao', '')}"))


def renderizar(caminho_banco) -> None:
    modo = cores.modo_atual()
    with st.spinner("Juntando os destaques das análises (a primeira vez leva alguns segundos) ..."):
        d = carregar_resumo(caminho_banco)
    seg, clv, churn, desc = d["seg"], d["clv"], d["churn"], d["desc"]

    st.subheader("Destaques da janela atual")
    st.caption("Os números vêm das mesmas análises das outras abas; cada bloco abaixo leva para a aba de origem.")
    linha1, linha2 = st.columns(3), st.columns(3)

    if d["yoy"] and d["faturamento_total"] is not None and d["yoy"][2] is not None:
        fat_atual, fat_base, var_fat, lojas_lfl = d["yoy"]
        _metrica(linha1[0], "Faturamento total", _usd(d["faturamento_total"]), "todas as lojas, janela atual")
        linha1[1].metric("Variação nas mesmas lojas", f"{_sinal(var_fat)}%", delta=_md(f"vs. ano anterior, {lojas_lfl} lojas"),
                         delta_color="normal", delta_arrow="up" if var_fat >= 0 else "down", border=True,
                         help=_md(f"Compara só as lojas presentes nos dois períodos: US$ {_milhar(fat_atual)} contra "
                                  f"US$ {_milhar(fat_base)}. O total acima inclui todas as lojas."))
    else:
        _metrica(linha1[0], "Faturamento total", "n/d", ajuda="Faltam semanas para o cálculo.")
        _metrica(linha1[1], "Variação nas mesmas lojas", "n/d", ajuda="Faltam as semanas do ano anterior para comparar.")
    ativos_atual, ativos_base = d["ativos"].get("atual", 0), d["ativos"].get("base", 0)
    var_ativos = 100 * (ativos_atual / ativos_base - 1) if ativos_base else None
    _metrica(linha1[2], "Clientes ativos", _milhar(ativos_atual),
             f"{_sinal(var_ativos)}% vs. ano anterior" if var_ativos is not None else None, direcional=True,
             ajuda="Households com ao menos uma compra nas últimas 8 semanas do período.")

    if "erro" not in seg:
        topo = max(seg["segmentos"], key=lambda s: s["valor_medio_usd"])
        _metrica(linha2[0], f"Parcela do faturamento: {topo['nome']}", f"{_pt(topo['pct_faturamento'])}%",
                 f"{_pt(topo['pct_households'])}% dos households")
    else:
        _metrica(linha2[0], "Parcela do faturamento dos Fiéis", "n/d")

    if "erro" not in clv:
        pr, t = clv["premissas"], clv["total"]
        _metrica(linha2[1], f"Margem esperada (premissa de {pr['margem'] * 100:.0f}%)",
                 _usd(t["clv_total_usd"]), f"IC 95%: {_usd(t['ic_95'][0])} a {_usd(t['ic_95'][1])}",
                 ajuda=f"Não é faturamento: é a margem de {pr['margem'] * 100:.0f}% (premissa, o dataset não tem custo) sobre o "
                       f"gasto esperado. A receita esperada é {_usd(t['receita_esperada_total_usd'])}.")
        linha2[1].caption(f"Margem em {pr['horizonte_semanas']} semanas, não faturamento.")
    else:
        _metrica(linha2[1], "Margem esperada em 52 semanas", "n/d")

    if "erro" not in churn:
        segs = churn["risco_por_segmento"]
        households = sum(s["households"] for s in segs)
        pausas = sum(s["pausas_esperadas"] for s in segs)
        _metrica(linha2[2], f"Pausa longa esperada ({churn['horizonte_semanas']} semanas)",
                 f"{_pt(100 * pausas / households)}%" if households else "n/d",
                 f"{_milhar(pausas)} de {_milhar(households)} ativos",
                 ajuda=f"{_milhar(sum(s['alertas'] for s in segs))} households em alerta hoje (limiar do modelo).")
        fora = ativos_atual - households
        if fora > 0:
            linha2[2].caption(f"O modelo avalia {_milhar(households)} dos {_milhar(ativos_atual)} ativos: "
                              f"{_milhar(fora)} têm menos de {CFG['analises']['churn']['historico_minimo_semanas']} semanas "
                              "de histórico e ficam fora.")
    else:
        _metrica(linha2[2], "Pausa longa esperada", "n/d")

    if "erro" not in desc:
        kw = desc["kruskal_wallis"]
        p_txt = "< 0,001" if kw["p_valor"] < 0.001 else _pt(kw["p_valor"], 3)
        with st.container(border=True):
            st.caption("Desconto entre segmentos")
            st.markdown(f"#### {FRASE_DESCONTO[desc['veredito']]}")
            st.caption(f"Teste de Kruskal-Wallis: p = {p_txt}; tamanho do efeito (eta²) = "
                       f"{_pt(max(0.0, kw['eta_quadrado_aprox']), 4)}.")
    else:
        with st.container(border=True):
            st.caption("Desconto entre segmentos")
            st.markdown("#### n/d")

    st.divider()
    esq1, dir1 = st.columns(2)
    esq2, dir2 = st.columns(2)
    if "erro" in seg:
        _erro(esq1, "Segmentos (RFM)", seg)
    else:
        _bloco(esq1, "Segmentos (RFM)", graficos.grafico_segmentos(seg["segmentos"], modo), seg["e_dai"])
    if "erro" in clv:
        _erro(dir1, "Valor do cliente (CLV)", clv)
    else:
        _bloco(dir1, "Valor do cliente (CLV)", graficos.grafico_clv(clv["segmentos"], modo), clv["e_dai"])
    if "erro" in churn:
        _erro(esq2, "Risco de pausa (churn)", churn)
    else:
        _bloco(esq2, "Risco de pausa (churn)",
               graficos.grafico_risco(churn["risco_por_segmento"], churn["horizonte_semanas"], modo), churn["e_dai"])
    if "erro" in desc:
        _erro(dir2, "Desconto por segmento", desc)
    else:
        _bloco(dir2, "Desconto por segmento",
               graficos.grafico_distribuicao(desc["grupos"], desc["veredito"], desc["impacto"]["taxa_geral_pct"], modo),
               desc["e_dai"])
