"""Peças comuns das abas de análise: o bloco "e daí?" vem sempre primeiro, antes de qualquer gráfico."""

import pandas as pd
import streamlit as st

ROTULOS_E_DAI = [("conclusao", "Conclusão"), ("acao_recomendada", "Ação recomendada"),
                 ("impacto_estimado", "Impacto estimado"), ("limitacoes", "Limitações")]


def bloco_e_dai(e_dai: dict) -> None:
    """Conclusão, ação, impacto e limitações, no topo da aba. A conclusão fica em destaque."""
    st.subheader("E daí?")
    with st.container(border=True):
        st.markdown(f"### {e_dai['conclusao']}")
        for chave, rotulo in ROTULOS_E_DAI[1:]:
            st.markdown(f"**{rotulo}.** {e_dai[chave]}")


def tabela_do_grafico(df: pd.DataFrame, rotulo: str = "Ver os dados do gráfico") -> None:
    """A versão em tabela de cada gráfico: todo valor fica legível sem depender de cor ou de tooltip."""
    with st.expander(rotulo):
        st.dataframe(df, hide_index=True, width="stretch")


def metricas(itens: list[tuple[str, str]]) -> None:
    colunas = st.columns(len(itens))
    for coluna, (rotulo, valor) in zip(colunas, itens):
        coluna.metric(rotulo, valor)
