"""RFM sobre a base real: K, nomes, perfil, exclusões e consistência com o SQL do chat e com as views."""

import pytest

from src.config import CFG, RAIZ
from src.nucleo import banco, cache
from src.nucleo.consulta import executar_consulta
from src.nucleo.rfm import coorte_retencao, segmentar_clientes

BANCO = RAIZ / CFG["banco"]["arquivo"]
pytestmark = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


@pytest.fixture(scope="module")
def r():
    banco.definir_banco(BANCO)
    cache.limpar()
    yield segmentar_clientes()
    banco.fechar_todas()
    banco.definir_banco(None)


def por_nome(r):
    return {s["nome"]: s for s in r["segmentos"]}


def test_a_regra_escolhe_k4_e_os_quatro_nomes_batem_com_o_perfil(r):
    assert "erro" not in r and r["k_usado"] == 4 and r["regra_k_cumprida"] is True
    s = por_nome(r)
    assert set(s) == {"Fiéis", "Regulares", "Esporádicos", "Em pausa"}
    # o nome descreve o perfil real: Fiéis têm o maior valor e frequência e a menor recência; Em pausa, a maior recência
    assert s["Fiéis"]["valor_medio_usd"] == max(x["valor_medio_usd"] for x in s.values())
    assert s["Fiéis"]["frequencia_media"] == max(x["frequencia_media"] for x in s.values())
    assert s["Fiéis"]["recencia_media_dias"] == min(x["recencia_media_dias"] for x in s.values())
    assert s["Em pausa"]["recencia_media_dias"] == max(x["recencia_media_dias"] for x in s.values())
    assert s["Em pausa"]["recencia_media_dias"] >= CFG["metricas"]["cliente_ativo_semanas"] * 7
    ordem = [x["valor_medio_usd"] for x in r["segmentos"]]
    assert ordem == sorted(ordem, reverse=True)


def test_estabilidade_e_silhueta_dentro_da_regra(r):
    cfg = CFG["analises"]["rfm"]
    e = r["estabilidade"]
    assert e["ari_sementes_min"] >= cfg["ari_minimo"] and e["ari_subamostras_min"] >= cfg["ari_minimo"]
    assert r["silhueta"] >= cfg["silhueta_minima"]
    assert min(s["pct_households"] for s in r["segmentos"]) >= cfg["tamanho_minimo_pct"]


def test_a_silhueta_pura_escolheria_k2_e_isso_esta_dito(r):
    por_k = {a["k"]: a for a in r["avaliacao_k"]}
    assert max(por_k, key=lambda k: por_k[k]["silhueta"]) == 2
    assert "silhueta pura escolheria K=2" in r["metodo_escolha_k"] and "K=2" in r["e_dai"]["limitacoes"]
    assert set(por_k) == set(CFG["analises"]["rfm"]["k_avaliados"])


def test_exclusoes_reconciliam_com_o_total_de_households(r):
    cur = banco.cursor()
    total = cur.execute("SELECT COUNT(*) FROM dim_household").fetchone()[0]
    na_janela = cur.execute("SELECT COUNT(*) FROM vw_metricas_cliente WHERE periodo = 'atual'").fetchone()[0]
    excluidos = sum(e["households"] for e in r["excluidos"])
    assert sum(s["households"] for s in r["segmentos"]) + excluidos == total == 2500
    assert r["excluidos"][0]["households"] == total - na_janela == 79


def test_aba_e_chat_dao_o_mesmo_numero(r):
    """O faturamento por segmento soma o mesmo valor do SQL do chat sobre as views (definição única)."""
    chat = executar_consulta("SELECT SUM(valor) AS v, COUNT(*) AS n FROM vw_metricas_cliente WHERE periodo = 'atual'")["linhas"][0]
    cesta = executar_consulta("SELECT SUM(faturamento) FROM vw_metricas_cesta WHERE periodo = 'atual'")["linhas"][0][0]
    assert sum(s["valor_total_usd"] for s in r["segmentos"]) == pytest.approx(chat[0], abs=1.0)
    assert chat[0] == pytest.approx(cesta, abs=1.0)
    assert sum(s["households"] for s in r["segmentos"]) == chat[1] == 2421


def test_perfil_e_concentracao_plausiveis(r):
    s = por_nome(r)
    assert 30 <= s["Fiéis"]["pct_households"] <= 40 and 65 <= s["Fiéis"]["pct_faturamento"] <= 75     # 35% dos clientes, 71% do faturamento
    assert s["Em pausa"]["pct_faturamento"] < 2
    for seg in s.values():
        assert 12 <= seg["desconto_medio_pct"] <= 20 and 15 <= seg["ticket_medio_usd"] <= 45


def test_e_dai_cita_os_numeros_do_resultado(r):
    s, e = por_nome(r), r["e_dai"]
    assert f"{round(s['Fiéis']['pct_households'])}%" in e["conclusao"] and f"{round(s['Fiéis']['pct_faturamento'])}%" in e["conclusao"]
    assert "79 households" in e["limitacoes"] and "US$" in e["impacto_estimado"]
    assert all(e[k].strip() for k in ("conclusao", "acao_recomendada", "impacto_estimado", "limitacoes"))


def test_coorte_tem_cinco_coortes_uteis_e_retencao_estavel():
    co = coorte_retencao(banco.cursor())
    assert len(co["coortes"]) == 5 and all(c["households"] >= CFG["analises"]["coorte"]["coorte_minima_households"] for c in co["coortes"])
    assert sum(c["households"] for c in co["coortes"]) + co["omitidas"]["households"] == 2500
    valores = [v for c in co["coortes"] for v in c["retencao_pct"].values()]
    assert valores and all(60 <= v <= 95 for v in valores)
    assert "painel em formação" in co["limitacao"]
