"""Aba "Segmentos (RFM)": o "e daí?" primeiro, depois os gráficos e as escolhas estatísticas."""

import pandas as pd
import streamlit as st

from src.config import CFG
from src.nucleo import banco
from src.nucleo.rfm import coorte_retencao, segmentar_clientes
from src.ui import cores, graficos
from src.ui.componentes import bloco_e_dai, metricas, tabela_do_grafico


def _pt(x: float, casas: int = 2) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def renderizar(caminho_banco) -> None:
    modo = cores.modo_atual()
    with st.spinner("Calculando os segmentos (a primeira vez leva alguns segundos) ..."):
        with banco.usando(caminho_banco):
            r = segmentar_clientes()
            coorte = coorte_retencao(banco.cursor()) if "erro" not in r else None
    if "erro" in r:
        st.error(f"{r['erro']} {r.get('sugestao', '')}")
        return

    bloco_e_dai(r["e_dai"])

    est = r["estabilidade"]
    excluidos = sum(e["households"] for e in r["excluidos"])
    metricas([("Segmentos (K)", str(r["k_usado"])), ("Silhueta", _pt(r["silhueta"])),
              ("Estabilidade mínima (ARI)", _pt(min(est["ari_sementes_min"], est["ari_subamostras_min"]))),
              ("Households fora da análise", f"{excluidos:,}".replace(",", "."))])

    st.markdown("#### Quem são os clientes")
    st.altair_chart(graficos.grafico_segmentos(r["segmentos"], modo), theme=None, width="stretch")
    perfil = pd.DataFrame(r["segmentos"])[["nome", "households", "pct_households", "recencia_media_dias", "frequencia_media",
                                           "valor_medio_usd", "ticket_medio_usd", "pct_faturamento", "desconto_medio_pct"]]
    perfil.columns = ["Segmento", "Households", "% dos households", "Recência média (dias)", "Compras (média)",
                      "Valor médio (US$)", "Ticket médio (US$)", "% do faturamento", "Desconto médio (%)"]
    st.dataframe(perfil, hide_index=True, width="stretch")
    tabela_do_grafico(graficos.tabela_segmentos(r["segmentos"]))

    st.markdown("#### Por que K = " + str(r["k_usado"]))
    st.altair_chart(graficos.grafico_k(r["avaliacao_k"], r["k_usado"], CFG["analises"]["rfm"], modo), theme=None, width="stretch")
    st.caption(r["metodo_escolha_k"])
    tabela_do_grafico(graficos.tabela_k(r["avaliacao_k"], r["k_usado"], CFG["analises"]["rfm"]).drop(columns=["estado"]),
                      "Ver a avaliação de cada K")

    st.markdown("#### Retenção por coorte de entrada")
    if coorte and coorte["coortes"]:
        st.altair_chart(graficos.grafico_coorte(coorte["coortes"], modo), theme=None, width="stretch")
        st.caption(coorte["limitacao"])
        tabela_do_grafico(graficos.tabela_coorte(coorte["coortes"]))
    else:
        st.info("Não há coortes com households suficientes para mostrar a retenção.")

    with st.expander("Escolhas estatísticas e exclusões"):
        st.markdown(
            "- **Variáveis:** recência em dias; frequência e valor em `log1p` (o valor tem cauda longa); tudo padronizado.\n"
            f"- **K-Means** com semente fixa ({CFG['semente']}) e {CFG['analises']['rfm']['n_init']} inicializações.\n"
            f"- **Estabilidade:** {est['sementes']} sementes e {est['subamostras']} subamostras de "
            f"{int(est['fracao_subamostra'] * 100)}% (índice de Rand ajustado, ARI).\n"
            "- **Nomes:** derivados do perfil de cada segmento (recência alta = em pausa; os demais, por valor médio), "
            "nunca de uma lista fixa por ordem do cluster.")
        st.markdown("**Households fora da análise**")
        st.dataframe(pd.DataFrame(r["excluidos"]).rename(columns={"motivo": "Motivo", "households": "Households"}),
                     hide_index=True, width="stretch")
