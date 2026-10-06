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


def _eixo_pt(formato: str, **opcoes) -> alt.Axis:
    """Eixo numérico com rótulos no formato brasileiro (vírgula decimal, ponto de milhar). O Vega usa o formato
    americano por padrão e o Streamlit não expõe o locale, então os rótulos são trocados por expressão."""
    expr = f"replace(replace(replace(format(datum.value, '{formato}'), ',', '#'), '.', ','), '#', '.')"
    return alt.Axis(labelExpr=expr, **opcoes)


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
    y = alt.Y("silhueta:Q", title="Silhueta (quanto maior, mais separados)", scale=alt.Scale(domain=[0, round(df["silhueta"].max() + 0.1, 1)]),
              axis=_eixo_pt(".1f"))
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


# --------------------------------------------------------------------------- CLV

SERIE_METODO, SERIE_INGENUA = "Método da razão", "Repetir o último período"


def tabela_clv(segs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"segmento": s["nome"], "households": s["n"], "clv_medio_usd": s["clv_medio"], "ic_inferior": s["ic_95"][0],
                          "ic_superior": s["ic_95"][1], "clv_total_usd": s["clv_total_usd"]} for s in segs])


def titulo_clv(segs: list[dict]) -> str:
    ordem = sorted(segs, key=lambda s: -s["clv_medio"])
    topo, segundo = ordem[0], ordem[1]
    return (f"Um household do grupo {topo['nome']} vale US$ {_pt(topo['clv_medio'])} em 52 semanas, "
            f"{_pt(topo['clv_medio'] / segundo['clv_medio'], 1)}x um do grupo {segundo['nome']}")


def grafico_clv(segs: list[dict], modo: str):
    df = tabela_clv(segs)
    ordem = list(df.sort_values("clv_medio_usd", ascending=False)["segmento"])
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    y = alt.Y("segmento:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=240, labelColor=tinta["secundaria"], ticks=False))
    x = alt.X("clv_medio_usd:Q", title="CLV por household em 52 semanas (US$, margem assumida)",
              scale=alt.Scale(domain=[0, math.ceil(df["ic_superior"].max() * 1.12 / 100) * 100]), axis=_eixo_pt(",.0f", tickCount=5))
    tooltip = [alt.Tooltip("segmento:N", title="Grupo"), alt.Tooltip("households:Q", title="Households", format=","),
               alt.Tooltip("clv_medio_usd:Q", title="CLV médio (US$)", format=",.0f"),
               alt.Tooltip("ic_inferior:Q", title="IC 95% inferior", format=",.0f"), alt.Tooltip("ic_superior:Q", title="IC 95% superior", format=",.0f"),
               alt.Tooltip("clv_total_usd:Q", title="CLV total do grupo (US$)", format=",.0f")]
    barras = alt.Chart(df).mark_bar(cornerRadiusEnd=4, size=16, color=cores.DESTAQUE[modo], stroke=sup, strokeWidth=2).encode(y=y, x=x, tooltip=tooltip)
    intervalo = alt.Chart(df).mark_rule(strokeWidth=2, color=tinta["primaria"]).encode(
        y=y, x=alt.X("ic_inferior:Q"), x2="ic_superior:Q", tooltip=tooltip)
    topo = df[df["segmento"] == ordem[0]].assign(rotulo=lambda d: d["clv_medio_usd"].map(lambda v: f"US$ {_pt(v)}"))
    rotulo = alt.Chart(topo).mark_text(align="left", dx=8, fontSize=12, fontWeight=600).encode(y=y, x=alt.X("ic_superior:Q"), text="rotulo:N")
    grafico = alt.layer(barras, intervalo, rotulo).properties(title=titulo_clv(segs), height=44 * len(df) + 30, width="container")
    return _base(grafico, modo)


def tabela_ritmo(segs: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"segmento": s["nome"], "ritmo": s["ritmo_relativo"], "ic_inferior": s["razao_ic_95"][0] / 2,
                          "ic_superior": s["razao_ic_95"][1] / 2, "razao_futuro_passado": s["razao_futuro_passado"]}
                         for s in segs if s.get("ritmo_relativo") is not None])


