"""Gráficos: título com a conclusão, cores só da paleta validada, marcas finas com vão, legenda, tooltip e tabela gêmea."""

import json
import re

import numpy as np
import pytest

from src.config import CFG
from src.ui import cores, graficos

CFG_RFM = CFG["analises"]["rfm"]


def segmentos():
    mk = lambda nome, n, pct_hh, v, pct_f: dict(nome=nome, households=n, pct_households=pct_hh, valor_medio_usd=v,
                                                valor_total_usd=n * v, pct_faturamento=pct_f)
    return [mk("Fiéis", 857, 35.4, 1780, 70.9), mk("Regulares", 980, 40.5, 568, 25.9),
            mk("Esporádicos", 426, 17.6, 128, 2.5), mk("Em pausa", 158, 6.5, 99, 0.7)]


def avaliacao():
    base = dict(inercia=1.0, tamanhos=[1])
    return [dict(base, k=2, silhueta=0.519, ari_sementes_min=0.99, ari_subamostras_min=0.95, menor_segmento_pct=24.7),
            dict(base, k=3, silhueta=0.429, ari_sementes_min=0.88, ari_subamostras_min=0.89, menor_segmento_pct=10.0),
            dict(base, k=4, silhueta=0.374, ari_sementes_min=0.97, ari_subamostras_min=0.95, menor_segmento_pct=6.5),
            dict(base, k=5, silhueta=0.32, ari_sementes_min=0.48, ari_subamostras_min=0.59, menor_segmento_pct=5.7)]


def coortes(retencao=(79.0, 78.0, 80.0, 79.0, 78.5, 79.5)):
    return [{"coorte": "Sem. 1–4", "households": 444, "retencao_pct": {i + 1: v for i, v in enumerate(retencao)}},
            {"coorte": "Sem. 5–8", "households": 522, "retencao_pct": {i + 1: v for i, v in enumerate(retencao[:-1])}}]


def espec(grafico) -> dict:
    return grafico.to_dict()


def hexes(spec) -> set[str]:
    return {h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}\b", json.dumps(spec))}


def titulo(spec) -> str:
    t = spec["title"]
    return t["text"] if isinstance(t, dict) else t


def permitidos(modo):
    t = cores.TINTA[modo]
    return ({c.lower() for c in cores.CATEGORICA[modo]} | {c.lower() for c in cores.SEQ_AZUL} | {c.lower() for c in t.values()}
            | {cores.SUPERFICIE[modo].lower(), cores.CINZA[modo].lower()})


@pytest.mark.parametrize("modo", ["claro", "escuro"])
@pytest.mark.parametrize("construir", [
    lambda m: graficos.grafico_segmentos(segmentos(), m),
    lambda m: graficos.grafico_k(avaliacao(), 4, CFG_RFM, m),
    lambda m: graficos.grafico_coorte(coortes(), m)])
def test_so_usa_cores_da_paleta_validada_e_nenhuma_grade_tracejada(construir, modo):
    spec = espec(construir(modo))
    assert hexes(spec) <= permitidos(modo), hexes(spec) - permitidos(modo)
    assert "strokeDash" not in json.dumps(spec)                      # grade e eixos são fios sólidos
    assert spec["config"]["view"]["stroke"] is None                  # sem moldura em volta do gráfico
    assert spec["config"]["background"] == "transparent"


def test_modo_escuro_usa_outros_passos_da_mesma_paleta():
    claro = hexes(espec(graficos.grafico_segmentos(segmentos(), "claro")))
    escuro = hexes(espec(graficos.grafico_segmentos(segmentos(), "escuro")))
    assert claro != escuro and cores.DESTAQUE["claro"] in claro and cores.DESTAQUE["escuro"] in escuro


# --- segmentos ---------------------------------------------------------------------------------------------

def test_titulo_dos_segmentos_diz_a_conclusao_com_os_numeros():
    assert graficos.titulo_segmentos(segmentos()) == "Fiéis são 35% dos clientes e geram 71% do faturamento"
    assert titulo(espec(graficos.grafico_segmentos(segmentos(), "claro"))) == graficos.titulo_segmentos(segmentos())


