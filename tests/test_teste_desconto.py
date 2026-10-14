"""Teste de desconto entre segmentos: funções da referência intactas, estatística conferida contra scipy, efeito plantado,
regra do post-hoc, veredito, sensibilidade e a base real conferida por SQL independente."""

import importlib.util
import inspect
import json
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src import teste_hipotese as copia
from src.config import CFG, RAIZ
from src.nucleo import banco, cache, log, rfm
from src.nucleo import teste_desconto as td
from src.nucleo.teste_desconto import ic_diferencas_mediana, testar_desconto_entre_segmentos, veredito
from tests import sintetico_clientes as sc

CFG_TD = CFG["analises"]["teste_desconto"]
BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


# --- as três funções vêm da referência, sem alteração --------------------------------------------------------------

def test_funcoes_estatisticas_sao_copia_fiel_da_referencia():
    spec = importlib.util.spec_from_file_location("referencia_th", Path(__file__).resolve().parent.parent / "referencia" / "teste_hipotese.py")
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    for nome in ("testar_normalidade_por_grupo", "teste_kruskal_wallis", "post_hoc_pairwise_mannwhitney"):
        assert inspect.getsource(getattr(copia, nome)) == inspect.getsource(getattr(ref, nome)), nome


# --- IC bootstrap -----------------------------------------------------------------------------------------------

def grupos_normais(medias, n=400, dp=1.0, semente=1):
    rng = np.random.default_rng(semente)
    return {f"g{i}": rng.normal(m, dp, n) for i, m in enumerate(medias)}


def test_ic_acha_a_diferenca_plantada_e_nao_acha_onde_nao_ha():
    dados = grupos_normais([10.0, 10.0, 13.0])
    ics = {(i["grupo_1"], i["grupo_2"]): i for i in ic_diferencas_mediana(dados, list(dados), 2000, 0.95, 42)}
    assert len(ics) == 3
    assert not ics[("g0", "g1")]["exclui_zero"] and ics[("g0", "g1")]["ic_inferior"] < 0 < ics[("g0", "g1")]["ic_superior"]
    mau = ics[("g0", "g2")]
    assert mau["exclui_zero"] and mau["ic_superior"] < 0 and mau["ic_inferior"] < -3 + 0.5 and mau["ic_superior"] > -3 - 0.5
    assert mau["diferenca_mediana_pp"] == pytest.approx(np.median(dados["g0"]) - np.median(dados["g2"]))


def test_ic_e_reproduzivel_com_a_mesma_semente_e_muda_com_outra():
    dados = grupos_normais([10.0, 11.0])
    a = ic_diferencas_mediana(dados, list(dados), 500, 0.95, 42)
    assert a == ic_diferencas_mediana(dados, list(dados), 500, 0.95, 42)
    assert a != ic_diferencas_mediana(dados, list(dados), 500, 0.95, 43)


def test_ic_cobre_a_diferenca_verdadeira_na_maioria_das_repeticoes():
    cobriu = 0
    for s in range(40):
        d = grupos_normais([10.0, 11.0], n=200, semente=100 + s)
        i = ic_diferencas_mediana(d, list(d), 400, 0.95, s)[0]
        cobriu += i["ic_inferior"] <= -1.0 <= i["ic_superior"]
    assert cobriu >= 34          # nominal 95% de 40 = 38; margem para a variação de 40 repetições


# --- veredito -----------------------------------------------------------------------------------------------------

def kw(p, eta):
    return {"p_valor": p, "eta_quadrado_aprox": eta}


def ic(dif, excl):
    return {"diferenca_mediana_pp": dif, "exclui_zero": excl}


@pytest.mark.parametrize("p,eta,ics,esperado", [
    (0.30, 0.05, [ic(3.0, True)], "sem_diferenca_detectavel"),       # sem significância, nem o efeito grande conta
    (0.05, 0.05, [ic(3.0, True)], "sem_diferenca_detectavel"),       # p igual ao alfa não é significativo
    (0.01, 0.004, [ic(0.9, True), ic(1.2, False)], "diferenca_desprezivel"),
    (0.01, 0.004, [ic(0.3, True)], "diferenca_desprezivel"),
    (0.01, 0.010, [ic(0.3, False)], "diferenca_relevante"),          # eta² no limite
    (0.01, 0.004, [ic(-1.0, True)], "diferenca_relevante"),          # par no limite, em módulo
    (0.01, -0.001, [], "diferenca_desprezivel"),
])
def test_veredito_exige_significancia_e_efeito(p, eta, ics, esperado):
    assert veredito(kw(p, eta), ics, CFG_TD) == esperado


