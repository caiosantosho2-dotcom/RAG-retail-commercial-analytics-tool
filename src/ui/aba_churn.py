"""Aba "Risco de pausa (churn)": o "e daí?" primeiro, depois os gráficos e a definição, a validação e as limitações."""

import pandas as pd
import streamlit as st

from src.nucleo import banco
from src.nucleo.churn import prever_churn
from src.ui import cores, graficos
from src.ui.componentes import bloco_e_dai, metricas, tabela_do_grafico


def _milhar(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def _pt(x: float, casas: int = 2) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def renderizar(caminho_banco) -> None:
    modo = cores.modo_atual()
    with st.spinner("Calculando o risco de pausa (a primeira vez leva alguns segundos) ..."):
        with banco.usando(caminho_banco):
            r = prever_churn()
    if "erro" in r:
        st.error(f"{r['erro']} {r.get('sugestao', '')}")
        return

    h = r["horizonte_semanas"]
    bloco_e_dai(r["e_dai"])
    segs = r["risco_por_segmento"]
    metricas([("Households ativos avaliados", _milhar(r["populacao_prevista"])),
              (f"Pausas esperadas em {h} semanas", _milhar(sum(s["pausas_esperadas"] for s in segs))),
              ("Em alerta hoje", _milhar(sum(s["alertas"] for s in segs))),
              ("AUC do modelo × regra simples", f"{_pt(r['auc_modelo'])} × {_pt(r['auc_baseline'])}")])

    st.markdown("#### Quem está em risco")
    st.altair_chart(graficos.grafico_risco(segs, h, modo), theme=None, width="stretch")
    tabela = graficos.tabela_risco(segs)
    st.dataframe(tabela.rename(columns={"segmento": "Segmento", "households": "Households", "risco_medio_pct": "Risco médio (%)",
                                        "pausas_esperadas": "Pausas esperadas", "pct_das_pausas": "% das pausas", "alertas": "Em alerta",
                                        "valor_em_risco_usd": "Faturamento em risco (US$)", "pct_do_valor_em_risco": "% do valor em risco"}),
                 hide_index=True, width="stretch")
    st.caption(f"{_milhar(r['ja_em_pausa']['households'])} households já estão sem comprar há {h} semanas ou mais: eles já estão em pausa "
               "e ficam fora da previsão. Faturamento em risco = risco x gasto semanal médio x " + str(h) + " semanas.")

    st.markdown("#### Quantos alertar: precisão e recall")
    st.altair_chart(graficos.grafico_limiar(r["curva_limiar"], modo), theme=None, width="stretch")
    st.caption("Quanto mais alto o limiar, menos alertas e mais deles se confirmam, mas mais pausas escapam. O limiar marcado maximiza o F1 "
               "na foto de validação; a gerência pode escolher outro conforme o custo de cada contato.")
    tabela_do_grafico(graficos.tabela_limiar(r["curva_limiar"]))

    st.markdown("#### O modelo ganha da regra simples?")
    m, b = r["modelo"], r["baseline"]
    comparacao = pd.DataFrame({"Medida": ["AUC", "AUC-PR (prevalência " + _pt(r["prevalencia_pct"]["teste"], 1) + "%)", "Precisão", "Recall", "F1", "Alertas no teste"],
                               "Modelo": [_pt(m["auc"], 3), _pt(m["auc_pr"], 3), _pt(m["precisao"]), _pt(m["recall"]), _pt(m["f1"]), _milhar(m["alertas"])],
                               "Regra simples": [_pt(b["auc"], 3), _pt(b["auc_pr"], 3), _pt(b["precisao"]), _pt(b["recall"]), _pt(b["f1"]), _milhar(b["alertas"])]})
    st.dataframe(comparacao, hide_index=True, width="stretch")
    lo, hi = r["diferenca_auc_ic"]
    st.caption(f"{r['baseline_descricao']}. Diferença de AUC: {_pt(r['diferenca_auc'], 3)} (IC de 95%: {_pt(lo, 3)} a {_pt(hi, 3)}, por household).")

    st.markdown("#### As probabilidades são confiáveis?")
    st.altair_chart(graficos.grafico_calibracao(r["calibracao"], modo), theme=None, width="stretch")
    tabela_do_grafico(graficos.tabela_calibracao(r["calibracao"]))

    st.markdown("#### O que pesa no risco")
    st.altair_chart(graficos.grafico_fatores(r["principais_fatores"], modo), theme=None, width="stretch")
    st.caption("Associação, não causa: mostra o que acompanha uma pausa, não o que a provoca. Os fatores são correlacionados entre si.")
    tabela_do_grafico(graficos.tabela_fatores(r["principais_fatores"]))

    with st.expander("Definição, validação e limitações"):
        ret = r["retorno_apos_pausa"]
        st.markdown(f"- **Definição:** {r['definicao_churn']}\n"
                    f"- **Treino:** {r['periodo_treino']}.\n- **Validação:** {r['periodo_validacao']}.\n- **Teste:** {r['periodo_teste']}.\n"
                    f"- **Linhas:** {_milhar(r['linhas']['treino'])} no treino e {_milhar(r['linhas']['teste'])} no teste (o mesmo household entra em várias fotos).\n"
                    f"- **Retorno depois da pausa:** {_pt(ret['taxa_pct'], 0)}% voltam a comprar em até {ret['janela_semanas']} semanas "
                    f"({_pt(ret['minimo_por_foto_pct'], 0)}% a {_pt(ret['maximo_por_foto_pct'], 0)}% conforme a foto; {_milhar(ret['pausas_observadas'])} pausas observadas).")
        cm = r["matriz_confusao"]
        st.markdown("**Matriz de confusão no teste**")
        st.dataframe(pd.DataFrame([{"Previsão": nome, "Verdadeiros negativos": c["tn"], "Falsos positivos": c["fp"], "Falsos negativos": c["fn"],
                                    "Verdadeiros positivos": c["tp"]} for nome, c in (("Modelo", cm["modelo"]), ("Regra simples", cm["baseline"]))]),
                     hide_index=True, width="stretch")
        st.markdown("**Households já em pausa (fora da previsão)**")
        st.dataframe(pd.DataFrame([{"Segmento": k, "Households": v} for k, v in r["ja_em_pausa"]["por_segmento"].items()]), hide_index=True, width="stretch")
