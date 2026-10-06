"""Churn (pausa longa): população e rótulo conferidos à mão, vazamento de futuro, métricas, painel sintético e base real."""

import copy
import json
import re

import numpy as np
import pytest
from sklearn.metrics import average_precision_score, roc_auc_score

from src.config import CFG, RAIZ
from src.nucleo import banco, cache, churn, log
from src.nucleo.churn import (ChurnIndisponivel, Painel, bootstrap_auc, calibracao_por_decil, escolher_k, escolher_limiar,
                              fotografar, fotos_do_plano, metricas_binarias, montar_e_dai, prever_churn)
from tests import sintetico_clv as sc

CFG_CHURN = CFG["analises"]["churn"]


# --- população, variáveis e rótulo, conferidos à mão ---------------------------------------------------------

def painel_a_mao(fim=45):
    """Seis households em semanas 0..fim (a semana 0 não existe). T=30, horizonte 8, histórico mínimo 16, ativo = 8 semanas."""
    comp = np.zeros((6, fim + 1))
    comp[0, 1:41] = 1                                   # A: toda semana
    comp[1, 1:31] = 1                                   # B: compra até a semana 30 e para
    comp[2, 1:21] = 1                                   # C: parou na 20 -> já em pausa em T=30
    comp[3, 25:41] = 1                                  # D: primeira compra na 25 -> pouco histórico em T=30
    comp[4, [10, 23, 30, 36]] = 1                       # E: esparso; volta na semana 36
    # F (linha 5): nunca comprou
    return Painel(np.array([101, 102, 103, 104, 105, 106]), comp, comp * 10.0, fim)


def test_populacao_e_rotulo_batem_com_o_calculo_a_mao():
    X, y, hh, rec = fotografar(painel_a_mao(), 30, CFG_CHURN)
    assert list(hh) == [101, 102, 105]                  # C (em pausa), D (pouco histórico) e F (sem compra) ficam de fora
    assert list(y) == [0, 1, 0]                         # B para de comprar; A e E compram nas 8 semanas seguintes
    assert list(rec) == [0, 0, 0]


def test_variaveis_de_um_household_batem_com_o_calculo_a_mao():
    X, _, hh, _ = fotografar(painel_a_mao(), 30, CFG_CHURN)
    b, e = X[list(hh).index(102)], X[list(hh).index(105)]
    # B: recência 0; 8 compras nas semanas 23-30; gasto 10 x 26 semanas (5-30); 26 semanas com compra; nenhuma pausa
    assert b[0] == 0 and b[1] == pytest.approx(np.log1p(8)) and b[2] == pytest.approx(np.log1p(260)) and b[3] == 26 and b[4] == 0
    # E: compras nas semanas 23 e 30 (2); gasto 10 x 2 na janela 5-30 (semanas 10, 23, 30 = 30); 3 semanas com compra;
    # maior pausa 12 (semanas 11-22)
    assert e[1] == pytest.approx(np.log1p(2)) and e[2] == pytest.approx(np.log1p(30)) and e[3] == 3 and e[4] == 12


def test_o_futuro_nao_muda_as_variaveis_nem_a_populacao():
    """Vazamento: mexer em qualquer compra depois de T não pode alterar as variáveis da foto em T."""
    p = painel_a_mao()
    antes = fotografar(p, 30, CFG_CHURN, com_rotulo=False)
    p2 = copy.deepcopy(p)
    p2.compras[:, 31:] = np.random.default_rng(0).integers(0, 3, p2.compras[:, 31:].shape)
    p2.valor[:, 31:] = p2.compras[:, 31:] * 99
    depois = fotografar(p2, 30, CFG_CHURN, com_rotulo=False)
    assert np.array_equal(antes[0], depois[0]) and np.array_equal(antes[2], depois[2]) and antes[1] is None


