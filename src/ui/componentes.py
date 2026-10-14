"""Peças comuns das abas de análise: o bloco "e daí?" vem sempre primeiro, antes de qualquer gráfico."""

import re

import pandas as pd
import streamlit as st

ROTULOS_E_DAI = [("acao_recomendada", "Ação recomendada"), ("impacto_estimado", "Impacto estimado"),
                 ("limitacoes", "Limitações")]

_TRECHO_DE_CODIGO = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)


def md(texto: str) -> str:
    """Escapa o cifrão fora de trechos de código: dois "US$" no mesmo texto viram fórmula no markdown do Streamlit."""
    partes = _TRECHO_DE_CODIGO.split(texto)
    return "".join(p if i % 2 else re.sub(r"(?<!\\)\$", r"\\$", p) for i, p in enumerate(partes))


def bloco_e_dai(e_dai: dict) -> None:
    """Conclusão curta em destaque, a evidência em texto normal, ação, impacto e limitações; a estatística fica no expander."""
    st.subheader("E daí?")
    with st.container(border=True):
        st.markdown(md(f"### {e_dai['conclusao']}"))
        st.markdown(md(e_dai["evidencia"]))
        for chave, rotulo in ROTULOS_E_DAI:
            st.markdown(md(f"**{rotulo}.** {e_dai[chave]}"))
        with st.expander("Detalhes técnicos"):
            st.markdown(md("\n".join(f"- {d}" for d in e_dai["detalhes_tecnicos"])))


def tabela_do_grafico(df: pd.DataFrame, rotulo: str = "Ver os dados do gráfico") -> None:
    """A versão em tabela de cada gráfico: todo valor fica legível sem depender de cor ou de tooltip."""
    with st.expander(rotulo):
        st.dataframe(df, hide_index=True, width="stretch")


def metricas(itens: list[tuple[str, str]]) -> None:
    colunas = st.columns(len(itens))
    for coluna, (rotulo, valor) in zip(colunas, itens):
        coluna.metric(md(rotulo), md(valor))