def titulo_ritmo(df: pd.DataFrame) -> str:
    acima = df[df["ritmo"] > 1.3].sort_values("ritmo", ascending=False)
    abaixo = df[df["ritmo"] <= 1.3].sort_values("ritmo")
    if len(acima) and len(abaixo):
        return (f"{' e '.join(acima['segmento'])} gastam {_pt(acima['ritmo'].mean(), 1)}x o ritmo atual nas semanas seguintes; "
                f"{abaixo.iloc[0]['segmento']}, {_pt(abaixo.iloc[0]['ritmo'], 2)}x")
    return "O gasto das semanas seguintes fica perto do ritmo atual em todos os grupos"


def grafico_ritmo(segs: list[dict], modo: str):
    df = tabela_ritmo(segs)
    ordem = list(df["segmento"])
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    y = alt.Y("segmento:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=240, labelColor=tinta["secundaria"], ticks=False))
    x = alt.X("ritmo:Q", title="Ritmo de gasto nas 52 semanas seguintes ÷ ritmo das últimas 26 semanas (1 = igual)",
              scale=alt.Scale(domain=[0, math.ceil(df["ic_superior"].max() * 1.15 * 2) / 2]), axis=_eixo_pt(".1f", tickCount=5))
    tooltip = [alt.Tooltip("segmento:N", title="Grupo"), alt.Tooltip("ritmo:Q", title="Ritmo relativo", format=".2f"),
               alt.Tooltip("ic_inferior:Q", title="IC 95% inferior", format=".2f"), alt.Tooltip("ic_superior:Q", title="IC 95% superior", format=".2f"),
               alt.Tooltip("razao_futuro_passado:Q", title="Razão (52 sem ÷ 26 sem)", format=".2f")]
    referencia = alt.Chart(pd.DataFrame({"x": [1.0]})).mark_rule(color=tinta["base"], strokeWidth=1).encode(x="x:Q")
    # Mesmo campo e mesma escala do eixo y das outras camadas: com campos diferentes o Vega-Lite funde as escalas
    # e perde a ordem dos grupos.
    nome_ref = alt.Chart(pd.DataFrame({"x": [1.0], "t": ["igual ao ritmo atual"], "segmento": [ordem[-1]]})).mark_text(
        align="left", dx=6, dy=-16, fontSize=11, color=tinta["muda"]).encode(x="x:Q", y=y, text="t:N")
    intervalo = alt.Chart(df).mark_rule(strokeWidth=2, color=cores.CINZA[modo]).encode(y=y, x="ic_inferior:Q", x2="ic_superior:Q", tooltip=tooltip)
    pontos = alt.Chart(df).mark_point(filled=True, size=130, color=cores.DESTAQUE[modo], stroke=sup, strokeWidth=2, opacity=1).encode(y=y, x=x, tooltip=tooltip)
    grafico = alt.layer(referencia, nome_ref, intervalo, pontos).properties(title=titulo_ritmo(df), height=44 * len(df) + 40, width="container")
    return _base(grafico, modo)


def tabela_backtest(bt: dict) -> pd.DataFrame:
    linhas = [{"grupo": l["nome"], "households": l["households"], "previsto_metodo_usd": l["previsto_metodo_usd"],
               "previsto_ingenuo_usd": l["previsto_ingenuo_usd"], "real_usd": l["real_usd"],
               "erro_metodo_pct": l["erro_metodo_pct"], "erro_ingenuo_pct": l["erro_ingenuo_pct"]} for l in bt["segmentos"]]
    t = bt["total"]
    linhas.append({"grupo": "Total", "households": sum(l["households"] for l in bt["segmentos"]), "previsto_metodo_usd": t["previsto_metodo_usd"],
                   "previsto_ingenuo_usd": t["previsto_ingenuo_usd"], "real_usd": t["real_usd"], "erro_metodo_pct": t["erro_metodo_pct"],
                   "erro_ingenuo_pct": t["erro_ingenuo_pct"]})
    return pd.DataFrame(linhas)


def titulo_backtest(bt: dict) -> str:
    t = bt["total"]
    return (f"No teste de {bt['horizonte_semanas']} semanas o método errou {_pt(abs(t['erro_metodo_pct']), 1)}% no total; "
            f"repetir o último período, {_pt(abs(t['erro_ingenuo_pct']), 1)}%")


def grafico_backtest(bt: dict, modo: str):
    df = tabela_backtest(bt)
    ordem = list(df["grupo"])
    longo = pd.concat([df.assign(serie=SERIE_METODO, erro=df["erro_metodo_pct"]), df.assign(serie=SERIE_INGENUA, erro=df["erro_ingenuo_pct"])])
    longo = longo.dropna(subset=["erro"])
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    series = [SERIE_INGENUA, SERIE_METODO]
    cor = alt.Color("serie:N", scale=alt.Scale(domain=series, range=[cores.CINZA[modo], cores.DESTAQUE[modo]]), legend=alt.Legend(title=None))
    y = alt.Y("grupo:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=240, labelColor=tinta["secundaria"], ticks=False))
    desloc = alt.YOffset("serie:N", sort=series)
    minimo, maximo = float(longo["erro"].min()), float(longo["erro"].max())
    x = alt.X("erro:Q", title="Erro da previsão (%)  ·  negativo = previu menos que o real",
              scale=alt.Scale(domain=[math.floor((minimo - 8) / 10) * 10, math.ceil((maximo + 8) / 10) * 10]), axis=alt.Axis(format=".0f", tickCount=6))
    tooltip = [alt.Tooltip("grupo:N", title="Grupo"), alt.Tooltip("serie:N", title="Previsão"), alt.Tooltip("erro:Q", title="Erro (%)", format=".1f"),
               alt.Tooltip("real_usd:Q", title="Real (US$)", format=",.0f"), alt.Tooltip("households:Q", title="Households", format=",")]
    barras = alt.Chart(longo).mark_bar(cornerRadius=4, size=12, stroke=sup, strokeWidth=2).encode(y=y, yOffset=desloc, x=x, color=cor, tooltip=tooltip)
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(color=tinta["base"], strokeWidth=1).encode(x="x:Q")
    total = longo[longo["grupo"] == "Total"].assign(rotulo=lambda d: d["erro"].map(lambda v: f"{_pt(v, 1)}%"))
    # O rótulo fica fora da ponta da barra: à esquerda quando o erro é negativo, à direita quando é positivo.
    rotulo = alt.Chart(total).mark_text(
        align=alt.expr("datum.erro < 0 ? 'right' : 'left'"), dx=alt.expr("datum.erro < 0 ? -6 : 6"), fontSize=12, fontWeight=600
    ).encode(y=y, yOffset=desloc, x="erro:Q", text="rotulo:N")
    grafico = alt.layer(zero, barras, rotulo).properties(title=titulo_backtest(bt), height=52 * len(df) + 40, width="container")
    return _base(grafico, modo)


# --------------------------------------------------------------------------- churn (pausa longa)

def tabela_risco(segs: list[dict]) -> pd.DataFrame:
    total_p = sum(s["pausas_esperadas"] for s in segs) or 1.0
    total_v = sum(s["valor_em_risco_usd"] for s in segs) or 1.0
    return pd.DataFrame([{"segmento": s["nome"], "households": s["households"], "risco_medio_pct": s["risco_medio_pct"],
                          "pausas_esperadas": s["pausas_esperadas"], "pct_das_pausas": 100 * s["pausas_esperadas"] / total_p,
                          "alertas": s["alertas"], "valor_em_risco_usd": s["valor_em_risco_usd"],
                          "pct_do_valor_em_risco": 100 * s["valor_em_risco_usd"] / total_v} for s in segs])


def titulo_risco(df: pd.DataFrame, horizonte: int) -> str:
    alto, baixo = df.loc[df["risco_medio_pct"].idxmax()], df.loc[df["risco_medio_pct"].idxmin()]
    return (f"{alto['segmento']} têm {_pt(alto['risco_medio_pct'], 1)}% de risco de ficar {horizonte} semanas sem comprar; "
            f"{baixo['segmento']}, {_pt(baixo['risco_medio_pct'], 1)}%")


def grafico_risco(segs: list[dict], horizonte: int, modo: str):
    df = tabela_risco(segs)
    ordem = list(df["segmento"])
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    y = alt.Y("segmento:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=240, labelColor=tinta["secundaria"], ticks=False))
    x = alt.X("risco_medio_pct:Q", title=f"Risco médio de ficar {horizonte} semanas sem comprar (%)",
              scale=alt.Scale(domain=[0, math.ceil((df["risco_medio_pct"].max() * 1.25) / 5) * 5]), axis=alt.Axis(format=".0f", tickCount=5))
    tooltip = [alt.Tooltip("segmento:N", title="Segmento"), alt.Tooltip("households:Q", title="Households ativos", format=","),
               alt.Tooltip("risco_medio_pct:Q", title="Risco médio (%)", format=".1f"), alt.Tooltip("pausas_esperadas:Q", title="Pausas esperadas", format=".0f"),
               alt.Tooltip("pct_das_pausas:Q", title="% das pausas", format=".0f"), alt.Tooltip("alertas:Q", title="Em alerta hoje", format=","),
               alt.Tooltip("valor_em_risco_usd:Q", title="Faturamento em risco (US$)", format=",.0f"),
               alt.Tooltip("pct_do_valor_em_risco:Q", title="% do valor em risco", format=".0f")]
    barras = alt.Chart(df).mark_bar(cornerRadiusEnd=4, size=18, color=cores.DESTAQUE[modo], stroke=sup, strokeWidth=2).encode(y=y, x=x, tooltip=tooltip)
    rotulos = alt.Chart(df.assign(rotulo=lambda d: d["risco_medio_pct"].map(lambda v: f"{_pt(v, 1)}%"))).mark_text(
        align="left", dx=6, fontSize=12, fontWeight=600).encode(y=y, x="risco_medio_pct:Q", text="rotulo:N")
    grafico = alt.layer(barras, rotulos).properties(title=titulo_risco(df, horizonte), height=52 * len(df) + 30, width="container")
    return _base(grafico, modo)


SERIE_PRECISAO, SERIE_RECALL = "Precisão (alertas que se confirmam)", "Recall (pausas que o alerta pega)"


def tabela_limiar(curva: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"limiar": c["limiar"], "precisao_pct": 100 * c["precisao"], "recall_pct": 100 * c["recall"], "alertas_no_teste": c["alertas"],
                          "escolhido": c["escolhido"]} for c in curva])


def titulo_limiar(curva: list[dict]) -> str:
    c = next(x for x in curva if x["escolhido"])
    return (f"No limiar {_pt(c['limiar'], 2)}, {_pt(100 * c['precisao'])}% dos alertas se confirmam e {_pt(100 * c['recall'])}% das pausas são pegas; "
            "subir o limiar troca recall por precisão")


def grafico_limiar(curva: list[dict], modo: str):
    df = tabela_limiar(curva)
    longo = pd.concat([df.assign(serie=SERIE_PRECISAO, pct=df["precisao_pct"]), df.assign(serie=SERIE_RECALL, pct=df["recall_pct"])])
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    series = [SERIE_PRECISAO, SERIE_RECALL]
    cor = alt.Color("serie:N", scale=alt.Scale(domain=series, range=cores.CATEGORICA[modo][:2]), legend=alt.Legend(title=None, labelLimit=320))
    x = alt.X("limiar:Q", title="Limiar de risco para disparar o alerta", axis=_eixo_pt(".2f", values=list(df["limiar"])))
    y = alt.Y("pct:Q", title="%", scale=alt.Scale(domain=[0, 100]))
    tooltip = [alt.Tooltip("limiar:Q", title="Limiar", format=".2f"), alt.Tooltip("serie:N", title="Medida"), alt.Tooltip("pct:Q", title="%", format=".1f"),
               alt.Tooltip("alertas_no_teste:Q", title="Alertas no teste", format=",")]
    linhas = alt.Chart(longo).mark_line(strokeWidth=2).encode(x=x, y=y, color=cor)
    pontos = alt.Chart(longo).mark_point(filled=True, size=80, stroke=sup, strokeWidth=2, opacity=1).encode(x=x, y=y, color=cor, tooltip=tooltip)
    escolhido = df[df["escolhido"]]
    regua = alt.Chart(escolhido).mark_rule(color=tinta["base"], strokeWidth=1).encode(x="limiar:Q")
    nome = alt.Chart(escolhido.assign(t="limiar escolhido (F1 máximo na validação)")).mark_text(
        align="left", dx=6, dy=-6, fontSize=11, color=tinta["muda"]).encode(x="limiar:Q", y=alt.value(12), text="t:N")
    grafico = alt.layer(regua, nome, linhas, pontos).properties(title=titulo_limiar(curva), height=280, width="container")
    return _base(grafico, modo)


def tabela_calibracao(cal: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(cal)


def titulo_calibracao(cal: list[dict]) -> str:
    topo = cal[-1]
    dif = max(abs(d["previsto_pct"] - d["observado_pct"]) for d in cal)
    if dif <= 4:
        return (f"As probabilidades são confiáveis: no decil de maior risco o modelo previu {_pt(topo['previsto_pct'], 1)}% "
                f"e observou {_pt(topo['observado_pct'], 1)}%")
    return f"As probabilidades se afastam do observado em até {_pt(dif, 1)} pontos: use o modelo só para ordenar"


def grafico_calibracao(cal: list[dict], modo: str):
    df = tabela_calibracao(cal)
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    teto = math.ceil(max(df["previsto_pct"].max(), df["observado_pct"].max()) * 1.15 / 5) * 5
    escala = alt.Scale(domain=[0, teto])
    x = alt.X("previsto_pct:Q", title="Risco previsto pelo modelo (%)", scale=escala, axis=alt.Axis(format=".0f"))
    y = alt.Y("observado_pct:Q", title="Pausas observadas (%)", scale=escala, axis=alt.Axis(format=".0f"))
    tooltip = [alt.Tooltip("decil:Q", title="Decil de risco (10 = maior)"), alt.Tooltip("households:Q", title="Households", format=","),
               alt.Tooltip("previsto_pct:Q", title="Previsto (%)", format=".1f"), alt.Tooltip("observado_pct:Q", title="Observado (%)", format=".1f")]
    diagonal = alt.Chart(pd.DataFrame({"a": [0, teto], "b": [0, teto]})).mark_line(color=tinta["base"], strokeWidth=1).encode(
        x=alt.X("a:Q", scale=escala), y=alt.Y("b:Q", scale=escala))
    pontos = alt.Chart(df).mark_point(filled=True, size=110, color=cores.DESTAQUE[modo], stroke=sup, strokeWidth=2, opacity=1).encode(x=x, y=y, tooltip=tooltip)
    # O rótulo fica logo acima da diagonal, perto da ponta, e não flutuando no meio do gráfico.
    nome = alt.Chart(pd.DataFrame({"a": [teto * 0.74], "b": [teto * 0.74], "t": ["calibração perfeita"]})).mark_text(
        align="right", dx=-4, dy=-9, fontSize=11, color=tinta["muda"]).encode(x=alt.X("a:Q", scale=escala), y=alt.Y("b:Q", scale=escala), text="t:N")
    grafico = alt.layer(diagonal, nome, pontos).properties(title=titulo_calibracao(cal), height=300, width="container")
    return _base(grafico, modo)


def tabela_fatores(fatores: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"fator": f["descricao"], "efeito": f["efeito"], "odds_ratio_por_dp": f["odds_ratio_por_dp"],
                          "coeficiente_padronizado": f["coeficiente_padronizado"], "leitura": f["leitura"]} for f in fatores])