def test_o_rotulo_olha_so_as_proximas_8_semanas():
    p = painel_a_mao()
    y1 = fotografar(p, 30, CFG_CHURN)[1]
    p2 = copy.deepcopy(p)
    p2.compras[1, 39:] = 1                              # B volta na semana 39 = T + 9: fora do horizonte
    assert list(fotografar(p2, 30, CFG_CHURN)[1]) == list(y1)
    p2.compras[1, 38] = 1                               # na semana 38 = T + 8: dentro do horizonte
    assert list(fotografar(p2, 30, CFG_CHURN)[1]) == [0, 0, 0]


def test_sem_rotulo_nao_devolve_y():
    assert fotografar(painel_a_mao(), 30, CFG_CHURN, com_rotulo=False)[1] is None


# --- plano de fotos --------------------------------------------------------------------------------------------

def test_plano_de_fotos_da_base_real_e_sem_sobreposicao():
    plano = fotos_do_plano(101, CFG_CHURN)
    h = CFG_CHURN["horizonte_semanas"]
    assert plano["treino"] == [30, 34, 38, 42, 46, 50, 54, 58, 62, 66] and plano["validacao"] == 77 and plano["teste"] == [85, 93]
    assert max(plano["treino"]) + h <= plano["validacao"]            # rótulos de treino terminam antes da validação
    assert plano["validacao"] + h <= min(plano["teste"])             # rótulos da validação terminam antes do teste
    assert plano["teste"][0] + h <= plano["teste"][1]                # as duas fotos de teste não compartilham rótulo
    assert plano["teste"][1] + h <= 101                              # o último rótulo existe


@pytest.mark.parametrize("mudanca,trecho", [
    ({"treino_inicio_antes_do_fim": 95}, "semanas suficientes"),
    ({"teste_antes_do_fim": [16, 3]}, "passa do fim|se sobrepõem|invadem"),
    ({"teste_antes_do_fim": [16, 12]}, "se sobrepõem"),
    ({"validacao_antes_do_fim": 30}, "invadem"),
    ({"treino_fim_antes_do_fim": 20}, "invadem"),
    ({"teste_antes_do_fim": [16, 7]}, "passa do fim"),
])
def test_plano_que_nao_cabe_da_erro_legivel(mudanca, trecho):
    cfg = {**CFG_CHURN, **mudanca}
    with pytest.raises(ChurnIndisponivel) as e:
        fotos_do_plano(101, cfg)
    assert re.search(trecho, e.value.erro) and e.value.sugestao


def test_poucas_semanas_de_historico_da_erro_legivel():
    with pytest.raises(ChurnIndisponivel, match="semanas suficientes"):
        fotos_do_plano(50, CFG_CHURN)


# --- limiar, regra simples e métricas --------------------------------------------------------------------------

def test_limiar_maximiza_o_f1_da_validacao_e_o_empate_fica_com_o_menor():
    y = np.array([0, 0, 0, 0, 1, 1, 1, 0, 0, 1])
    prob = np.array([0.02, 0.05, 0.1, 0.12, 0.4, 0.5, 0.6, 0.15, 0.3, 0.7])
    t = escolher_limiar(y, prob)
    assert 0.3 < t <= 0.4                              # acima de 0.3 (o falso positivo mais alto) e até 0.4 (o menor positivo)
    constante = escolher_limiar(np.array([0, 1, 0, 1]), np.full(4, 0.5))
    assert constante == 0.01                           # tudo empata: vence o menor


def test_regra_simples_escolhe_o_k_certo():
    rec = np.array([0, 1, 2, 3, 4, 5, 6, 7] * 20)
    y = (rec >= 5).astype(int)
    assert escolher_k(rec, y, 7) == 5


def test_metricas_binarias_conferem_com_as_contagens():
    y = np.array([1, 1, 1, 0, 0, 0, 0, 1])
    pred = np.array([1, 1, 0, 1, 0, 0, 0, 0])
    m = metricas_binarias(y, pred)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 2, 3) and m["alertas"] == 3
    assert m["precisao"] == pytest.approx(2 / 3) and m["recall"] == pytest.approx(0.5) and m["f1"] == pytest.approx(4 / 7)