def test_segmentos_emphasis_barras_finas_arredondadas_com_vao_e_legenda():
    spec = espec(graficos.grafico_segmentos(segmentos(), "claro"))
    barras = next(c for c in spec["layer"] if c["mark"]["type"] == "bar")
    assert barras["mark"]["cornerRadiusEnd"] == 4 and barras["mark"]["strokeWidth"] == 2 and barras["mark"]["size"] <= 16
    assert barras["mark"]["stroke"] == cores.SUPERFICIE["claro"]                 # o vão tem a cor da superfície
    cor = barras["encoding"]["color"]
    assert cor["scale"]["domain"] == [graficos.SERIE_HH, graficos.SERIE_FAT]
    assert cor["scale"]["range"] == [cores.CINZA["claro"], cores.DESTAQUE["claro"]]   # cinza de apoio + um destaque
    assert cor["legend"] is not None and cor["legend"].get("title") is None            # 2 séries: legenda sempre
    assert len(barras["encoding"]["tooltip"]) >= 4                                     # tooltip em toda barra


def test_segmentos_rotula_so_o_segmento_principal_nao_todos_os_pontos():
    spec = espec(graficos.grafico_segmentos(segmentos(), "claro"))
    texto = next(c for c in spec["layer"] if c["mark"]["type"] == "text")
    dados = spec["datasets"][texto["data"]["name"]]
    assert {d["segmento"] for d in dados} == {"Fiéis"} and sorted(d["rotulo"] for d in dados) == ["35%", "71%"]


def test_tabela_gemea_dos_segmentos_tem_os_mesmos_valores_do_grafico():
    df = graficos.tabela_segmentos(segmentos())
    assert len(df) == 8 and set(df["serie"]) == {graficos.SERIE_HH, graficos.SERIE_FAT}
    spec = espec(graficos.grafico_segmentos(segmentos(), "claro"))
    barras = next(c for c in spec["layer"] if c["mark"]["type"] == "bar")
    desenhado = sorted(d["pct"] for d in spec["datasets"][barras["data"]["name"]])
    assert desenhado == sorted(df["pct"].tolist())


def test_eixo_nao_desperdica_espaco_e_ordem_dos_segmentos_e_a_recebida():
    spec = espec(graficos.grafico_segmentos(segmentos(), "claro"))
    barras = next(c for c in spec["layer"] if c["mark"]["type"] == "bar")
    assert barras["encoding"]["x"]["scale"]["domain"] == [0, 80]                       # 71% + folga, não 0-100
    assert barras["encoding"]["y"]["sort"] == ["Fiéis", "Regulares", "Esporádicos", "Em pausa"]


# --- escolha de K -----------------------------------------------------------------------------------------

def test_titulo_do_k_admite_que_a_silhueta_sozinha_escolheria_outro():
    df = graficos.tabela_k(avaliacao(), 4, CFG_RFM)
    assert graficos.titulo_k(df, 4) == "A silhueta sozinha escolheria K=2; só K=4 passa na regra de estabilidade e tamanho"
    melhor = avaliacao()[:1]
    assert "tem a maior silhueta" in graficos.titulo_k(graficos.tabela_k(melhor, 2, CFG_RFM), 2)


def test_tabela_do_k_marca_quem_passou_na_regra():
    df = graficos.tabela_k(avaliacao(), 4, CFG_RFM)
    assert dict(zip(df["k"], df["passou_na_regra"])) == {2: False, 3: False, 4: True, 5: False}
    assert dict(zip(df["k"], df["estado"])) == {2: "Demais K", 3: "Demais K", 4: "K escolhido", 5: "Demais K"}