# --- estatística conferida contra scipy ------------------------------------------------------------------------------

def test_kruskal_confere_com_scipy_e_eta_quadrado_com_a_formula():
    rng = np.random.default_rng(5)
    d = pd.concat([pd.DataFrame({"segmento": g, "pct_desconto": rng.gamma(4, 4, n) + s}) for g, n, s in (("a", 300, 0), ("b", 200, 1), ("c", 100, 2))])
    r = td._kw(d)
    h, p = stats.kruskal(*[d.loc[d.segmento == g, "pct_desconto"] for g in "abc"])
    assert r["estatistica_H"] == pytest.approx(h, abs=1e-4) and r["p_valor"] == pytest.approx(p)
    assert r["eta_quadrado_aprox"] == pytest.approx((h - 3 + 1) / (600 - 3), abs=1e-4)
    assert r["n_grupos_testados"] == 3 and r["n_total_observacoes"] == 600


def test_impacto_calculado_a_mao():
    g = [{"segmento": "A", "taxa_ponderada_pct": 10.0, "desconto_total_usd": 100.0, "valor_bruto_usd": 1000.0},
         {"segmento": "B", "taxa_ponderada_pct": 20.0, "desconto_total_usd": 400.0, "valor_bruto_usd": 2000.0}]
    i = td._impacto(g)
    assert i["desconto_total_usd"] == 500 and i["taxa_geral_pct"] == pytest.approx(100 * 500 / 3000)
    assert i["menor_taxa_segmento"] == "A" and i["desconto_a_menos_se_igualar_usd"] == pytest.approx(2000 * 0.10)   # B cairia de 20% para 10%
    assert i["desconto_a_menos_pct_do_total"] == pytest.approx(40.0)


# --- pipeline sintético: efeito plantado e sem efeito ---------------------------------------------------------------

def clientes_com_desconto(extra_por_plantado: dict[str, float]) -> pd.DataFrame:
    c = sc.gerar_clientes()
    pct = (c["pct_desconto"] + c["segmento_plantado"].map(extra_por_plantado).fillna(0.0)).clip(0, 60)
    bruto = c["valor"] / (1 - pct / 100)
    return c.assign(pct_desconto=pct, valor_bruto=bruto, desconto_total=bruto - c["valor"])


def rodar(tmp_path, clientes):
    mp = pytest.MonkeyPatch()
    mp.setattr(log, "CAMINHO", tmp_path / "chamadas.jsonl")
    banco.definir_banco(sc.criar_banco(tmp_path / "t.duckdb", clientes=clientes))
    cache.limpar()
    try:
        return testar_desconto_entre_segmentos(), clientes
    finally:
        banco.fechar_todas()
        banco.definir_banco(None)
        cache.limpar()
        mp.undo()


@pytest.fixture(scope="module")
def com_efeito(tmp_path_factory):
    return rodar(tmp_path_factory.mktemp("td_efeito"), clientes_com_desconto({"fieis": 6.0}))


@pytest.fixture(scope="module")
def sem_efeito(tmp_path_factory):
    return rodar(tmp_path_factory.mktemp("td_sem"), clientes_com_desconto({}))


def test_acha_o_efeito_plantado_e_roda_o_post_hoc(com_efeito):
    r, _ = com_efeito
    assert "erro" not in r and r["veredito"] == "diferenca_relevante" and r["kruskal_wallis"]["significativo_5pct"]
    assert r["post_hoc_executado"] and r["post_hoc"] and r["post_hoc_motivo"] is None
    maior = max(r["grupos"], key=lambda g: g["mediana_pct"])
    assert maior["segmento"] == "Fiéis" and maior["mediana_pct"] > 19
    pares_fieis = [i for i in r["ic_diferencas"] if "Fiéis" in (i["grupo_1"], i["grupo_2"])]
    assert len(pares_fieis) == 3 and all(i["exclui_zero"] and abs(i["diferenca_mediana_pp"]) > 4 for i in pares_fieis)
    assert "diferente de forma relevante" in r["e_dai"]["conclusao"] and "Fiéis" in r["e_dai"]["conclusao"]


