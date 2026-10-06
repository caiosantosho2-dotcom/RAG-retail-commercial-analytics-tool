"""Gráficos das abas de análise (Altair), no padrão da skill de visualização.

Regras que valem para todos: o título diz a conclusão (a descrição vai nos eixos e na legenda); marcas finas com
ponta arredondada de 4 px e vão de 2 px na cor da superfície; grade em fio recessivo; rótulos seletivos; legenda
sempre que há 2 ou mais séries; tooltip em toda marca; cores validadas (app/cores.py) nos dois modos; cada gráfico
tem uma versão em tabela (componentes.tabela_do_grafico). Forma: emphasis (um destaque, o resto cinza) em vez de
várias cores quando uma série é o ponto; sequencial de um matiz para magnitude.
"""

import math

import altair as alt
import pandas as pd

from src.ui import cores

SERIE_HH, SERIE_FAT = "% dos households", "% do faturamento"


def _base(grafico, modo: str):
    t = cores.TINTA[modo]
    return (grafico.configure(background="transparent")
            .configure_view(stroke=None)
            .configure_axis(labelColor=t["muda"], titleColor=t["secundaria"], gridColor=t["grade"], domainColor=t["base"],
                            tickColor=t["base"], labelFontSize=12, titleFontSize=12, gridWidth=1)
            .configure_title(color=t["primaria"], fontSize=15, fontWeight=600, anchor="start", offset=14)
            .configure_legend(labelColor=t["secundaria"], titleColor=t["secundaria"], orient="top", symbolType="square",
                              labelFontSize=12, padding=0)
            .configure_text(color=t["primaria"]))


def _pt(x: float, casas: int = 0) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


# --------------------------------------------------------------------------- segmentos

def tabela_segmentos(segmentos: list[dict]) -> pd.DataFrame:
    """Uma linha por segmento e série (households, faturamento): é o que o gráfico desenha e a tabela mostra."""
    linhas = []
    for s in segmentos:
        linhas.append({"segmento": s["nome"], "serie": SERIE_HH, "pct": s["pct_households"], "households": s["households"],
                       "valor_usd": s["valor_total_usd"]})
        linhas.append({"segmento": s["nome"], "serie": SERIE_FAT, "pct": s["pct_faturamento"], "households": s["households"],
                       "valor_usd": s["valor_total_usd"]})
    return pd.DataFrame(linhas)


def titulo_segmentos(segmentos: list[dict]) -> str:
    topo = max(segmentos, key=lambda s: s["valor_medio_usd"])
    return (f"{topo['nome']} são {_pt(topo['pct_households'])}% dos clientes e geram "
            f"{_pt(topo['pct_faturamento'])}% do faturamento")