def test_curva_do_k_tem_emphasis_regua_rotulada_e_legenda():
    spec = espec(graficos.grafico_k(avaliacao(), 4, CFG_RFM, "claro"))
    pontos = next(c for c in spec["layer"] if c["mark"]["type"] == "point")
    cor = pontos["encoding"]["color"]
    assert cor["scale"]["range"] == [cores.DESTAQUE["claro"], cores.CINZA["claro"]] and cor["legend"] is not None
    textos = [d for c in spec["layer"] if c["mark"]["type"] == "text" for d in spec["datasets"][c["data"]["name"]]]
    assert any("mínimo da regra: 0,25" in d.get("t", "") for d in textos)              # a régua não fica sem nome
    assert any(d.get("t") == "K=4" for d in textos)
    regua = next(c for c in spec["layer"] if c["mark"]["type"] == "rule")
    assert spec["datasets"][regua["data"]["name"]][0]["y"] == CFG_RFM["silhueta_minima"]


# --- coorte -------------------------------------------------------------------------------------------------

def test_titulo_da_coorte_distingue_retencao_estavel_de_queda():
    df = graficos.tabela_coorte(coortes())
    assert graficos.titulo_coorte(df).startswith("A retenção é estável: cerca de 79% de cada coorte")
    caindo = graficos.tabela_coorte(coortes((90, 88, 85, 70, 60, 50, 45, 40)))
    assert "cai de" in graficos.titulo_coorte(caindo) and "ao longo do tempo" in graficos.titulo_coorte(caindo)


def test_heatmap_usa_escala_sequencial_de_0_a_100_com_um_matiz_e_o_escuro_inverte():
    claro = espec(graficos.grafico_coorte(coortes(), "claro"))["encoding"]["color"]["scale"]
    escuro = espec(graficos.grafico_coorte(coortes(), "escuro"))["encoding"]["color"]["scale"]
    assert claro["domain"] == [0, 100] and claro["range"] == cores.SEQ_AZUL and escuro["range"] == cores.SEQ_AZUL[::-1]


# --- CLV ------------------------------------------------------------------------------------------------------

def segmentos_clv():
    mk = lambda nome, n, clv, ic, razao=None, ric=None: {
        "nome": nome, "n": n, "clv_medio": clv, "ic_95": ic, "clv_total_usd": n * clv, "razao_futuro_passado": razao,
        "razao_ic_95": ric, "ritmo_relativo": None if razao is None else razao / 2}
    return [mk("Fiéis", 857, 820.0, [781.0, 860.0], 1.84, [1.75, 1.93]), mk("Regulares", 980, 326.0, [309.0, 344.0], 2.29, [2.2, 2.4]),
            mk("Esporádicos", 426, 135.0, [120.0, 153.0], 4.2, [3.8, 4.7]), mk("Em pausa", 158, 103.0, [78.0, 133.0], 4.16, [3.4, 5.0]),
            mk("Sem compra na janela", 79, 99.0, [78.0, 122.0])]


def backtest_exemplo():
    l = lambda nome, n, pm, pi, real: {"nome": nome, "households": n, "previsto_metodo_usd": pm, "previsto_ingenuo_usd": pi, "real_usd": real,
                                       "erro_metodo_pct": 100 * (pm / real - 1), "erro_ingenuo_pct": 100 * (pi / real - 1)}
    linhas = [l("Fiéis", 849, 1378541.0, 1469729.0, 1412575.0), l("Esporádicos", 447, 103871.0, 58301.0, 119578.0),
              l("Sem compra na janela", 98, 11651.0, 0.0, 17143.0)]
    tot = {c: sum(x[c] for x in linhas) for c in ("previsto_metodo_usd", "previsto_ingenuo_usd", "real_usd")}
    tot["erro_metodo_pct"] = 100 * (tot["previsto_metodo_usd"] / tot["real_usd"] - 1)
    tot["erro_ingenuo_pct"] = 100 * (tot["previsto_ingenuo_usd"] / tot["real_usd"] - 1)
    return {"horizonte_semanas": 26, "segmentos": linhas, "total": tot}


@pytest.mark.parametrize("modo", ["claro", "escuro"])
@pytest.mark.parametrize("construir", [
    lambda m: graficos.grafico_clv(segmentos_clv(), m),
    lambda m: graficos.grafico_ritmo(segmentos_clv(), m),
    lambda m: graficos.grafico_backtest(backtest_exemplo(), m)])
