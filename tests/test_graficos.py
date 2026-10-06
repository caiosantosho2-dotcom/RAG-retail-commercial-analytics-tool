"""Gráficos: título com a conclusão, cores só da paleta validada, marcas finas com vão, legenda, tooltip e tabela gêmea."""

import json
import re

import pytest

from src.config import CFG
from src.ui import cores, graficos

CFG_RFM = CFG["analises"]["rfm"]


def segmentos():
    mk = lambda nome, n, pct_hh, v, pct_f: dict(nome=nome, households=n, pct_households=pct_hh, valor_medio_usd=v,
                                                valor_total_usd=n * v, pct_faturamento=pct_f)
    return [mk("Fiéis", 857, 35.4, 1780, 70.9), mk("Regulares", 980, 40.5, 568, 25.9),
            mk("Esporádicos", 426, 17.6, 128, 2.5), mk("Inativos", 158, 6.5, 99, 0.7)]


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
    assert barras["encoding"]["y"]["sort"] == ["Fiéis", "Regulares", "Esporádicos", "Inativos"]


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


def test_tabela_gemea_da_coorte_tem_uma_linha_por_celula():
    df = graficos.tabela_coorte(coortes())
    assert len(df) == 6 + 5 and set(df.columns) >= {"coorte", "households", "bloco_depois_da_entrada", "pct"}
    spec = espec(graficos.grafico_coorte(coortes(), "claro"))
    assert len(next(iter(spec["datasets"].values()))) == len(df)