def test_metricas_sem_alertas_nao_dividem_por_zero():
    m = metricas_binarias(np.array([0, 1, 0]), np.array([0, 0, 0]))
    assert m["precisao"] == 0.0 and m["recall"] == 0.0 and m["alertas"] == 0


def dados_com_sinal(n=1500, semente=3):
    rng = np.random.default_rng(semente)
    hh = np.repeat(np.arange(n // 2), 2)
    y = (rng.random(n) < 0.15).astype(int)
    prob = np.clip(0.1 + 0.5 * y + 0.25 * rng.standard_normal(n), 0.001, 0.999)
    base = rng.random(n) + 0.3 * y
    return y, prob, base, hh


def test_bootstrap_do_auc_e_reproduzivel_e_o_ponto_cai_dentro_do_intervalo():
    y, prob, base, hh = dados_com_sinal()
    a = bootstrap_auc(y, prob, base, hh, 300, 0.95, 5)
    b = bootstrap_auc(y, prob, base, hh, 300, 0.95, 5)
    assert a == b and bootstrap_auc(y, prob, base, hh, 300, 0.95, 6) != a
    lo, hi = a["diferenca_auc_ic"]
    assert lo < roc_auc_score(y, prob) - roc_auc_score(y, base) < hi and lo < a["diferenca_auc"] < hi


def test_bootstrap_reamostra_por_household_e_o_intervalo_fica_mais_largo_que_por_linha():
    y, prob, base, hh = dados_com_sinal(2000)
    por_household = bootstrap_auc(y, prob, base, hh, 300, 0.95, 1)["diferenca_auc_ic"]
    por_linha = bootstrap_auc(y, prob, base, np.arange(len(y)), 300, 0.95, 1)["diferenca_auc_ic"]
    # duas linhas por household: o intervalo por household não pode ser mais estreito que o por linha
    assert (por_household[1] - por_household[0]) >= 0.8 * (por_linha[1] - por_linha[0])


def test_calibracao_por_decil():
    rng = np.random.default_rng(1)
    prob = rng.random(5000) ** 2
    y = (rng.random(5000) < prob).astype(int)
    c = calibracao_por_decil(y, prob)
    assert [d["decil"] for d in c] == list(range(1, 11)) and sum(d["households"] for d in c) == 5000
    assert all(abs(d["previsto_pct"] - d["observado_pct"]) < 8 for d in c)
    assert c[0]["previsto_pct"] < c[-1]["previsto_pct"]


# --- texto do e daí --------------------------------------------------------------------------------------------

def resultado_exemplo(ic_dif=(0.087, 0.147), mesmo_topo=False):
    seg = lambda nome, n, risco, esp, alertas, valor: {"nome": nome, "households": n, "risco_medio_pct": risco, "pausas_esperadas": esp,
                                                      "alertas": alertas, "valor_em_risco_usd": valor}
    segs = [seg("Fiéis", 857, 0.6, 5.2, 0, 2517.0), seg("Regulares", 966, 4.5, 43.7, 20, 7157.0 if not mesmo_topo else 100.0),
            seg("Esporádicos", 380, 22.9, 87.1, 223, 3031.0 if not mesmo_topo else 20000.0)]
    return {"horizonte_semanas": 8, "limiar": 0.17, "diferenca_auc_ic": list(ic_dif),
            "modelo": {"auc": 0.853, "precisao": 0.287, "recall": 0.481, "alertas": 473},
            "baseline": {"auc": 0.738}, "risco_por_segmento": segs, "retorno_apos_pausa": {"janela_semanas": 18, "taxa_pct": 80.0},
            "ja_em_pausa": {"households": 297}, "valor_em_risco_usd": 12706.0, "valor_em_risco_pct_do_periodo": 1.9}


def test_e_dai_traz_os_quatro_blocos_com_numeros_em_portugues():
    e = montar_e_dai(resultado_exemplo())
    assert set(e) == {"conclusao", "acao_recomendada", "impacto_estimado", "limitacoes"}
    assert "2.203 households" in e["conclusao"] and "22,9%" in e["conclusao"] and "AUC 0,85 contra 0,74" in e["conclusao"]
    assert "243 households em alerta hoje" in e["acao_recomendada"] and "limiar 0,17" in e["acao_recomendada"]
    assert "US$ 12.706" in e["impacto_estimado"] and "80% de quem pausa" in e["impacto_estimado"]
    assert "Pausa não é saída" in e["limitacoes"] and "297 households já estão em pausa" in e["limitacoes"] and "Precisão modesta" in e["limitacoes"]
    junto = " ".join(e.values())
    assert not re.search(r"\d\.\d", junto.replace("2.203", "").replace("12.706", "")), "decimais devem usar vírgula"
    assert "{" not in junto


def test_e_dai_separa_onde_estao_as_pausas_de_onde_esta_o_dinheiro():
    diferente = montar_e_dai(resultado_exemplo())["acao_recomendada"]
    igual = montar_e_dai(resultado_exemplo(mesmo_topo=True))["acao_recomendada"]
    assert "as pausas se concentram nos Esporádicos, mas o dinheiro em risco está nos Regulares" in diferente
    assert "Esporádicos concentram as pausas e o valor em risco" in igual


def test_e_dai_admite_quando_o_modelo_nao_supera_a_regra():
    e = montar_e_dai(resultado_exemplo(ic_dif=(-0.02, 0.04)))
    assert "não superou a regra simples" in e["conclusao"] and "use a regra" in e["conclusao"]
    assert "ordena melhor" not in e["conclusao"]


# --- pipeline numa base semanal sintética ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def mundo(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("churn")
    mp = pytest.MonkeyPatch()
    mp.setattr(log, "CAMINHO", pasta / "chamadas.jsonl")
    caminho, semanal, hh = sc.criar_banco(pasta / "churn.duckdb")
    banco.definir_banco(caminho)
    cache.limpar()
    yield {"pasta": pasta, "semanal": semanal, "hh": hh, "r": prever_churn(), "cur": banco.cursor()}
    banco.fechar_todas()
    banco.definir_banco(None)
    cache.limpar()
    mp.undo()


def test_formato_da_spec(mundo):
    r = mundo["r"]
    assert "erro" not in r
    assert {"definicao_churn", "periodo_treino", "periodo_teste", "auc_modelo", "auc_baseline", "precisao_recall_classe_churn",
            "matriz_confusao", "principais_fatores", "risco_por_segmento", "e_dai", "versao_base", "janela"} <= r.keys()
    assert r["versao_base"] == "sintetica_clv" and r["janela"]["atual"]["semanas"] == [76, 101]
    texto = json.dumps(r, ensure_ascii=False)
    assert len(texto.encode()) < 20_000 and "household_key" not in texto


def test_matriz_de_confusao_e_metricas_sao_coerentes(mundo):
    r = mundo["r"]
    for quem in ("modelo", "baseline"):
        c = r["matriz_confusao"][quem]
        assert c["tn"] + c["fp"] + c["fn"] + c["tp"] == r["linhas"]["teste"]
        assert r["precisao_recall_classe_churn"][quem]["precisao"] == pytest.approx(c["tp"] / max(1, c["tp"] + c["fp"]), abs=1e-3)
        assert r["precisao_recall_classe_churn"][quem]["recall"] == pytest.approx(c["tp"] / max(1, c["tp"] + c["fn"]), abs=1e-3)
    m = r["matriz_confusao"]["modelo"]
    assert r["prevalencia_pct"]["teste"] == pytest.approx(100 * (m["fn"] + m["tp"]) / r["linhas"]["teste"], abs=1e-2)


def test_o_modelo_ganha_da_regra_simples_e_o_intervalo_diz_isso(mundo):
    r = mundo["r"]
    assert r["auc_modelo"] > r["auc_baseline"] and r["diferenca_auc_ic"][0] > 0
    assert r["diferenca_auc_ic"][0] < r["diferenca_auc"] < r["diferenca_auc_ic"][1]
    assert "ordena melhor" in r["e_dai"]["conclusao"]


def test_limiar_k_e_coeficientes_nao_dependem_dos_rotulos_de_teste(mundo, monkeypatch):
    """Vazamento no pipeline: embaralhar os rótulos das fotos de teste muda o AUC, mas não o limiar, o k nem o modelo."""
    base = mundo["r"]
    plano = fotos_do_plano(101, CFG_CHURN)
    original = churn.fotografar
    rng = np.random.default_rng(0)

    def embaralhado(p, T, cfg=None, com_rotulo=True):
        X, y, hh, rec = original(p, T, cfg, com_rotulo)
        return X, (rng.permutation(y) if com_rotulo and T in plano["teste"] else y), hh, rec

    monkeypatch.setattr(churn, "fotografar", embaralhado)
    cache.limpar()
    try:
        r2 = prever_churn()
    finally:
        cache.limpar()
    assert r2["limiar"] == base["limiar"] and r2["k_baseline"] == base["k_baseline"]
    assert r2["principais_fatores"] == base["principais_fatores"]
    assert r2["auc_modelo"] != base["auc_modelo"] and r2["auc_modelo"] < 0.6          # sem sinal nenhum nos rótulos de teste


def test_populacao_prevista_confere_com_pandas_independente(mundo):
    semanal, r = mundo["semanal"], mundo["r"]
    por_h = semanal.groupby("household_key")["WEEK_NO"].agg(["min", "max"])
    esperado = int(((por_h["max"] >= 94) & (por_h["min"] <= 101 - 15)).sum())
    assert r["populacao_prevista"] == esperado == sum(s["households"] for s in r["risco_por_segmento"])
    assert r["ja_em_pausa"]["households"] == len(mundo["hh"]) - esperado
    assert sum(r["ja_em_pausa"]["por_segmento"].values()) == r["ja_em_pausa"]["households"]


def test_prevalencia_do_teste_confere_com_pandas_independente(mundo):
    semanal, r = mundo["semanal"], mundo["r"]
    por_h = semanal.groupby("household_key")["WEEK_NO"].agg(["min"])
    linhas = positivos = 0
    for T in (85, 93):
        ate_t = semanal[semanal["WEEK_NO"] <= T].groupby("household_key")["WEEK_NO"].max()
        pop = [h for h, ult in ate_t.items() if ult >= T - 7 and por_h.loc[h, "min"] <= T - 15]
        futuro = set(semanal[semanal["WEEK_NO"].between(T + 1, T + 8)]["household_key"])
        linhas += len(pop)
        positivos += sum(1 for h in pop if h not in futuro)
    c = r["matriz_confusao"]["modelo"]
    assert r["linhas"]["teste"] == linhas and c["fn"] + c["tp"] == positivos


def test_valor_em_risco_soma_os_segmentos_e_o_risco_tem_ordem_de_negocio(mundo):
    r = mundo["r"]
    assert sum(s["valor_em_risco_usd"] for s in r["risco_por_segmento"]) == pytest.approx(r["valor_em_risco_usd"], rel=1e-3)
    assert sum(s["pausas_esperadas"] for s in r["risco_por_segmento"]) > 0
    riscos = {s["nome"]: s["risco_medio_pct"] for s in r["risco_por_segmento"]}
    assert riscos["Fiéis"] == min(riscos.values())


def test_fatores_tem_odds_ratio_leitura_em_portugues_e_a_variavel_dominante_com_sinal_certo(mundo):
    """No painel sintético as cinco variáveis medem a mesma probabilidade latente de compra (correlação até 0,96): só a
    dominante tem sinal garantido. Os cinco sinais de negócio são conferidos na base real (test_real_fatores...)."""
    f = {x["variavel"]: x for x in mundo["r"]["principais_fatores"]}
    assert f["semanas_com_compra_26s"]["efeito"] == "reduz o risco"
    assert all(x["odds_ratio_por_dp"] == pytest.approx(np.exp(x["coeficiente_padronizado"]), rel=2e-3) for x in f.values())
    assert [x["variavel"] for x in mundo["r"]["principais_fatores"]][0] == max(f, key=lambda k: abs(f[k]["coeficiente_padronizado"]))
    assert "constância" in f["semanas_com_compra_26s"]["leitura"]


def test_curva_de_limiar_inclui_o_escolhido_e_a_troca_precisao_recall(mundo):
    curva = mundo["r"]["curva_limiar"]
    assert sum(1 for c in curva if c["escolhido"]) == 1 and next(c for c in curva if c["escolhido"])["limiar"] == mundo["r"]["limiar"]
    por_limiar = sorted(curva, key=lambda c: c["limiar"])
    assert por_limiar[0]["recall"] >= por_limiar[-1]["recall"] and por_limiar[0]["alertas"] >= por_limiar[-1]["alertas"]


def test_retorno_apos_a_pausa_e_calculado_nas_fotos_de_treino(mundo):
    ret = mundo["r"]["retorno_apos_pausa"]
    assert ret["pausas_observadas"] > 0 and ret["minimo_por_foto_pct"] <= ret["taxa_pct"] <= ret["maximo_por_foto_pct"] <= 100


def test_filtro_por_segmento_ignora_acento_e_mantem_o_resto(mundo):
    r = prever_churn(segmento="fieis")
    assert [s["nome"] for s in r["risco_por_segmento"]] == ["Fiéis"] and r["auc_modelo"] == mundo["r"]["auc_modelo"]
    erro = prever_churn(segmento="vip")
    assert "erro" in erro and "Fiéis" in erro["sugestao"]


def test_resultado_e_cacheado_e_reproduzivel(mundo, monkeypatch):
    chamadas = []
    original = churn._calcular
    monkeypatch.setattr(churn, "_calcular", lambda *a, **k: chamadas.append(1) or original(*a, **k))
    assert prever_churn() == {**mundo["r"]} and chamadas == []
    cache.limpar()
    de_novo = prever_churn()
    assert chamadas == [1] and de_novo["auc_modelo"] == mundo["r"]["auc_modelo"] and de_novo["limiar"] == mundo["r"]["limiar"]


def test_chamada_gera_linha_de_log(mundo):
    prever_churn()
    ultimo = json.loads((mundo["pasta"] / "chamadas.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ultimo["ferramenta"] == "prever_churn" and ultimo["erro"] is None


def test_plano_que_nao_cabe_nos_dados_devolve_erro_legivel_sem_stack_trace(mundo, monkeypatch):
    monkeypatch.setitem(CFG_CHURN, "treino_inicio_antes_do_fim", 95)
    r = prever_churn()
    assert "erro" in r and "semanas suficientes" in r["erro"] and "sugestao" in r and "Traceback" not in json.dumps(r)


def test_sem_base_devolve_erro_legivel(tmp_path):
    anterior = banco._ativo
    banco.definir_banco(tmp_path / "nao_existe.duckdb")
    try:
        assert "Nenhuma base" in prever_churn()["erro"]
    finally:
        banco.definir_banco(anterior)


# --- base real, conferida contra SQL feito sobre a view -----------------------------------------------------------

BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


@pytest.fixture(scope="module")
def real():
    banco.definir_banco(BANCO)
    cache.limpar()
    yield prever_churn()
    banco.fechar_todas()
    banco.definir_banco(None)
    cache.limpar()


def sql(texto):
    from src.nucleo.consulta import executar_consulta
    return executar_consulta(texto)["linhas"][0]


def populacao_sql(T):
    return sql(f"SELECT COUNT(*) FROM (SELECT household_key FROM vw_cliente_semana GROUP BY household_key "
               f"HAVING MAX(WEEK_NO) FILTER (WHERE WEEK_NO <= {T}) >= {T - 7} AND MIN(WEEK_NO) <= {T - 15})")[0]


def positivos_sql(T):
    return sql(f"SELECT COUNT(*) FROM (SELECT household_key FROM vw_cliente_semana GROUP BY household_key "
               f"HAVING MAX(WEEK_NO) FILTER (WHERE WEEK_NO <= {T}) >= {T - 7} AND MIN(WEEK_NO) <= {T - 15} "
               f"AND COUNT(*) FILTER (WHERE WEEK_NO BETWEEN {T + 1} AND {T + 8}) = 0)")[0]


@precisa_do_banco
def test_real_populacao_e_positivos_do_teste_batem_com_sql(real):
    assert real["linhas"]["teste"] == populacao_sql(85) + populacao_sql(93)
    m = real["matriz_confusao"]["modelo"]
    assert m["fn"] + m["tp"] == positivos_sql(85) + positivos_sql(93)
    assert real["populacao_prevista"] == populacao_sql(101) == 2203
    assert real["populacao_prevista"] + real["ja_em_pausa"]["households"] == 2500


@precisa_do_banco
def test_real_o_modelo_ganha_da_regra_e_o_intervalo_exclui_zero(real):
    assert real["auc_modelo"] > real["auc_baseline"] + 0.05 and real["diferenca_auc_ic"][0] > 0
    assert real["modelo"]["auc_pr"] > 2 * real["prevalencia_pct"]["teste"] / 100
    assert 5.5 < real["prevalencia_pct"]["treino"] < 7.5 and 5.5 < real["prevalencia_pct"]["teste"] < 7.5
    assert 1 <= real["k_baseline"] <= 7 and 0.05 < real["limiar"] < 0.5


@precisa_do_banco
def test_real_calibracao_por_decil(real):
    c = real["calibracao"]
    assert len(c) == 10 and max(abs(d["previsto_pct"] - d["observado_pct"]) for d in c) < 8
    assert sum(abs(d["previsto_pct"] - d["observado_pct"]) * d["households"] for d in c) / sum(d["households"] for d in c) < 3


@precisa_do_banco
def test_real_risco_por_segmento_e_retorno(real):
    riscos = {s["nome"]: s["risco_medio_pct"] for s in real["risco_por_segmento"]}
    assert riscos["Fiéis"] < riscos["Regulares"] < riscos["Esporádicos"] and riscos["Fiéis"] < 2
    assert sum(s["households"] for s in real["risco_por_segmento"]) == 2203
    assert 65 < real["retorno_apos_pausa"]["taxa_pct"] < 90 and real["retorno_apos_pausa"]["pausas_observadas"] > 500
    assert real["ja_em_pausa"]["por_segmento"]["Em pausa"] == 158 and real["ja_em_pausa"]["por_segmento"]["Sem compra na janela"] == 79


@precisa_do_banco
def test_real_fatores_tem_o_sinal_de_negocio_nas_cinco_variaveis(real):
    efeito = {f["variavel"]: f["efeito"] for f in real["principais_fatores"]}
    assert efeito == {"recencia_semanas": "aumenta o risco", "maior_pausa_26s": "aumenta o risco", "log_compras_8s": "reduz o risco",
                      "log_valor_26s": "reduz o risco", "semanas_com_compra_26s": "reduz o risco"}
    assert real["principais_fatores"][0]["variavel"] == "semanas_com_compra_26s"        # a constância é o maior protetor


@precisa_do_banco
def test_real_e_dai_cita_pausa_retorno_e_valor(real):
    e = real["e_dai"]
    assert "Esporádicos concentram" in e["conclusao"] and "ordena melhor" in e["conclusao"]
    assert "Regulares" in e["acao_recomendada"] and "dinheiro em risco" in e["acao_recomendada"]
    assert "volta em até 18 semanas" in e["impacto_estimado"] and "Pausa não é saída" in e["limitacoes"]
    assert 5_000 < real["valor_em_risco_usd"] < 30_000 and real["valor_em_risco_pct_do_periodo"] < 5