def test_graficos_do_clv_so_usam_cores_da_paleta_e_grade_solida(construir, modo):
    spec = espec(construir(modo))
    assert hexes(spec) <= permitidos(modo) and "strokeDash" not in json.dumps(spec)
    assert spec["config"]["view"]["stroke"] is None


def test_titulo_do_clv_diz_a_conclusao_com_a_razao_entre_os_dois_maiores_grupos():
    assert graficos.titulo_clv(segmentos_clv()) == "Um household do grupo Fiéis vale US$ 820 em 52 semanas, 2,5x um do grupo Regulares"
    assert titulo(espec(graficos.grafico_clv(segmentos_clv(), "claro"))) == graficos.titulo_clv(segmentos_clv())


def test_clv_uma_serie_uma_cor_barra_de_intervalo_e_rotulo_so_no_maior_grupo():
    spec = espec(graficos.grafico_clv(segmentos_clv(), "claro"))
    barras = next(c for c in spec["layer"] if c["mark"]["type"] == "bar")
    assert barras["mark"]["color"] == cores.DESTAQUE["claro"] and barras["mark"]["cornerRadiusEnd"] == 4 and barras["mark"]["strokeWidth"] == 2
    assert "color" not in barras["encoding"]                              # nominal: não pinta por valor
    assert barras["encoding"]["y"]["sort"][0] == "Fiéis" and len(barras["encoding"]["tooltip"]) >= 5
    regua = next(c for c in spec["layer"] if c["mark"]["type"] == "rule")
    assert regua["encoding"]["x"]["field"] == "ic_inferior" and regua["encoding"]["x2"]["field"] == "ic_superior"
    texto = next(c for c in spec["layer"] if c["mark"]["type"] == "text")
    assert [d["segmento"] for d in spec["datasets"][texto["data"]["name"]]] == ["Fiéis"]


def test_tabela_gemea_do_clv_tem_ic_e_total_de_cada_grupo():
    df = graficos.tabela_clv(segmentos_clv())
    assert len(df) == 5 and list(df["ic_inferior"][:2]) == [781.0, 309.0] and df.loc[0, "clv_total_usd"] == 857 * 820.0


def test_ritmo_ignora_o_grupo_sem_razao_e_marca_a_referencia_em_um():
    df = graficos.tabela_ritmo(segmentos_clv())
    assert list(df["segmento"]) == ["Fiéis", "Regulares", "Esporádicos", "Em pausa"] and df.loc[0, "ritmo"] == 0.92
    assert df.loc[0, "ic_inferior"] == pytest.approx(0.875) and df.loc[0, "ic_superior"] == pytest.approx(0.965)
    spec = espec(graficos.grafico_ritmo(segmentos_clv(), "claro"))
    referencia = next(c for c in spec["layer"] if c["mark"]["type"] == "rule" and "x2" not in c["encoding"])
    assert spec["datasets"][referencia["data"]["name"]][0]["x"] == 1.0
    assert "igual ao ritmo atual" in json.dumps(spec)


def test_ritmo_mantem_a_ordem_dos_grupos_em_todas_as_camadas():
    """As camadas compartilham o campo e a ordem do eixo y: com campos diferentes o Vega-Lite reordena os grupos."""
    spec = espec(graficos.grafico_ritmo(segmentos_clv(), "claro"))
    campos = {c["encoding"]["y"]["field"] for c in spec["layer"] if "y" in c["encoding"]}
    ordens = {json.dumps(c["encoding"]["y"].get("sort")) for c in spec["layer"] if "y" in c["encoding"]}
    assert campos == {"segmento"} and len(ordens) == 1


def test_titulo_do_ritmo_nomeia_quem_gasta_acima_e_quem_fica_abaixo():
    t = graficos.titulo_ritmo(graficos.tabela_ritmo(segmentos_clv()))
    assert t == "Esporádicos e Em pausa gastam 2,1x o ritmo atual nas semanas seguintes; Fiéis, 0,92x"