def test_sem_efeito_nao_inventa_diferenca_e_o_post_hoc_obedece_ao_teste_geral(sem_efeito):
    r, _ = sem_efeito
    assert r["veredito"] in ("sem_diferenca_detectavel", "diferenca_desprezivel")
    assert r["post_hoc_executado"] == r["kruskal_wallis"]["significativo_5pct"]
    assert (r["post_hoc"] is None) == (not r["post_hoc_executado"]) and (r["post_hoc_motivo"] is None) == r["post_hoc_executado"]
    assert all(not i["exclui_zero"] or abs(i["diferenca_mediana_pp"]) < 1.0 for i in r["ic_diferencas"])
    assert "diferente de forma relevante" not in r["e_dai"]["conclusao"]


def test_post_hoc_fica_de_fora_quando_o_geral_nao_e_significativo(tmp_path):
    rng = np.random.default_rng(11)
    c = sc.gerar_clientes()
    pct = pd.Series(np.clip(rng.normal(15.5, 5, len(c)), 0, 60))      # sorteio novo, sem relação com o segmento
    c = c.assign(pct_desconto=pct, valor_bruto=c["valor"] / (1 - pct / 100)).assign(desconto_total=lambda t: t["valor_bruto"] - t["valor"])
    r, _ = rodar(tmp_path, c)
    if r["kruskal_wallis"]["significativo_5pct"]:
        pytest.skip("o sorteio calhou significativo; a regra já é testada no outro cenário")
    assert r["post_hoc"] is None and not r["post_hoc_executado"] and "não foi significativo" in r["post_hoc_motivo"]
    assert r["veredito"] == "sem_diferenca_detectavel" and "nenhuma diferença detectável" in " ".join(r["e_dai"]["detalhes_tecnicos"])


def test_reconcilia_com_os_clientes_sinteticos(com_efeito):
    r, c = com_efeito
    ativos = c[c["valor"] > 0]
    assert r["households"] == len(ativos) == sum(g["households"] for g in r["grupos"]) == r["kruskal_wallis"]["n_total_observacoes"]
    assert r["impacto"]["desconto_total_usd"] == pytest.approx(ativos["desconto_total"].sum(), rel=1e-4)
    assert r["impacto"]["taxa_geral_pct"] == pytest.approx(100 * ativos["desconto_total"].sum() / ativos["valor_bruto"].sum(), rel=1e-4)
    assert sum(g["desconto_total_usd"] for g in r["grupos"]) == pytest.approx(r["impacto"]["desconto_total_usd"], rel=1e-4)


def test_sensibilidade_usa_so_quem_tem_cinco_compras_ou_mais(com_efeito):
    r, c = com_efeito
    s = r["sensibilidade"]
    assert s["minimo_compras"] == 5 and s["households"] == int((c["frequencia"] >= 5).sum())
    assert s["households"] == sum(g["households"] for g in s["grupos"]) and s["veredito"] in (
        "sem_diferenca_detectavel", "diferenca_desprezivel", "diferenca_relevante")
    assert "Só com households de 5 ou mais compras" in " ".join(r["e_dai"]["detalhes_tecnicos"])


def test_formato_da_spec_serializa_e_a_limitacao_sempre_diz_que_nao_e_causal(com_efeito, sem_efeito):
    for r, _ in (com_efeito, sem_efeito):
        assert {"normalidade_por_grupo", "kruskal_wallis", "post_hoc", "ic_diferencas", "e_dai", "versao_base", "janela"} <= r.keys()
        assert {"estatistica_H", "p_valor", "eta_quadrado_aprox"} <= r["kruskal_wallis"].keys()
        assert set(r["e_dai"]) == {"conclusao", "evidencia", "acao_recomendada", "impacto_estimado", "limitacoes", "detalhes_tecnicos"}
        assert "não efeito causal" in r["e_dai"]["limitacoes"]
        texto = json.dumps(r, ensure_ascii=False)
        assert "household_key" not in texto and len(texto.encode()) < 16_000
        assert not any("{" in str(v) or "}" in str(v) for v in r["e_dai"].values())
        assert r["versao_base"] == "sintetica1" and r["janela"]["atual"]["semanas"] == [76, 101]
        assert len(r["normalidade_por_grupo"]) == 4 and len(r["ic_diferencas"]) == 6