def titulo_fatores(fatores: list[dict]) -> str:
    f = fatores[0]
    movimento = "o risco cai para" if f["odds_ratio_por_dp"] < 1 else "o risco sobe para"
    return (f"O maior sinal é \"{f['descricao']}\": a cada desvio-padrão a mais, {movimento} {_pt(f['odds_ratio_por_dp'], 2)}x")


def grafico_fatores(fatores: list[dict], modo: str):
    df = tabela_fatores(fatores).assign(rotulo=lambda d: d["odds_ratio_por_dp"].map(lambda v: f"{_pt(v, 2)}x"))
    ordem = list(df["fator"])
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    y = alt.Y("fator:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=360, labelColor=tinta["secundaria"], ticks=False))
    x = alt.X("odds_ratio_por_dp:Q", title="Odds de pausar por desvio-padrão do fator (1 = sem efeito)",
              scale=alt.Scale(domain=[round(max(0.0, df["odds_ratio_por_dp"].min() - 0.15), 1), round(df["odds_ratio_por_dp"].max() + 0.3, 1)]),
              axis=_eixo_pt(".1f", tickCount=6))
    tooltip = [alt.Tooltip("fator:N", title="Fator"), alt.Tooltip("efeito:N", title="Efeito"), alt.Tooltip("odds_ratio_por_dp:Q", title="Odds ratio", format=".2f"),
               alt.Tooltip("leitura:N", title="Leitura")]
    referencia = alt.Chart(pd.DataFrame({"x": [1.0]})).mark_rule(color=tinta["base"], strokeWidth=1).encode(x="x:Q")
    pontos = alt.Chart(df).mark_point(filled=True, size=130, color=cores.DESTAQUE[modo], stroke=sup, strokeWidth=2, opacity=1).encode(y=y, x=x, tooltip=tooltip)
    rotulos = alt.Chart(df).mark_text(align="left", dx=10, fontSize=12, fontWeight=600).encode(y=y, x="odds_ratio_por_dp:Q", text="rotulo:N")
    grafico = alt.layer(referencia, pontos, rotulos).properties(title=titulo_fatores(fatores), height=46 * len(df) + 40, width="container")
    return _base(grafico, modo)


# --------------------------------------------------------------------------- teste de desconto entre segmentos

def tabela_distribuicao(grupos: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{"segmento": g["segmento"], "households": g["households"], "mediana_pct": g["mediana_pct"], "q25_pct": g["q25_pct"],
                          "q75_pct": g["q75_pct"], "bigode_inf_pct": g["bigode_inf_pct"], "bigode_sup_pct": g["bigode_sup_pct"],
                          "desvio_padrao_pp": g["desvio_padrao_pp"], "taxa_ponderada_pct": g["taxa_ponderada_pct"]} for g in grupos])