def test_backtest_titulo_legenda_curta_e_rotulo_fora_da_barra():
    bt = backtest_exemplo()
    comma = lambda v: f"{abs(v):.1f}".replace(".", ",")
    esperado = (f"No teste de 26 semanas o método errou {comma(bt['total']['erro_metodo_pct'])}% no total; "
                f"repetir o último período, {comma(bt['total']['erro_ingenuo_pct'])}%")
    assert graficos.titulo_backtest(bt) == esperado
    spec = espec(graficos.grafico_backtest(bt, "claro"))
    barras = next(c for c in spec["layer"] if c["mark"]["type"] == "bar")
    cor = barras["encoding"]["color"]
    assert cor["scale"]["domain"] == [graficos.SERIE_INGENUA, graficos.SERIE_METODO] and cor["legend"] is not None
    assert max(len(s) for s in cor["scale"]["domain"]) <= 26                               # cabe na legenda sem ser cortado
    texto = next(c for c in spec["layer"] if c["mark"]["type"] == "text")
    assert "datum.erro < 0" in json.dumps(texto["mark"]) and {d["grupo"] for d in spec["datasets"][texto["data"]["name"]]} == {"Total"}


def test_tabela_gemea_do_backtest_traz_o_total_e_a_regra_ingenua_do_grupo_sem_compra():
    df = graficos.tabela_backtest(backtest_exemplo())
    assert list(df["grupo"]) == ["Fiéis", "Esporádicos", "Sem compra na janela", "Total"]
    assert df.loc[df["grupo"] == "Sem compra na janela", "erro_ingenuo_pct"].iloc[0] == -100.0
    assert df.loc[df["grupo"] == "Total", "households"].iloc[0] == 849 + 447 + 98


# --- churn (pausa longa) ------------------------------------------------------------------------------------------

def segmentos_churn():
    s = lambda nome, n, risco, esp, alertas, valor: {"nome": nome, "households": n, "risco_medio_pct": risco, "pausas_esperadas": esp,
                                                    "alertas": alertas, "valor_em_risco_usd": valor}
    return [s("Fiéis", 857, 0.6, 5.2, 0, 2517.0), s("Regulares", 966, 4.5, 43.7, 20, 7157.0), s("Esporádicos", 380, 22.9, 87.1, 223, 3031.0)]


def curva_churn():
    return [{"limiar": t, "precisao": p, "recall": r, "alertas": a, "escolhido": t == 0.17}
            for t, p, r, a in ((0.05, 0.17, 0.81, 1400), (0.10, 0.23, 0.67, 800), (0.17, 0.287, 0.481, 473), (0.30, 0.33, 0.23, 190), (0.50, 0.46, 0.06, 40))]


def calibracao_exemplo(desvio=0.0):
    prev = [0.2, 0.4, 0.8, 1.4, 2.4, 4.0, 7.0, 12.8, 20.0, 31.0]
    return [{"decil": i + 1, "households": 440, "previsto_pct": p, "observado_pct": p + (desvio if i == 9 else 0.0)} for i, p in enumerate(prev)]


def fatores_churn():
    f = lambda v, desc, coef: {"variavel": v, "descricao": desc, "coeficiente_padronizado": coef, "odds_ratio_por_dp": float(np.exp(coef)),
                               "efeito": "reduz o risco" if coef < 0 else "aumenta o risco",
                               "leitura": f"{desc}: {'quanto maior, menor' if coef < 0 else 'quanto maior, maior'} o risco"}
    return [f("semanas_com_compra_26s", "semanas com compra nas últimas 26 (constância)", -0.71), f("log_compras_8s", "compras nas últimas 8 semanas", -0.54),
            f("recencia_semanas", "semanas desde a última compra", 0.28), f("maior_pausa_26s", "maior pausa seguida nas últimas 26 semanas", 0.16),
            f("log_valor_26s", "gasto nas últimas 26 semanas", -0.14)]


@pytest.mark.parametrize("modo", ["claro", "escuro"])
@pytest.mark.parametrize("construir", [
    lambda m: graficos.grafico_risco(segmentos_churn(), 8, m),
    lambda m: graficos.grafico_limiar(curva_churn(), m),
    lambda m: graficos.grafico_calibracao(calibracao_exemplo(), m),
    lambda m: graficos.grafico_fatores(fatores_churn(), m)])