def test_sem_base_carregada_devolve_erro_legivel(tmp_path):
    anterior = banco._ativo
    banco.definir_banco(tmp_path / "nao_existe.duckdb")
    try:
        r = testar_desconto_entre_segmentos()
        assert "Nenhuma base" in r["erro"] and r["sugestao"]
    finally:
        banco.definir_banco(anterior)


# --- base real, conferida por SQL independente ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(log, "CAMINHO", tmp_path_factory.mktemp("td_real") / "chamadas.jsonl")
    banco.definir_banco(BANCO)
    cache.limpar()
    yield testar_desconto_entre_segmentos()
    banco.fechar_todas()
    banco.definir_banco(None)
    cache.limpar()
    mp.undo()


@precisa_do_banco
def test_real_totais_batem_com_sql_direto_nas_semanas_da_janela(real):
    cur = banco.cursor()
    ini, fim = cur.execute("SELECT semana_ini_atual, semana_fim_atual FROM vw_janela").fetchone()
    desc, bruto, hh = cur.execute("SELECT SUM(desconto_total), SUM(valor_bruto), COUNT(DISTINCT household_key) FROM vw_cliente_semana "
                                  "WHERE WEEK_NO BETWEEN ? AND ?", [ini, fim]).fetchone()
    assert real["households"] == hh == 2421 == real["kruskal_wallis"]["n_total_observacoes"]
    assert real["impacto"]["desconto_total_usd"] == pytest.approx(float(desc), abs=0.01)
    assert real["impacto"]["taxa_geral_pct"] == pytest.approx(100 * float(desc) / float(bruto), abs=0.001)


@precisa_do_banco
def test_real_kruskal_confere_com_scipy_sobre_dados_lidos_por_sql(real):
    cur = banco.cursor()
    h = cur.execute("SELECT household_key, 100.0 * SUM(desconto_total) / SUM(valor_bruto) AS pct, SUM(cestas) AS compras "
                    "FROM vw_cliente_semana WHERE WEEK_NO BETWEEN 76 AND 101 GROUP BY household_key").df()
    seg = rfm.segmentos_por_household(cur)
    d = h.merge(seg, on="household_key")
    k = stats.kruskal(*[d.loc[d.segmento == s, "pct"] for s in d.segmento.unique()])
    assert real["kruskal_wallis"]["estatistica_H"] == pytest.approx(k.statistic, abs=1e-3)
    assert real["kruskal_wallis"]["p_valor"] == pytest.approx(k.pvalue, abs=1e-4)
    d5 = d[d["compras"] >= 5]
    k5 = stats.kruskal(*[d5.loc[d5.segmento == s, "pct"] for s in d5.segmento.unique()])
    assert real["sensibilidade"]["households"] == len(d5) and real["sensibilidade"]["kruskal_wallis"]["p_valor"] == pytest.approx(k5.pvalue, abs=1e-4)
    for g in real["grupos"]:
        assert g["mediana_pct"] == pytest.approx(d.loc[d.segmento == g["segmento"], "pct"].median(), abs=1e-3)


@precisa_do_banco
def test_real_veredito_e_sensibilidade_contam_a_mesma_historia(real):
    assert real["veredito"] == "diferenca_desprezivel" and real["sensibilidade"]["veredito"] == "sem_diferenca_detectavel"
    assert real["kruskal_wallis"]["significativo_5pct"] and real["kruskal_wallis"]["eta_quadrado_aprox"] < CFG_TD["eta2_relevante"]
    assert all(not i["exclui_zero"] for i in real["ic_diferencas"])
    assert real["post_hoc_executado"] and sum(p["significativo_5pct"] for p in real["post_hoc"]) == 1     # só Esporádicos x Regulares
    assert "praticamente o mesmo desconto" in real["e_dai"]["conclusao"] and "a significância desaparece" in " ".join(real["e_dai"]["detalhes_tecnicos"])


@precisa_do_banco
def test_real_quem_tem_poucas_compras_tem_desconto_mais_disperso(real):
    dp = {g["segmento"]: g["desvio_padrao_pp"] for g in real["grupos"]}
    assert dp["Esporádicos"] > 1.4 * dp["Fiéis"] and dp["Em pausa"] > 1.4 * dp["Fiéis"]