def titulo_distribuicao(grupos: list[dict], veredito: str) -> str:
    lo, hi = min(g["mediana_pct"] for g in grupos), max(g["mediana_pct"] for g in grupos)
    faixa = f"medianas de {_pt(lo, 1)}% a {_pt(hi, 1)}%"
    if veredito == "diferenca_relevante":
        return f"Os segmentos recebem desconto diferente: {faixa}"
    return f"Os segmentos recebem desconto praticamente igual: {faixa}"


def grafico_distribuicao(grupos: list[dict], veredito: str, taxa_geral: float, modo: str):
    df = tabela_distribuicao(grupos)
    ordem = list(df["segmento"])
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    y = alt.Y("segmento:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=240, labelColor=tinta["secundaria"], ticks=False))
    escala = alt.Scale(domain=[0, math.ceil(df["bigode_sup_pct"].max() * 1.1 / 5) * 5])
    x_titulo = "% de desconto do household (caixa = 50% central, risco claro = mediana)"
    tooltip = [alt.Tooltip("segmento:N", title="Segmento"), alt.Tooltip("households:Q", title="Households", format=","),
               alt.Tooltip("mediana_pct:Q", title="Mediana (%)", format=".1f"), alt.Tooltip("q25_pct:Q", title="25% (%)", format=".1f"),
               alt.Tooltip("q75_pct:Q", title="75% (%)", format=".1f"), alt.Tooltip("desvio_padrao_pp:Q", title="Desvio-padrão (pp)", format=".1f"),
               alt.Tooltip("taxa_ponderada_pct:Q", title="Taxa ponderada (%)", format=".1f")]
    bigode = alt.Chart(df).mark_rule(strokeWidth=2, color=tinta["base"]).encode(
        y=y, x=alt.X("bigode_inf_pct:Q", scale=escala, title=x_titulo, axis=_eixo_pt(".0f", tickCount=6)), x2="bigode_sup_pct:Q")
    caixa = alt.Chart(df).mark_bar(cornerRadius=4, size=22, color=cores.DESTAQUE[modo], stroke=sup, strokeWidth=2).encode(
        y=y, x=alt.X("q25_pct:Q", scale=escala), x2="q75_pct:Q", tooltip=tooltip)
    mediana = alt.Chart(df).mark_tick(color=sup, thickness=3, size=22).encode(y=y, x=alt.X("mediana_pct:Q", scale=escala))
    regua = alt.Chart(pd.DataFrame({"x": [taxa_geral], "t": [f"taxa geral {_pt(taxa_geral, 1)}%"]}))
    linha = regua.mark_rule(color=tinta["muda"], strokeWidth=1).encode(x=alt.X("x:Q", scale=escala))
    nome = regua.mark_text(align="left", dx=5, dy=-4, fontSize=11, color=tinta["muda"]).encode(
        x=alt.X("x:Q", scale=escala), y=alt.value(8), text="t:N")
    grafico = alt.layer(bigode, linha, nome, caixa, mediana).properties(
        title=titulo_distribuicao(grupos, veredito), height=56 * len(df) + 30, width="container")
    return _base(grafico, modo)


def tabela_pares(ics: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame([{"par": f"{i['grupo_1']} − {i['grupo_2']}", "diferenca_mediana_pp": i["diferenca_mediana_pp"], "ic_inferior_pp": i["ic_inferior"],
                        "ic_superior_pp": i["ic_superior"], "ic_exclui_zero": i["exclui_zero"]} for i in ics])
    return df.reindex(df["diferenca_mediana_pp"].abs().sort_values(ascending=False).index).reset_index(drop=True)


def titulo_pares(ics: list[dict]) -> str:
    df = tabela_pares(ics)
    n_zero = int(df["ic_exclui_zero"].sum())
    maior = df.iloc[0]
    if n_zero == 0:
        return (f"Nenhum dos {len(df)} pares tem diferença de mediana distinguível de zero; a maior, {maior['par']}, "
                f"é {_pt(abs(maior['diferenca_mediana_pp']), 1)} pp")
    return (f"{n_zero} de {len(df)} pares têm diferença de mediana distinguível de zero; a maior, {maior['par']}, "
            f"é {_pt(abs(maior['diferenca_mediana_pp']), 1)} pp")


def grafico_pares(ics: list[dict], limite_pp: float, modo: str):
    df = tabela_pares(ics)
    ordem = list(df["par"])
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    lim = max(limite_pp * 2, math.ceil(max(df["ic_inferior_pp"].abs().max(), df["ic_superior_pp"].abs().max()) + 0.5))
    escala = alt.Scale(domain=[-lim, lim])
    y = alt.Y("par:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=260, labelColor=tinta["secundaria"], ticks=False))
    titulo_x = "Diferença de medianas, 1º menos 2º (pontos percentuais; barra = IC de 95%)"
    eixo_x = _eixo_pt(".0f", tickCount=7)
    tooltip = [alt.Tooltip("par:N", title="Par"), alt.Tooltip("diferenca_mediana_pp:Q", title="Diferença (pp)", format=".2f"),
               alt.Tooltip("ic_inferior_pp:Q", title="IC inferior (pp)", format=".2f"), alt.Tooltip("ic_superior_pp:Q", title="IC superior (pp)", format=".2f")]
    faixa = alt.Chart(pd.DataFrame({"a": [-limite_pp], "b": [limite_pp]})).mark_rect(color=tinta["grade"], opacity=0.55).encode(
        x=alt.X("a:Q", scale=escala), x2="b:Q")
    zero = alt.Chart(pd.DataFrame({"x": [0.0]})).mark_rule(color=tinta["base"], strokeWidth=1).encode(x=alt.X("x:Q", scale=escala))
    nome = alt.Chart(pd.DataFrame({"x": [limite_pp], "t": [f"faixa de ±{_pt(limite_pp, 0)} pp: diferença relevante"]})).mark_text(
        align="left", dx=5, fontSize=11, color=tinta["muda"]).encode(x=alt.X("x:Q", scale=escala), y=alt.value(8), text="t:N")
    intervalo = alt.Chart(df).mark_rule(strokeWidth=3, color=cores.DESTAQUE[modo]).encode(
        y=y, x=alt.X("ic_inferior_pp:Q", scale=escala, title=titulo_x, axis=eixo_x), x2="ic_superior_pp:Q")
    ponto = alt.Chart(df).mark_point(filled=True, size=110, color=cores.DESTAQUE[modo], stroke=sup, strokeWidth=2, opacity=1).encode(
        y=y, x=alt.X("diferenca_mediana_pp:Q", scale=escala), tooltip=tooltip)
    grafico = alt.layer(faixa, zero, nome, intervalo, ponto).properties(
        title=titulo_pares(ics), height=46 * len(df) + 40, width="container")
    return _base(grafico, modo)


SERIE_TODOS, SERIE_CINCO = "Todos os households", "Só quem tem {n} ou mais compras"


def tabela_sensibilidade(grupos: list[dict], grupos_sens: list[dict], minimo: int) -> pd.DataFrame:
    sens = {g["segmento"]: g for g in grupos_sens}
    linhas = []
    for g in grupos:
        for serie, d in ((SERIE_TODOS, g), (SERIE_CINCO.format(n=minimo), sens.get(g["segmento"]))):
            if d:
                linhas.append({"segmento": g["segmento"], "serie": serie, "households": d["households"], "mediana_pct": d["mediana_pct"],
                               "desvio_padrao_pp": d["desvio_padrao_pp"]})
    return pd.DataFrame(linhas)


def titulo_sensibilidade(grupos_sens: list[dict], minimo: int, p_valor: float, veredito_sens: str) -> str:
    lo, hi = min(g["mediana_pct"] for g in grupos_sens), max(g["mediana_pct"] for g in grupos_sens)
    p = "< 0,001" if p_valor < 0.001 else "= " + _pt(p_valor, 2)
    base = f"Só com quem comprou {minimo}+ vezes, as medianas ficam entre {_pt(lo, 1)}% e {_pt(hi, 1)}%"
    if veredito_sens == "sem_diferenca_detectavel":
        return f"{base} e a diferença deixa de ser significativa (p {p})"
    return f"{base} (p {p})"


def grafico_sensibilidade(grupos: list[dict], grupos_sens: list[dict], minimo: int, p_valor: float, veredito_sens: str, modo: str):
    df = tabela_sensibilidade(grupos, grupos_sens, minimo)
    ordem = list(dict.fromkeys(df["segmento"]))
    sup, tinta = cores.SUPERFICIE[modo], cores.TINTA[modo]
    series = [SERIE_TODOS, SERIE_CINCO.format(n=minimo)]
    cor = alt.Color("serie:N", scale=alt.Scale(domain=series, range=[cores.CINZA[modo], cores.DESTAQUE[modo]]),
                    legend=alt.Legend(title=None, labelLimit=360))
    escala = alt.Scale(domain=[math.floor(df["mediana_pct"].min() - 1.5), math.ceil(df["mediana_pct"].max() + 1.5)])
    y = alt.Y("segmento:N", sort=ordem, title=None, axis=alt.Axis(labelLimit=240, labelColor=tinta["secundaria"], ticks=False))
    titulo_x = "Mediana do % de desconto do household"
    tooltip = [alt.Tooltip("segmento:N", title="Segmento"), alt.Tooltip("serie:N", title="Grupo"), alt.Tooltip("households:Q", title="Households", format=","),
               alt.Tooltip("mediana_pct:Q", title="Mediana (%)", format=".1f"), alt.Tooltip("desvio_padrao_pp:Q", title="Desvio-padrão (pp)", format=".1f")]
    ligacao = alt.Chart(df).mark_rule(strokeWidth=2, color=tinta["base"]).encode(
        y=y, x=alt.X("min(mediana_pct):Q", scale=escala, title=titulo_x, axis=_eixo_pt(".0f", tickCount=6)), x2="max(mediana_pct):Q")
    # Quando as duas medianas coincidem o ponto cinza (maior) fica por baixo do azul (menor), e os dois continuam visíveis.
    pontos_todos = alt.Chart(df[df["serie"] == series[0]]).mark_point(filled=True, size=300, stroke=sup, strokeWidth=2, opacity=1).encode(
        y=y, x=alt.X("mediana_pct:Q", scale=escala), color=cor, tooltip=tooltip)
    pontos_cinco = alt.Chart(df[df["serie"] == series[1]]).mark_point(filled=True, size=110, stroke=sup, strokeWidth=2, opacity=1).encode(
        y=y, x=alt.X("mediana_pct:Q", scale=escala), color=cor, tooltip=tooltip)
    grafico = alt.layer(ligacao, pontos_todos, pontos_cinco).properties(
        title=titulo_sensibilidade(grupos_sens, minimo, p_valor, veredito_sens), height=52 * len(ordem) + 40, width="container")
    return _base(grafico, modo)