def test_graficos_do_churn_so_usam_cores_da_paleta_e_grade_solida(construir, modo):
    spec = espec(construir(modo))
    assert hexes(spec) <= permitidos(modo) and "strokeDash" not in json.dumps(spec)
    assert spec["config"]["view"]["stroke"] is None


def test_risco_titulo_com_a_conclusao_uma_cor_e_rotulo_em_todas_as_barras():
    assert graficos.titulo_risco(graficos.tabela_risco(segmentos_churn()), 8) == (
        "Esporádicos têm 22,9% de risco de ficar 8 semanas sem comprar; Fiéis, 0,6%")
    spec = espec(graficos.grafico_risco(segmentos_churn(), 8, "claro"))
    barras = next(c for c in spec["layer"] if c["mark"]["type"] == "bar")
    assert barras["mark"]["color"] == cores.DESTAQUE["claro"] and "color" not in barras["encoding"] and len(barras["encoding"]["tooltip"]) >= 7
    texto = next(c for c in spec["layer"] if c["mark"]["type"] == "text")
    assert sorted(d["rotulo"] for d in spec["datasets"][texto["data"]["name"]]) == ["0,6%", "22,9%", "4,5%"]


def test_tabela_do_risco_mostra_onde_estao_as_pausas_e_onde_esta_o_dinheiro():
    df = graficos.tabela_risco(segmentos_churn())
    assert df["pct_das_pausas"].sum() == pytest.approx(100) and df["pct_do_valor_em_risco"].sum() == pytest.approx(100)
    por = df.set_index("segmento")
    assert por.loc["Esporádicos", "pct_das_pausas"] > por.loc["Regulares", "pct_das_pausas"]
    assert por.loc["Regulares", "pct_do_valor_em_risco"] > por.loc["Esporádicos", "pct_do_valor_em_risco"]


def test_limiar_duas_series_legenda_regua_no_escolhido_e_titulo_com_os_numeros():
    assert graficos.titulo_limiar(curva_churn()) == ("No limiar 0,17, 29% dos alertas se confirmam e 48% das pausas são pegas; "
                                                      "subir o limiar troca recall por precisão")
    spec = espec(graficos.grafico_limiar(curva_churn(), "claro"))
    linhas = next(c for c in spec["layer"] if c["mark"]["type"] == "line")
    cor = linhas["encoding"]["color"]
    assert cor["scale"]["domain"] == [graficos.SERIE_PRECISAO, graficos.SERIE_RECALL] and cor["scale"]["range"] == cores.CATEGORICA["claro"][:2]
    assert cor["legend"] is not None
    regua = next(c for c in spec["layer"] if c["mark"]["type"] == "rule")
    assert spec["datasets"][regua["data"]["name"]][0]["limiar"] == 0.17 and "F1 máximo" in json.dumps(spec, ensure_ascii=False)


def test_tabela_do_limiar_marca_um_unico_escolhido():
    df = graficos.tabela_limiar(curva_churn())
    assert int(df["escolhido"].sum()) == 1 and df.loc[df["escolhido"], "precisao_pct"].iloc[0] == pytest.approx(28.7)


def test_calibracao_titulo_distingue_confiavel_de_desalinhada():
    assert graficos.titulo_calibracao(calibracao_exemplo()).startswith("As probabilidades são confiáveis: no decil de maior risco o modelo previu 31,0%")
    assert "se afastam do observado em até 9,0 pontos" in graficos.titulo_calibracao(calibracao_exemplo(desvio=-9.0))


def test_calibracao_tem_diagonal_e_o_rotulo_fica_perto_dela():
    spec = espec(graficos.grafico_calibracao(calibracao_exemplo(), "claro"))
    nome = next(c for c in spec["layer"] if c["mark"]["type"] == "text")
    ponto = spec["datasets"][nome["data"]["name"]][0]
    assert ponto["a"] == pytest.approx(ponto["b"]) and "calibração perfeita" == ponto["t"]          # sobre a diagonal y = x
    linha = next(c for c in spec["layer"] if c["mark"]["type"] == "line")
    assert linha["encoding"]["x"]["scale"] == linha["encoding"]["y"]["scale"]                      # mesma escala nos dois eixos


