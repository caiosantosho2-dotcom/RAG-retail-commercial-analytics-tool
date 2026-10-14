"""CLV: bootstrap e texto (funções puras), pipeline numa base semanal sintética conferido por cálculo independente,
e a base real conferida contra SQL feito sobre as views."""

import json

import numpy as np
import pandas as pd
import pytest

from src.config import CFG, RAIZ
from src.nucleo import banco, cache, clv, log, rfm
from src.nucleo.clv import NOME_SEM_COMPRA, bootstrap, calcular_clv, montar_e_dai
from tests import sintetico_clv as sc


# --- bootstrap ---------------------------------------------------------------------------------------

def grupo_razao(n_cal=50, n_atual=40, razao=2.0, ruido=0.0, semente=0):
    rng = np.random.default_rng(semente)
    valor = rng.lognormal(2.5, 0.4, n_cal)
    fut = valor * razao * (1 + ruido * rng.standard_normal(n_cal))
    return {"tipo": "razao", "cal_valor": valor, "cal_fut": fut, "atual_valor": rng.lognormal(2.5, 0.4, n_atual), "n_atual": n_atual}


def test_bootstrap_sem_ruido_devolve_a_razao_exata_em_todas_as_reamostras():
    g = {"A": {"tipo": "razao", "cal_valor": np.full(50, 10.0), "cal_fut": np.full(50, 20.0), "atual_valor": np.full(40, 5.0), "n_atual": 40}}
    b = bootstrap(g, 300, 0.95, 1)
    assert np.allclose(b["razao"]["A"], 2.0) and np.allclose(b["receita"]["A"], 10.0) and np.allclose(b["total_receita"], 400.0)
    assert clv._ic(b["razao"]["A"], 0.95) == [2.0, 2.0]


def test_bootstrap_e_reproduzivel_e_a_semente_importa():
    g = {"A": grupo_razao(ruido=0.5)}
    a, b, c = (bootstrap(g, 400, 0.95, s)["razao"]["A"] for s in (7, 7, 8))
    assert np.array_equal(a, b) and not np.array_equal(a, c)


def test_intervalo_cobre_o_valor_verdadeiro_e_estreita_com_mais_households():
    pequeno = bootstrap({"A": grupo_razao(n_cal=40, ruido=0.6, semente=1)}, 1500, 0.95, 3)["razao"]["A"]
    grande = bootstrap({"A": grupo_razao(n_cal=4000, ruido=0.6, semente=1)}, 1500, 0.95, 3)["razao"]["A"]
    lo_p, hi_p = clv._ic(pequeno, 0.95)
    lo_g, hi_g = clv._ic(grande, 0.95)
    assert lo_p <= 2.0 <= hi_p and lo_g <= 2.0 <= hi_g
    assert (hi_g - lo_g) < (hi_p - lo_p) / 4


def test_grupo_de_analogos_usa_a_media_do_ano_anterior_e_o_total_pondera_pelo_tamanho_atual():
    fut = np.array([0.0, 100.0, 200.0, 300.0])
    g = {"S": {"tipo": "analogos", "cal_fut": fut, "n_atual": 10}, "A": grupo_razao(n_atual=20)}
    b = bootstrap(g, 800, 0.95, 5)
    assert b["receita"]["S"].mean() == pytest.approx(fut.mean(), rel=0.03)
    assert np.allclose(b["total_receita"], 10 * b["receita"]["S"] + 20 * b["receita"]["A"])


def test_ic_usa_os_percentis_do_nivel():
    assert clv._ic(np.arange(101.0), 0.90) == pytest.approx([5.0, 95.0])


# --- texto do e daí ----------------------------------------------------------------------------------

def seg(nome, n, clv_medio, ritmo=None, ic=None):
    return {"nome": nome, "n": n, "clv_medio": clv_medio, "ic_95": ic or [clv_medio * 0.95, clv_medio * 1.05],
            "clv_total_usd": n * clv_medio, "ritmo_relativo": ritmo}


def bt(metodo, ingenuo, ganha, de=4, total=True):
    return {"horizonte_semanas": 26, "total": {"erro_metodo_pct": metodo, "erro_ingenuo_pct": ingenuo}, "mae_household_metodo_usd": 321.0,
            "mae_household_ingenuo_usd": 317.0, "segmentos_em_que_o_metodo_ganha": ganha, "segmentos_avaliados": de, "metodo_ganha_no_total": total}


