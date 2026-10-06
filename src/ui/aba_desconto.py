"""Aba "Desconto por segmento": o "e daí?" primeiro, depois os gráficos, o teste em si e as limitações."""

import pandas as pd
import streamlit as st

from src.nucleo import banco
from src.nucleo.teste_desconto import testar_desconto_entre_segmentos
from src.ui import cores, graficos
from src.ui.componentes import bloco_e_dai, metricas, tabela_do_grafico

VEREDITOS = {"sem_diferenca_detectavel": "Sem diferença detectável", "diferenca_desprezivel": "Diferença desprezível",
             "diferenca_relevante": "Diferença relevante"}


def _milhar(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def _pt(x: float, casas: int = 2) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _p(p: float) -> str:
    return "< 0,001" if p < 0.001 else _pt(p, 3)


def renderizar(caminho_banco) -> None:
    modo = cores.modo_atual()
    with st.spinner("Testando o desconto entre os segmentos (a primeira vez leva alguns segundos) ..."):
        with banco.usando(caminho_banco):
            r = testar_desconto_entre_segmentos()
    if "erro" in r:
        st.error(f"{r['erro']} {r.get('sugestao', '')}")
        return

    cfg, kw, sens, imp = r["parametros"], r["kruskal_wallis"], r["sensibilidade"], r["impacto"]
    bloco_e_dai(r["e_dai"])
    metricas([("Households comparados", _milhar(r["households"])),
              ("Kruskal-Wallis (p-valor)", _p(kw["p_valor"])),
              ("Tamanho do efeito (eta²)", _pt(max(0.0, kw["eta_quadrado_aprox"]), 4)),
              ("Veredito", VEREDITOS[r["veredito"]])])
    st.caption(f"Hipótese testada: {r['hipotese']} Métrica: {r['metrica']}.")

    st.markdown("#### Quanto desconto cada segmento recebe")
    st.altair_chart(graficos.grafico_distribuicao(r["grupos"], r["veredito"], imp["taxa_geral_pct"], modo), theme=None, width="stretch")
    st.caption("A taxa geral é a do valor bruto total (soma do desconto sobre soma do valor bruto); a mediana é a do % de cada household.")
    tabela_do_grafico(graficos.tabela_distribuicao(r["grupos"]))

    st.markdown("#### As diferenças entre pares são distinguíveis de zero?")
    st.altair_chart(graficos.grafico_pares(r["ic_diferencas"], cfg["diferenca_relevante_pp"], modo), theme=None, width="stretch")
    st.caption("Intervalos por bootstrap (2.000 reamostras, semente fixa), sem ajuste de Holm: servem para dimensionar a diferença, não para decidir significância.")
    tabela_do_grafico(graficos.tabela_pares(r["ic_diferencas"]))

    st.markdown("#### O resultado depende de quem comprou pouco?")
    st.altair_chart(graficos.grafico_sensibilidade(r["grupos"], sens["grupos"], sens["minimo_compras"], sens["kruskal_wallis"]["p_valor"],
                                                   sens["veredito"], modo), theme=None, width="stretch")
    st.caption(f"O % de desconto de quem comprou pouco vem de poucas cestas e varia muito. Repetir o teste só com households de "
               f"{sens['minimo_compras']} ou mais compras ({_milhar(sens['households'])} de {_milhar(r['households'])}) mostra se a diferença sobrevive.")
    tabela_do_grafico(graficos.tabela_sensibilidade(r["grupos"], sens["grupos"], sens["minimo_compras"]))

    with st.expander("Teste, post-hoc e limitações"):
        st.markdown(f"- **Teste geral:** Kruskal-Wallis, H = {_pt(kw['estatistica_H'])}, p {_p(kw['p_valor'])}, eta² = {_pt(kw['eta_quadrado_aprox'], 4)} "
                    f"({kw['n_grupos_testados']} grupos, {_milhar(kw['n_total_observacoes'])} households). Escolhido no lugar da ANOVA porque o % de desconto "
                    "é assimétrico e não normal (Shapiro abaixo).\n"
                    f"- **Veredito:** significância exige também efeito: eta² a partir de {_pt(100 * cfg['eta2_relevante'], 0)}% ou um par com "
                    f"{_pt(cfg['diferenca_relevante_pp'], 0)} pp ou mais de diferença de medianas e IC que exclui zero.\n"
                    f"- **Desconto total da janela:** US$ {_milhar(imp['desconto_total_usd'])} ({_pt(imp['taxa_geral_pct'], 1)}% do valor bruto).")
        st.markdown("**Normalidade por grupo (Shapiro-Wilk)**")
        st.dataframe(pd.DataFrame(r["normalidade_por_grupo"]).rename(columns={"segmento": "Segmento", "n": "Households", "shapiro_p_valor": "p-valor",
                                                                              "normal_a_5pct": "Normal a 5%?"}), hide_index=True, width="stretch")
        st.markdown("**Comparações par a par (Mann-Whitney com correção de Holm)**")
        if r["post_hoc_executado"]:
            st.dataframe(pd.DataFrame(r["post_hoc"]).rename(columns={"grupo_1": "Grupo 1", "grupo_2": "Grupo 2", "mediana_1": "Mediana 1 (%)",
                                                                     "mediana_2": "Mediana 2 (%)", "p_valor_bruto": "p bruto",
                                                                     "p_valor_ajustado": "p ajustado (Holm)", "significativo_5pct": "Significativo a 5%?"}),
                         hide_index=True, width="stretch")
        else:
            st.info(f"Não executado: {r['post_hoc_motivo']}.")