def test_fatores_referencia_em_um_rotulos_em_portugues_e_titulo_do_maior_sinal():
    assert graficos.titulo_fatores(fatores_churn()) == ('O maior sinal é "semanas com compra nas últimas 26 (constância)": '
                                                         'a cada desvio-padrão a mais, o risco cai para 0,49x')
    spec = espec(graficos.grafico_fatores(fatores_churn(), "claro"))
    referencia = next(c for c in spec["layer"] if c["mark"]["type"] == "rule")
    assert spec["datasets"][referencia["data"]["name"]][0]["x"] == 1.0
    texto = next(c for c in spec["layer"] if c["mark"]["type"] == "text")
    assert sorted(d["rotulo"] for d in spec["datasets"][texto["data"]["name"]]) == ["0,49x", "0,58x", "0,87x", "1,17x", "1,32x"]
    assert graficos.tabela_fatores(fatores_churn()).shape[0] == 5


def test_eixos_numericos_com_decimal_ou_milhar_usam_o_formato_brasileiro():
    """O Vega usa o formato americano; os rótulos são trocados por expressão para bater com os textos do app."""
    construtores = {"limiar": lambda: graficos.grafico_limiar(curva_churn(), "claro"), "fatores": lambda: graficos.grafico_fatores(fatores_churn(), "claro"),
                    "clv": lambda: graficos.grafico_clv(segmentos_clv(), "claro"), "ritmo": lambda: graficos.grafico_ritmo(segmentos_clv(), "claro"),
                    "k": lambda: graficos.grafico_k(avaliacao(), 4, CFG_RFM, "claro")}
    for nome, construir in construtores.items():
        assert "replace(replace(replace(format(datum.value" in json.dumps(espec(construir())), nome


# --- teste de desconto entre segmentos ---------------------------------------------------------------------------

def grupos_desconto(medianas=(14.97, 15.38, 14.49, 14.13), n=(857, 980, 426, 158)):
    nomes = ("Fiéis", "Regulares", "Esporádicos", "Em pausa")
    return [{"segmento": s, "households": h, "mediana_pct": m, "q25_pct": m - 3, "q75_pct": m + 4, "bigode_inf_pct": m - 10, "bigode_sup_pct": m + 12,
             "desvio_padrao_pp": 5.0 + i, "taxa_ponderada_pct": m + 0.5} for i, (s, h, m) in enumerate(zip(nomes, n, medianas))]


def ics_desconto(excluem=False):
    pares = [("Fiéis", "Regulares", -0.41, -1.06, 0.16), ("Fiéis", "Esporádicos", 0.48, -0.52, 1.79), ("Fiéis", "Em pausa", 0.84, -0.79, 2.30),
             ("Regulares", "Esporádicos", 0.89, -0.15, 2.19), ("Regulares", "Em pausa", 1.25, -0.43, 2.67), ("Esporádicos", "Em pausa", 0.36, -1.73, 1.92)]
    return [{"grupo_1": a, "grupo_2": b, "diferenca_mediana_pp": d, "ic_inferior": lo + (1.0 if excluem else 0), "ic_superior": hi, "exclui_zero": excluem and lo + 1.0 > 0}
            for a, b, d, lo, hi in pares]


@pytest.mark.parametrize("modo", ["claro", "escuro"])
@pytest.mark.parametrize("construir", [
    lambda m: graficos.grafico_distribuicao(grupos_desconto(), "diferenca_desprezivel", 15.7, m),
    lambda m: graficos.grafico_pares(ics_desconto(), 1.0, m),
    lambda m: graficos.grafico_sensibilidade(grupos_desconto(), grupos_desconto((14.97, 15.39, 15.19, 15.08), (857, 979, 257, 45)), 5, 0.52,
                                             "sem_diferenca_detectavel", m)])
def test_graficos_do_desconto_so_usam_cores_da_paleta_e_grade_solida(construir, modo):
    spec = espec(construir(modo))
    assert hexes(spec) <= permitidos(modo) and "strokeDash" not in json.dumps(spec)
    assert spec["config"]["view"]["stroke"] is None