PREM = {"horizonte_semanas": 52, "margem": 0.25}
TOTAL = {"clv_total_usd": 1_103_220.0, "ic_95": [1_063_210.0, 1_143_641.0], "receita_esperada_total_usd": 4_412_881.0}


def test_e_dai_traz_os_quatro_blocos_premissa_e_limitacao_do_backtest():
    e = montar_e_dai([seg("Fiéis", 857, 820, 0.92), seg("Regulares", 980, 326, 1.15), seg("Esporádicos", 426, 135, 2.1)],
                     TOTAL, PREM, bt(-2.9, -4.0, 5, 5), [])
    assert set(e) == {"conclusao", "evidencia", "acao_recomendada", "impacto_estimado", "limitacoes", "detalhes_tecnicos"}
    assert "Fiéis valem US$ 820" in e["conclusao"] and "IC 95%" not in e["conclusao"]
    assert "IC 95%" in " ".join(e["detalhes_tecnicos"])
    assert "ritmo de 2,1x" in e["acao_recomendada"] and "Esporádicos" in e["acao_recomendada"]
    assert "margem assumida de 25%" in e["impacto_estimado"] and "US$ 4.412.881" in e["impacto_estimado"]
    assert "é premissa" in e["limitacoes"] and "não pode ser testado" in e["limitacoes"] and "2,9%" in e["limitacoes"]
    assert "não como previsão individual" in e["limitacoes"] and not any("{" in str(v) for v in e.values())


def test_e_dai_avisa_quando_o_metodo_nao_supera_a_regra_ingenua():
    e = montar_e_dai([seg("Fiéis", 857, 820)], TOTAL, PREM, bt(-9.0, -3.0, 1, 4, total=False), [])
    assert "não superou a regra ingênua" in e["evidencia"]


def test_e_dai_sem_backtest_diz_que_nao_foi_possivel_e_repassa_avisos():
    e = montar_e_dai([seg("Fiéis", 857, 820)], TOTAL, PREM, None, ["O segmento X tem só 5 households."])
    assert "backtest não pôde ser feito" in e["limitacoes"] and "O segmento X tem só 5 households." in e["limitacoes"]


def test_e_dai_com_ritmos_diferentes_mostra_a_faixa():
    e = montar_e_dai([seg("Fiéis", 857, 820), seg("A", 10, 100, 1.5), seg("B", 10, 90, 2.1)], TOTAL, PREM, None, [])
    assert "ritmo de 1,5x a 2,1x" in e["acao_recomendada"]


# --- pipeline numa base semanal sintética --------------------------------------------------------------------

