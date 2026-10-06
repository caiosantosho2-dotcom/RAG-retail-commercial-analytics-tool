"""Aba "Valor do cliente (CLV)": o "e daí?" primeiro, depois os gráficos, o backtest e as premissas."""

import pandas as pd
import streamlit as st

from src.nucleo import banco
from src.nucleo.clv import calcular_clv
from src.ui import cores, graficos
from src.ui.componentes import bloco_e_dai, metricas, tabela_do_grafico


def _usd(x: float) -> str:
    return "US$ " + f"{x:,.0f}".replace(",", ".")


def renderizar(caminho_banco) -> None:
    modo = cores.modo_atual()
    with st.spinner("Calculando o valor de cada grupo de clientes (a primeira vez leva alguns segundos) ..."):
        with banco.usando(caminho_banco):
            r = calcular_clv()
    if "erro" in r:
        st.error(f"{r['erro']} {r.get('sugestao', '')}")
        return

    bloco_e_dai(r["e_dai"])
    prem, total, bt = r["premissas"], r["total"], r["backtest"]
    metricas([("Valor esperado (margem, 52 semanas)", _usd(total["clv_total_usd"])),
              ("Receita esperada (52 semanas)", _usd(total["receita_esperada_total_usd"])),
              ("Margem assumida (premissa)", f"{prem['margem'] * 100:.0f}%"),
              ("Erro do backtest no total", f"{abs(bt['total']['erro_metodo_pct']):.1f}%".replace(".", ",") if bt else "n/d")])

    st.markdown("#### Quanto vale cada grupo")
    st.altair_chart(graficos.grafico_clv(r["segmentos"], modo), theme=None, width="stretch")
    st.caption("A linha preta é o intervalo de confiança de 95% (bootstrap de households). Ele cobre só a variação entre "
               "households, não a incerteza da margem nem a escolha dos segmentos.")
    tabela_do_grafico(graficos.tabela_clv(r["segmentos"]))

    st.markdown("#### Por que os grupos de menor gasto valem mais do que o gasto passado sugere")
    com_ritmo = [s for s in r["segmentos"] if s.get("ritmo_relativo") is not None]
    st.altair_chart(graficos.grafico_ritmo(com_ritmo, modo), theme=None, width="stretch")
    st.caption("Ritmo 1 = gastar nas próximas 52 semanas o mesmo ritmo das últimas 26. Grupos de gasto baixo numa janela tendem a "
               "voltar ao seu nível normal (regressão à média): parte do gasto baixo é acaso de calendário, não saída do cliente.")
    tabela_do_grafico(graficos.tabela_ritmo(com_ritmo))

    st.markdown("#### O método acerta? Teste em 26 semanas")
    if bt:
        st.altair_chart(graficos.grafico_backtest(bt, modo), theme=None, width="stretch")
        st.caption(f"Calibração: {bt['calibracao']}. Teste: {bt['teste']}. Por household, o erro absoluto médio do método foi "
                   f"{_usd(bt['mae_household_metodo_usd'])} contra {_usd(bt['mae_household_ingenuo_usd'])} da regra ingênua: o valor serve "
                   "como média de grupo, não como previsão individual.")
        tabela_do_grafico(graficos.tabela_backtest(bt))
    else:
        st.info("Não há semanas observadas suficientes para o backtest.")

    with st.expander("Premissas e método"):
        st.markdown(f"- **Método:** {prem['metodo']}.\n"
                    f"- **Janela atual:** {prem['janela_atual']}; **calibração (um ano antes):** {prem['janela_calibracao']}; "
                    f"**semanas futuras observadas:** {prem['semanas_futuras_observadas']}.\n"
                    f"- **Margem:** {prem['margem'] * 100:.0f}% é premissa (o dataset não tem custo); o CLV escala linearmente com ela.\n"
                    f"- **{prem['grupo_sem_compra']}.**\n"
                    f"- **Desconto financeiro:** {prem['desconto_financeiro']}.\n"
                    f"- **Bootstrap:** {prem['bootstrap']['reamostras']} reamostras, nível {prem['bootstrap']['nivel'] * 100:.0f}%, semente "
                    f"{prem['bootstrap']['semente']}.")
        for aviso in r["avisos"]:
            st.warning(aviso)
        st.markdown("**Gasto usado na calibração**")
        st.dataframe(pd.DataFrame([{"Grupo": s["nome"], "Households": s["calibracao"]["households"],
                                    "Gasto passado (US$)": s["calibracao"]["gasto_passado_usd"],
                                    "Gasto nas 52 semanas seguintes (US$)": s["calibracao"]["gasto_futuro_usd"]}
                                   for s in r["segmentos"]]), hide_index=True, width="stretch")