def test_titulos_do_desconto_dizem_a_conclusao_conforme_o_veredito():
    g = grupos_desconto()
    assert graficos.titulo_distribuicao(g, "diferenca_desprezivel") == "Os segmentos recebem desconto praticamente igual: medianas de 14,1% a 15,4%"
    assert graficos.titulo_distribuicao(g, "diferenca_relevante").startswith("Os segmentos recebem desconto diferente")
    assert graficos.titulo_pares(ics_desconto()) == ("Nenhum dos 6 pares tem diferença de mediana distinguível de zero; a maior, "
                                                     "Regulares − Em pausa, é 1,2 pp")
    assert graficos.titulo_pares(ics_desconto(excluem=True)).startswith("4 de 6 pares têm diferença de mediana distinguível de zero")
    sens = grupos_desconto((14.97, 15.39, 15.19, 15.08))
    assert graficos.titulo_sensibilidade(sens, 5, 0.5225, "sem_diferenca_detectavel") == (
        "Só com quem comprou 5+ vezes, as medianas ficam entre 15,0% e 15,4% e a diferença deixa de ser significativa (p = 0,52)")
    assert graficos.titulo_sensibilidade(sens, 5, 0.0004, "diferenca_desprezivel").endswith("(p < 0,001)")


def test_distribuicao_uma_cor_tooltip_completo_e_referencia_da_taxa_geral():
    spec = espec(graficos.grafico_distribuicao(grupos_desconto(), "diferenca_desprezivel", 15.7, "claro"))
    caixa = next(c for c in spec["layer"] if c["mark"]["type"] == "bar")
    assert caixa["mark"]["color"] == cores.DESTAQUE["claro"] and "color" not in caixa["encoding"] and len(caixa["encoding"]["tooltip"]) == 7
    assert "taxa geral 15,7%" in json.dumps(spec, ensure_ascii=False)
    assert graficos.tabela_distribuicao(grupos_desconto()).shape == (4, 9)


def test_pares_tem_zero_faixa_de_relevancia_e_ordem_pelo_tamanho_da_diferenca():
    df = graficos.tabela_pares(ics_desconto())
    assert list(df["par"])[0] == "Regulares − Em pausa" and list(df["diferenca_mediana_pp"].abs()) == sorted(df["diferenca_mediana_pp"].abs(), reverse=True)
    spec = espec(graficos.grafico_pares(ics_desconto(), 1.0, "claro"))
    tipos = [c["mark"]["type"] for c in spec["layer"]]
    assert tipos.count("rect") == 1 and tipos.count("rule") >= 2 and "point" in tipos
    faixa = next(c for c in spec["layer"] if c["mark"]["type"] == "rect")
    assert spec["datasets"][faixa["data"]["name"]][0] == {"a": -1.0, "b": 1.0}


def test_sensibilidade_duas_series_com_legenda_e_tabela_com_as_duas():
    g, s = grupos_desconto(), grupos_desconto((14.97, 15.39, 15.19, 15.08), (857, 979, 257, 45))
    df = graficos.tabela_sensibilidade(g, s, 5)
    assert sorted(df["serie"].unique()) == ["Só quem tem 5 ou mais compras", "Todos os households"] and len(df) == 8
    spec = espec(graficos.grafico_sensibilidade(g, s, 5, 0.52, "sem_diferenca_detectavel", "claro"))
    pontos = [c for c in spec["layer"] if c["mark"]["type"] == "point"]
    assert len(pontos) == 2 and all(p["encoding"]["color"]["legend"] is not None for p in pontos)
    assert pontos[0]["encoding"]["color"]["scale"]["range"] == [cores.CINZA["claro"], cores.DESTAQUE["claro"]]


def test_tabela_gemea_da_coorte_tem_uma_linha_por_celula():
    df = graficos.tabela_coorte(coortes())
    assert len(df) == 6 + 5 and set(df.columns) >= {"coorte", "households", "bloco_depois_da_entrada", "pct"}
    spec = espec(graficos.grafico_coorte(coortes(), "claro"))
    assert len(next(iter(spec["datasets"].values()))) == len(df)