@pytest.fixture(scope="module")
def mundo(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("clv")
    mp = pytest.MonkeyPatch()
    mp.setattr(log, "CAMINHO", pasta / "chamadas.jsonl")
    caminho, semanal, hh = sc.criar_banco(pasta / "clv.duckdb")
    banco.definir_banco(caminho)
    cache.limpar()
    yield {"pasta": pasta, "semanal": semanal, "hh": hh, "r": calcular_clv(), "cur": banco.cursor()}
    banco.fechar_todas()
    banco.definir_banco(None)
    cache.limpar()
    mp.undo()


def gasto(semanal, ids, a, b):
    s = semanal[semanal["WEEK_NO"].between(a, b)].groupby("household_key")["faturamento"].sum()
    return s.reindex(ids).fillna(0.0).to_numpy()


def por_nome(r):
    return {s["nome"]: s for s in r["segmentos"]}


def test_calculo_sem_erro_e_formato_da_spec(mundo):
    r = mundo["r"]
    assert "erro" not in r
    assert {"segmentos", "total", "premissas", "backtest", "e_dai", "versao_base", "janela"} <= r.keys()
    assert {"nome", "n", "clv_medio", "ic_95", "razao_futuro_passado", "calibracao"} <= r["segmentos"][0].keys()
    assert r["versao_base"] == "sintetica_clv" and r["janela"]["atual"]["semanas"] == [76, 101]
    texto = json.dumps(r, ensure_ascii=False)
    assert len(texto.encode()) < 20_000 and "household_key" not in texto


def test_premissas_ficam_explicitas_no_retorno(mundo):
    p = mundo["r"]["premissas"]
    assert p["horizonte_semanas"] == 52 and p["margem"] == 0.25 and p["margem_e_premissa"] is True
    assert "mesmo segmento um ano antes" in p["metodo"] and "não aplicado" in p["desconto_financeiro"]
    assert p["bootstrap"] == {"reamostras": 2000, "nivel": 0.95, "semente": CFG["semente"]}


def test_a_razao_confere_com_um_calculo_independente_em_pandas(mundo):
    cur, semanal = mundo["cur"], mundo["semanal"]
    k = rfm.segmentar_clientes()["k_usado"]
    df_b, _ = rfm.carregar_base(cur, "base")
    nomes_b, _ = rfm.ajustar_segmentos(df_b, k)
    fut = gasto(semanal, df_b["household_key"].to_numpy(), 50, 101)
    r = por_nome(mundo["r"])
    for nome in set(nomes_b):
        m = nomes_b == nome
        esperado = fut[m].sum() / df_b.loc[m, "valor"].sum()
        assert r[nome]["razao_futuro_passado"] == pytest.approx(esperado, abs=1e-3)
        assert r[nome]["calibracao"]["gasto_futuro_usd"] == pytest.approx(fut[m].sum(), abs=0.01)
        assert r[nome]["calibracao"]["households"] == int(m.sum())


def test_clv_e_margem_x_valor_medio_x_razao(mundo):
    for nome, s in por_nome(mundo["r"]).items():
        if nome == NOME_SEM_COMPRA:
            continue
        assert s["receita_esperada_usd"] == pytest.approx(s["valor_medio_janela_usd"] * s["razao_futuro_passado"], rel=2e-3)
        assert s["clv_medio"] == pytest.approx(0.25 * s["receita_esperada_usd"], rel=1e-3)
        assert s["ritmo_relativo"] == pytest.approx(s["razao_futuro_passado"] / 2, abs=1e-3)


def test_valor_medio_da_janela_atual_confere_com_o_rfm(mundo):
    cur = mundo["cur"]
    df_a, _ = rfm.carregar_base(cur, "atual")
    df_a = df_a.merge(rfm.segmentos_por_household(cur), on="household_key")
    for nome, g in df_a.groupby("segmento"):
        assert por_nome(mundo["r"])[nome]["valor_medio_janela_usd"] == pytest.approx(g["valor"].mean(), abs=0.01)
        assert por_nome(mundo["r"])[nome]["n"] == len(g)


def test_o_total_cobre_todos_os_households_e_soma_os_grupos(mundo):
    r, hh, semanal = mundo["r"], mundo["hh"], mundo["semanal"]
    assert r["total"]["households"] == len(hh) == sum(s["n"] for s in r["segmentos"])
    assert r["total"]["clv_total_usd"] == pytest.approx(sum(s["clv_medio"] * s["n"] for s in r["segmentos"]), rel=1e-3)
    sem_compra = set(hh["household_key"]) - set(semanal[semanal["WEEK_NO"].between(76, 101)]["household_key"])
    assert por_nome(r)[NOME_SEM_COMPRA]["n"] == len(sem_compra) > 0


def test_grupo_sem_compra_usa_a_media_dos_analogos_do_ano_anterior(mundo):
    semanal, hh = mundo["semanal"], mundo["hh"]
    sem_base = sorted(set(hh["household_key"]) - set(semanal[semanal["WEEK_NO"].between(24, 49)]["household_key"]))
    esperado = gasto(semanal, np.array(sem_base), 50, 101).mean()
    s = por_nome(mundo["r"])[NOME_SEM_COMPRA]
    assert s["receita_esperada_usd"] == pytest.approx(esperado, abs=0.01) and s["calibracao"]["households"] == len(sem_base)
    assert s["razao_futuro_passado"] is None and s["valor_medio_janela_usd"] == 0.0


def test_intervalo_cobre_o_ponto_e_a_calibracao_soma_o_gasto_de_todos_os_households(mundo):
    r, semanal, hh = mundo["r"], mundo["semanal"], mundo["hh"]
    for s in r["segmentos"]:
        assert s["ic_95"][0] <= s["clv_medio"] <= s["ic_95"][1]
    assert r["total"]["ic_95"][0] <= r["total"]["clv_total_usd"] <= r["total"]["ic_95"][1]
    futuro_total = sum(s["calibracao"]["gasto_futuro_usd"] for s in r["segmentos"])
    assert futuro_total == pytest.approx(semanal[semanal["WEEK_NO"].between(50, 101)]["faturamento"].sum(), abs=0.5)


def test_backtest_confere_com_um_calculo_independente(mundo):
    cur, semanal, bt_ = mundo["cur"], mundo["semanal"], mundo["r"]["backtest"]
    k = rfm.segmentar_clientes()["k_usado"]
    df_b, _ = rfm.carregar_base(cur, "base")
    nomes_b, _ = rfm.ajustar_segmentos(df_b, k)
    fut26 = gasto(semanal, df_b["household_key"].to_numpy(), 50, 75)
    razao26 = {n: fut26[nomes_b == n].sum() / df_b.loc[nomes_b == n, "valor"].sum() for n in set(nomes_b)}
    df2, _ = rfm.base_rfm(cur, 50, 75)
    nomes2, _ = rfm.ajustar_segmentos(df2, k)
    real2 = gasto(semanal, df2["household_key"].to_numpy(), 76, 101)
    for l in bt_["segmentos"]:
        if l["nome"] == NOME_SEM_COMPRA:
            continue
        m = nomes2 == l["nome"]
        assert l["previsto_metodo_usd"] == pytest.approx(df2.loc[m, "valor"].sum() * razao26[l["nome"]], abs=0.5)
        assert l["previsto_ingenuo_usd"] == pytest.approx(df2.loc[m, "valor"].sum(), abs=0.5)
        assert l["real_usd"] == pytest.approx(real2[m].sum(), abs=0.5)
        assert l["erro_metodo_pct"] == pytest.approx(100 * (l["previsto_metodo_usd"] / l["real_usd"] - 1), abs=0.01)
    # o real do backtest, somando todos os grupos, é o gasto de todos os households em 76-101
    assert bt_["total"]["real_usd"] == pytest.approx(semanal[semanal["WEEK_NO"].between(76, 101)]["faturamento"].sum(), abs=0.5)
    assert bt_["segmentos_avaliados"] == len(bt_["segmentos"]) and bt_["calibracao"].startswith("semanas 24-49 -> 50-75")


def test_regra_ingenua_preve_zero_para_quem_nao_comprou(mundo):
    sem = next(l for l in mundo["r"]["backtest"]["segmentos"] if l["nome"] == NOME_SEM_COMPRA)
    assert sem["previsto_ingenuo_usd"] == 0.0 and sem["erro_ingenuo_pct"] == -100.0


def test_margem_escala_o_clv_linearmente_e_nao_mexe_na_razao(mundo, monkeypatch):
    base = mundo["r"]
    monkeypatch.setitem(CFG["analises"]["clv"], "margem", 0.5)
    r2 = calcular_clv()
    for a, b in zip(base["segmentos"], r2["segmentos"]):
        assert b["clv_medio"] == pytest.approx(2 * a["clv_medio"], rel=2e-3) and b["razao_futuro_passado"] == a["razao_futuro_passado"]
        assert b["ic_95"][1] == pytest.approx(2 * a["ic_95"][1], rel=2e-3)
    assert r2["total"]["clv_total_usd"] == pytest.approx(2 * base["total"]["clv_total_usd"], rel=2e-3)
    assert "margem assumida de 50%" in r2["e_dai"]["impacto_estimado"] and r2["premissas"]["margem"] == 0.5


def test_mesma_semente_mesmo_resultado_e_outra_semente_outro_intervalo(mundo, monkeypatch):
    cache.limpar()
    igual = calcular_clv()
    assert [s["ic_95"] for s in igual["segmentos"]] == [s["ic_95"] for s in mundo["r"]["segmentos"]]
    monkeypatch.setitem(CFG, "semente", 99)
    outra = calcular_clv()
    assert [s["ic_95"] for s in outra["segmentos"]] != [s["ic_95"] for s in mundo["r"]["segmentos"]]
    monkeypatch.setitem(CFG, "semente", 42)
    cache.limpar()


def test_filtro_por_segmento_ignora_acento_e_mantem_os_totais(mundo):
    r = calcular_clv(segmento="fieis")
    assert [s["nome"] for s in r["segmentos"]] == ["Fiéis"] and r["total"] == mundo["r"]["total"]


def test_segmento_inexistente_lista_os_validos(mundo):
    r = calcular_clv(segmento="vip")
    assert "erro" in r and "Fiéis" in r["sugestao"] and "segmentos" not in r


def test_resultado_e_cacheado(mundo, monkeypatch):
    chamadas = []
    original = clv._calcular
    monkeypatch.setattr(clv, "_calcular", lambda *a, **k: chamadas.append(1) or original(*a, **k))
    calcular_clv()
    assert chamadas == []


def test_chamada_gera_linha_de_log(mundo):
    calcular_clv()
    ultimo = json.loads((mundo["pasta"] / "chamadas.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ultimo["ferramenta"] == "calcular_clv" and ultimo["erro"] is None


def test_e_dai_cita_numeros_que_batem_com_o_retorno(mundo):
    r = mundo["r"]
    topo = max(r["segmentos"], key=lambda s: s["clv_medio"])
    usd = lambda x: "US$ " + f"{x:,.0f}".replace(",", ".")
    assert usd(topo["clv_medio"]) in r["e_dai"]["conclusao"] and usd(r["total"]["clv_total_usd"]) in r["e_dai"]["evidencia"]
    assert usd(r["total"]["receita_esperada_total_usd"]) in r["e_dai"]["impacto_estimado"]


# --- erros e condições limite ---------------------------------------------------------------------------------

def test_horizonte_diferente_do_deslocamento_devolve_erro_legivel(mundo, monkeypatch):
    monkeypatch.setitem(CFG["analises"]["clv"], "horizonte_semanas", 26)
    r = calcular_clv()
    assert "erro" in r and "deslocamento" in r["erro"] and "sugestao" in r and "Traceback" not in json.dumps(r)


def test_nomes_de_segmento_diferentes_entre_janelas_dao_erro_legivel(mundo, monkeypatch):
    original = rfm.ajustar_segmentos

    def trocado(df, k, *a, **kw):
        nomes, perfil = original(df, k, *a, **kw)
        if len(df) == len(rfm.carregar_base(mundo["cur"], "base")[0]):          # só a janela base
            nomes = np.where(nomes == "Fiéis", "Campeões", nomes)
        return nomes, perfil

    monkeypatch.setattr(rfm, "ajustar_segmentos", trocado)
    monkeypatch.setitem(CFG["analises"]["clv"], "n_bootstrap", 500)
    r = calcular_clv()
    assert "erro" in r and "mesmos nomes" in r["erro"] and "Campeões" in r["erro"] and "sugestao" in r


def test_grupo_pequeno_na_calibracao_gera_aviso(mundo, monkeypatch):
    monkeypatch.setitem(CFG["analises"]["clv"], "tamanho_minimo_grupo", 10_000)
    r = calcular_clv()
    assert r["avisos"] and all("tem só" in a for a in r["avisos"]) and r["avisos"][0] in r["e_dai"]["limitacoes"]


def test_sem_semanas_suficientes_o_backtest_e_declarado_indisponivel(mundo, monkeypatch):
    original = clv.janelas
    monkeypatch.setattr(clv, "janelas", lambda cur: {**original(cur), "L": 30})
    cache.limpar()          # a chave do cache não inclui o que o monkeypatch troca: sem isto, voltaria o resultado guardado
    try:
        r = calcular_clv()
        assert "erro" not in r and r["backtest"] is None and "backtest não pôde ser feito" in r["e_dai"]["limitacoes"]
    finally:
        cache.limpar()      # o resultado artificial não pode vazar para os testes seguintes


def test_sem_base_devolve_erro_legivel(tmp_path):
    anterior = banco._ativo
    banco.definir_banco(tmp_path / "nao_existe.duckdb")
    try:
        assert "Nenhuma base" in calcular_clv()["erro"]
    finally:
        banco.definir_banco(anterior)


# --- base real, conferida contra SQL feito sobre as views ------------------------------------------------------

BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


@pytest.fixture(scope="module")
def real():
    banco.definir_banco(BANCO)
    cache.limpar()
    yield calcular_clv()
    banco.fechar_todas()
    banco.definir_banco(None)
    cache.limpar()


def sql(texto):
    from src.nucleo.consulta import executar_consulta
    return executar_consulta(texto)["linhas"][0]


@precisa_do_banco
def test_real_cobre_os_2500_households_com_os_cinco_grupos(real):
    assert "erro" not in real and real["total"]["households"] == 2500
    assert [s["nome"] for s in real["segmentos"]] == ["Fiéis", "Regulares", "Esporádicos", "Em pausa", NOME_SEM_COMPRA]
    assert [s["n"] for s in real["segmentos"]][-1] == 79 == sql("SELECT COUNT(*) FROM dim_household")[0] - 2421


@precisa_do_banco
def test_real_o_gasto_somado_bate_com_sql_sobre_as_views(real):
    segs = real["segmentos"]
    futuro = sum(s["calibracao"]["gasto_futuro_usd"] for s in segs)
    passado = sum(s["calibracao"]["gasto_passado_usd"] for s in segs)
    atual = sum(s["n"] * s["valor_medio_janela_usd"] for s in segs)
    assert futuro == pytest.approx(sql("SELECT SUM(faturamento) FROM vw_cliente_semana WHERE WEEK_NO BETWEEN 50 AND 101")[0], abs=1.0)
    assert passado == pytest.approx(sql("SELECT SUM(faturamento) FROM vw_metricas_cesta WHERE periodo = 'base'")[0], abs=1.0)
    assert atual == pytest.approx(sql("SELECT SUM(valor) FROM vw_metricas_cliente WHERE periodo = 'atual'")[0], abs=2.0)
    assert sum(s["calibracao"]["households"] for s in segs) == 2500


@precisa_do_banco
def test_real_backtest_cobre_todos_os_households_e_o_metodo_ganha(real):
    bt_ = real["backtest"]
    assert bt_["total"]["real_usd"] == pytest.approx(sql("SELECT SUM(faturamento) FROM vw_metricas_cesta WHERE periodo = 'atual'")[0], abs=1.0)
    assert bt_["metodo_ganha_no_total"] is True and bt_["segmentos_em_que_o_metodo_ganha"] >= bt_["segmentos_avaliados"] - 1
    assert abs(bt_["total"]["erro_metodo_pct"]) < 6 and bt_["mae_household_metodo_usd"] < 450


@precisa_do_banco
def test_real_ordem_de_grandeza_e_premissas(real):
    s = por_nome(real)
    assert s["Fiéis"]["clv_medio"] > s["Regulares"]["clv_medio"] > s["Esporádicos"]["clv_medio"] > s["Em pausa"]["clv_medio"]
    assert 700 < s["Fiéis"]["clv_medio"] < 950 and s["Fiéis"]["ritmo_relativo"] < 1.05
    assert s["Esporádicos"]["ritmo_relativo"] > 1.5 and s["Em pausa"]["ritmo_relativo"] > 1.5      # voltam a gastar acima do ritmo anterior
    assert real["premissas"]["margem"] == 0.25 and real["premissas"]["horizonte_semanas"] == 52
    receita, atual = real["total"]["receita_esperada_total_usd"], sql("SELECT SUM(faturamento) FROM vw_metricas_cesta WHERE periodo = 'atual'")[0]
    assert 0.9 < receita / (2 * atual) < 1.15           # 52 semanas esperadas ≈ 2x a janela de 26, sem explosão nem queda


@precisa_do_banco
def test_real_e_dai_e_intervalos(real):
    e = real["e_dai"]
    assert "Fiéis valem US$" in e["conclusao"] and "premissa" in e["limitacoes"] and "backtest de 26 semanas" in e["limitacoes"]
    assert all(s["ic_95"][0] <= s["clv_medio"] <= s["ic_95"][1] for s in real["segmentos"])
    assert real["total"]["ic_95"][0] < real["total"]["clv_total_usd"] < real["total"]["ic_95"][1]