def grafico_segmentos(segmentos: list[dict], modo: str):
    df = tabela_segmentos(segmentos)
    ordem = [s["nome"] for s in segmentos]
    topo = max(segmentos, key=lambda s: s["valor_medio_usd"])["nome"]
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    series = [SERIE_HH, SERIE_FAT]
    cor = alt.Color("serie:N", scale=alt.Scale(domain=series, range=[cores.CINZA[modo], cores.DESTAQUE[modo]]),
                    legend=alt.Legend(title=None))
    y = alt.Y("segmento:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=220, labelColor=tinta["secundaria"], ticks=False))
    desloc = alt.YOffset("serie:N", sort=series)
    limite = math.ceil((df["pct"].max() + 5) / 10) * 10   # folga para o rótulo; sem 30% de eixo vazio
    x = alt.X("pct:Q", title="% do total da janela", scale=alt.Scale(domain=[0, limite]),
              axis=alt.Axis(format=".0f", tickCount=5))
    barras = alt.Chart(df).mark_bar(cornerRadiusEnd=4, size=14, stroke=sup, strokeWidth=2).encode(
        y=y, yOffset=desloc, x=x, color=cor,
        tooltip=[alt.Tooltip("segmento:N", title="Segmento"), alt.Tooltip("serie:N", title="Série"),
                 alt.Tooltip("pct:Q", title="%", format=".1f"), alt.Tooltip("households:Q", title="Households", format=","),
                 alt.Tooltip("valor_usd:Q", title="Faturamento da janela (US$)", format=",.0f")])
    rotulos = alt.Chart(df[df["segmento"] == topo].assign(rotulo=lambda d: d["pct"].map(lambda v: f"{_pt(v)}%"))).mark_text(
        align="left", dx=6, fontSize=12, fontWeight=600).encode(y=y, yOffset=desloc, x=x, text="rotulo:N")
    grafico = alt.layer(barras, rotulos).properties(title=titulo_segmentos(segmentos), height=46 * len(segmentos) + 30, width="container")
    return _base(grafico, modo)


# --------------------------------------------------------------------------- escolha de K

def tabela_k(avaliacao: list[dict], k_usado: int, cfg: dict) -> pd.DataFrame:
    df = pd.DataFrame(avaliacao)
    df["passou_na_regra"] = ((df["k"] >= cfg["k_min"]) & (df["ari_sementes_min"] >= cfg["ari_minimo"])
                             & (df["ari_subamostras_min"] >= cfg["ari_minimo"])
                             & (df["menor_segmento_pct"] >= cfg["tamanho_minimo_pct"]) & (df["silhueta"] >= cfg["silhueta_minima"]))
    df["estado"] = df["k"].map(lambda k: "K escolhido" if k == k_usado else "Demais K")
    return df


def titulo_k(df: pd.DataFrame, k_usado: int) -> str:
    k_sil = int(df.loc[df["silhueta"].idxmax(), "k"])
    if k_sil == k_usado:
        return f"K={k_usado} tem a maior silhueta e passa na regra de estabilidade e tamanho"
    return f"A silhueta sozinha escolheria K={k_sil}; só K={k_usado} passa na regra de estabilidade e tamanho"


def grafico_k(avaliacao: list[dict], k_usado: int, cfg: dict, modo: str):
    df = tabela_k(avaliacao, k_usado, cfg)
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    x = alt.X("k:O", title="Número de segmentos (K)", axis=alt.Axis(labelAngle=0))
    y = alt.Y("silhueta:Q", title="Silhueta (quanto maior, mais separados)", scale=alt.Scale(domain=[0, round(df["silhueta"].max() + 0.1, 1)]))
    linha = alt.Chart(df).mark_line(color=cores.CINZA[modo], strokeWidth=2).encode(x=x, y=y)
    cor = alt.Color("estado:N", scale=alt.Scale(domain=["K escolhido", "Demais K"], range=[cores.DESTAQUE[modo], cores.CINZA[modo]]),
                    legend=alt.Legend(title=None))
    pontos = alt.Chart(df).mark_point(filled=True, size=110, stroke=sup, strokeWidth=2, opacity=1).encode(
        x=x, y=y, color=cor,
        tooltip=[alt.Tooltip("k:O", title="K"), alt.Tooltip("silhueta:Q", title="Silhueta", format=".3f"),
                 alt.Tooltip("ari_sementes_min:Q", title="ARI mínima (sementes)", format=".2f"),
                 alt.Tooltip("ari_subamostras_min:Q", title="ARI mínima (subamostras)", format=".2f"),
                 alt.Tooltip("menor_segmento_pct:Q", title="Menor segmento (%)", format=".1f"),
                 alt.Tooltip("passou_na_regra:N", title="Passou na regra")])
    minimo = alt.Chart(pd.DataFrame({"y": [cfg["silhueta_minima"]]})).mark_rule(color=tinta["base"], strokeWidth=1).encode(y="y:Q")
    rotulo = alt.Chart(df[df["k"] == k_usado].assign(t=lambda d: d["k"].map(lambda k: f"K={k}"))).mark_text(
        dy=-16, fontSize=12, fontWeight=600).encode(x=x, y=y, text="t:N")
    nome_minimo = alt.Chart(pd.DataFrame({"k": [int(df["k"].max())], "y": [cfg["silhueta_minima"]],
                                          "t": [f"mínimo da regra: {_pt(cfg['silhueta_minima'], 2)}"]})).mark_text(
        align="right", dy=12, fontSize=11, color=tinta["muda"]).encode(x=x, y="y:Q", text="t:N")
    grafico = alt.layer(minimo, linha, pontos, rotulo, nome_minimo).properties(title=titulo_k(df, k_usado), height=260, width="container")
    return _base(grafico, modo)


# --------------------------------------------------------------------------- coorte

def tabela_coorte(coortes: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"coorte": c["coorte"], "households": c["households"], "bloco_depois_da_entrada": lag, "pct": pct}
                         for c in coortes for lag, pct in c["retencao_pct"].items()])


def titulo_coorte(df: pd.DataFrame) -> str:
    media = df["pct"].mean()
    cedo, tarde = df[df["bloco_depois_da_entrada"] <= 4]["pct"].mean(), df[df["bloco_depois_da_entrada"] >= df["bloco_depois_da_entrada"].max() - 3]["pct"].mean()
    if abs(cedo - tarde) <= 3:
        return f"A retenção é estável: cerca de {_pt(media)}% de cada coorte volta a comprar a cada bloco de 4 semanas"
    sentido = "cai" if tarde < cedo else "sobe"
    return f"A retenção {sentido} de {_pt(cedo)}% para {_pt(tarde)}% ao longo do tempo"


def grafico_coorte(coortes: list[dict], modo: str):
    df = tabela_coorte(coortes)
    ordem = [c["coorte"] for c in coortes]
    sup = cores.SUPERFICIE[modo]
    celulas = alt.Chart(df).mark_rect(stroke=sup, strokeWidth=2, cornerRadius=2).encode(
        x=alt.X("bloco_depois_da_entrada:O", title="Blocos de 4 semanas depois da entrada", axis=alt.Axis(labelAngle=0, labelOverlap=True)),
        y=alt.Y("coorte:N", sort=ordem, title="Coorte (semanas de entrada)", axis=alt.Axis(ticks=False)),
        color=alt.Color("pct:Q", scale=alt.Scale(domain=[0, 100], range=cores.rampa_sequencial(modo)),
                        legend=alt.Legend(title="% do coorte que comprou", orient="top", gradientLength=220)),
        tooltip=[alt.Tooltip("coorte:N", title="Coorte"), alt.Tooltip("households:Q", title="Households no coorte"),
                 alt.Tooltip("bloco_depois_da_entrada:O", title="Bloco depois da entrada"),
                 alt.Tooltip("pct:Q", title="% que comprou", format=".1f")])
    grafico = celulas.properties(title=titulo_coorte(df), height=36 * len(ordem) + 40, width="container")
    return _base(grafico, modo)
