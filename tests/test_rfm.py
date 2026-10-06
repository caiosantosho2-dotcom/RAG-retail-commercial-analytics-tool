"""RFM + K-Means: funções puras, pipeline sobre clientes com segmentos plantados e formato da spec."""

import json

import duckdb
import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import adjusted_rand_score

from src.config import CFG
from src.nucleo import banco, cache, log, rfm
from src.nucleo.rfm import (avaliar_k, coorte_retencao, escolher_k, matriz, montar_e_dai, montar_perfil, nomear,
                           segmentar_clientes, segmentos_por_household, validar_nomes)
from tests import sintetico_clientes as sc

CFG_RFM = CFG["analises"]["rfm"]


def tabela(linhas):
    base = dict(silhueta=0.4, inercia=1.0, ari_sementes_min=0.97, ari_sementes_mediana=0.98, ari_subamostras_min=0.96,
                ari_subamostras_mediana=0.98, menor_segmento_pct=10.0, tamanhos=[1])
    return pd.DataFrame([{**base, **l} for l in linhas])


# --- regra de escolha de K -----------------------------------------------------------------------

def test_k2_nao_e_escolhido_mesmo_com_a_maior_silhueta():
    t = tabela([dict(k=2, silhueta=0.52), dict(k=3, silhueta=0.43), dict(k=4, silhueta=0.37)])
    k, metodo, cumprida = escolher_k(t, CFG_RFM)
    assert (k, cumprida) == (3, True) and "silhueta pura escolheria K=2" in metodo


def test_k_instavel_e_excluido():
    t = tabela([dict(k=3, silhueta=0.43, ari_sementes_min=0.88), dict(k=4, silhueta=0.37),
                dict(k=5, silhueta=0.32, ari_subamostras_min=0.59)])
    assert escolher_k(t, CFG_RFM)[0] == 4


def test_segmento_pequeno_demais_e_excluido():
    t = tabela([dict(k=5, silhueta=0.45, menor_segmento_pct=3.9), dict(k=4, silhueta=0.37, menor_segmento_pct=6.5)])
    assert escolher_k(t, CFG_RFM)[0] == 4


def test_silhueta_baixa_demais_e_excluida():
    t = tabela([dict(k=3, silhueta=0.20), dict(k=4, silhueta=0.26)])
    assert escolher_k(t, CFG_RFM)[0] == 4


def test_vence_a_maior_silhueta_entre_os_aprovados():
    t = tabela([dict(k=3, silhueta=0.33), dict(k=4, silhueta=0.41), dict(k=5, silhueta=0.36)])
    assert escolher_k(t, CFG_RFM)[0] == 4


def test_sem_nenhum_aprovado_usa_a_melhor_silhueta_e_avisa():
    t = tabela([dict(k=2, silhueta=0.5), dict(k=3, silhueta=0.30, ari_sementes_min=0.5),
                dict(k=4, silhueta=0.28, ari_sementes_min=0.5)])
    k, metodo, cumprida = escolher_k(t, CFG_RFM)
    assert k == 3 and cumprida is False and "Nenhum K atendeu" in metodo and "podem não ser estáveis" in metodo


# --- preparo e avaliação -----------------------------------------------------------------------------

def test_matriz_e_padronizada_e_a_cauda_longa_e_comprimida():
    df = sc.gerar_clientes()
    x = matriz(df)
    assert np.allclose(x.mean(axis=0), 0, atol=1e-9) and np.allclose(x.std(axis=0), 1, atol=1e-9)
    assert abs(pd.Series(x[:, 2]).skew()) < abs(df["valor"].skew())     # log1p reduz a assimetria do valor


def test_avaliar_k_recupera_quatro_grupos_plantados_e_e_reproduzivel():
    x = matriz(sc.gerar_clientes())
    a = avaliar_k(x, [2, 3, 4, 5, 6], semente=42, cfg=CFG_RFM)
    b = avaliar_k(x, [2, 3, 4, 5, 6], semente=42, cfg=CFG_RFM)
    pd.testing.assert_frame_equal(a, b)
    assert escolher_k(a, CFG_RFM)[0] == 4
    linha = a[a["k"] == 4].iloc[0]
    assert linha["ari_sementes_min"] >= 0.9 and linha["ari_subamostras_min"] >= 0.9 and linha["silhueta"] >= 0.25
    assert {"k", "silhueta", "inercia", "ari_sementes_min", "ari_subamostras_min", "menor_segmento_pct"} <= set(a.columns)


# --- nomes pelo perfil ---------------------------------------------------------------------------------

def perfil(linhas):
    return pd.DataFrame(linhas, columns=["recencia_media_dias", "valor_medio_usd"]).rename_axis("seg")


def test_nomes_vem_do_perfil_nao_da_ordem_dos_clusters():
    p = perfil([(10.6, 568), (108.5, 99), (3.2, 1780), (27.6, 128)])        # índices fora de ordem de propósito
    nomes = nomear(p, limite_inativo_dias=56)
    assert nomes == {2: "Fiéis", 0: "Regulares", 3: "Esporádicos", 1: "Inativos"}
    validar_nomes(nomes, 4)


def test_tres_segmentos_ativos_e_nenhum_inativo():
    nomes = nomear(perfil([(5, 1500), (12, 300), (30, 90)]), 56)
    assert sorted(nomes.values()) == ["Esporádicos", "Fiéis", "Regulares"]


def test_dois_inativos_ganham_nomes_diferentes():
    nomes = nomear(perfil([(70, 100), (120, 90), (4, 1500), (15, 400)]), 56)
    assert nomes[1] == "Inativos" and nomes[0] == "Inativos (2)" and len(set(nomes.values())) == 4


def test_muitos_segmentos_ativos_usam_nomes_de_nivel_sem_repetir():
    nomes = nomear(perfil([(3 + i, 2000 - 200 * i) for i in range(7)]), 56)
    validar_nomes(nomes, 7)
    assert nomes[0] == "Valor nível 1"


@pytest.mark.parametrize("nomes,k", [({0: "A", 1: "A"}, 2), ({0: "A", 1: " "}, 2), ({0: "A"}, 2)])
def test_nomes_invalidos_sao_recusados(nomes, k):
    with pytest.raises(ValueError):
        validar_nomes(nomes, k)


def test_desconto_do_segmento_e_ponderado_pelo_valor():
    df = pd.DataFrame({"recencia_dias": [1, 1], "frequencia": [1, 1], "valor": [100.0, 300.0], "ticket_medio": [1.0, 1.0],
                       "pct_desconto": [10.0, 20.0]})
    p = montar_perfil(df, np.array([0, 0]))
    assert p.loc[0, "desconto_medio_pct"] == pytest.approx(17.5)     # (10*100 + 20*300) / 400


# --- bloco "e daí?" --------------------------------------------------------------------------------------

def segmentos_exemplo():
    mk = lambda nome, n, pct_hh, v, pct_f: dict(nome=nome, households=n, pct_households=pct_hh, valor_medio_usd=v,
                                                valor_total_usd=n * v, pct_faturamento=pct_f)
    return [mk("Fiéis", 857, 35.4, 1780, 70.9), mk("Regulares", 980, 40.5, 568, 25.9),
            mk("Esporádicos", 426, 17.6, 128, 2.5), mk("Inativos", 158, 6.5, 99, 0.7)]


def test_e_dai_tem_os_quatro_blocos_com_numeros_e_sem_marcadores_soltos():
    e = montar_e_dai(segmentos_exemplo(), 4, 0.374, {"ari_sementes_min": 0.97, "ari_subamostras_min": 0.95}, True, 2, 79, 2500)
    assert set(e) == {"conclusao", "acao_recomendada", "impacto_estimado", "limitacoes"}
    assert "Fiéis são 35% dos households e fazem 71%" in e["conclusao"] and "0,95" in e["conclusao"]
    assert "Fiéis" in e["acao_recomendada"] and "Inativos" in e["impacto_estimado"] and "US$" in e["impacto_estimado"]
    assert "2.500 households" in e["limitacoes"] and "79 households" in e["limitacoes"] and "K=2" in e["limitacoes"]
    assert not any("{" in v or "}" in v for v in e.values())


def test_e_dai_avisa_quando_a_regra_de_k_nao_foi_cumprida():
    e = montar_e_dai(segmentos_exemplo(), 4, 0.30, {"ari_sementes_min": 0.5, "ari_subamostras_min": 0.5}, False, 4, 0, 2500)
    assert "regra de estabilidade não foi atendida" in e["conclusao"]


# --- pipeline sobre clientes com segmentos plantados ------------------------------------------------------

@pytest.fixture(scope="module")
def ambiente(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("rfm")
    mp = pytest.MonkeyPatch()
    mp.setattr(log, "CAMINHO", pasta / "chamadas.jsonl")
    extras = [dict(household_key=10_000, segmento_plantado="x", recencia_dias=5, frequencia=1, valor=0.0, ticket_medio=0.0,
                   pct_desconto=0.0, tem_demografia=False)]
    banco.definir_banco(sc.criar_banco(pasta / "a.duckdb", extras=extras))
    cache.limpar()
    yield pasta
    banco.fechar_todas()
    banco.definir_banco(None)
    cache.limpar()
    mp.undo()


def test_recupera_os_segmentos_plantados(ambiente):
    r = segmentar_clientes()
    assert "erro" not in r and r["k_usado"] == 4 and r["regra_k_cumprida"] is True
    atrib = segmentos_por_household(banco.cursor()).merge(sc.gerar_clientes()[["household_key", "segmento_plantado"]], on="household_key")
    assert adjusted_rand_score(atrib["segmento_plantado"], atrib["segmento"]) >= 0.9
    mapa = {"fieis": "Fiéis", "regulares": "Regulares", "esporadicos": "Esporádicos", "inativos": "Inativos"}
    certo = np.mean([mapa[p] == s for p, s in zip(atrib["segmento_plantado"], atrib["segmento"])])
    assert certo >= 0.95        # os nomes saíram do perfil e caíram nos grupos certos


def test_formato_da_spec_e_sem_lista_de_households(ambiente):
    r = segmentar_clientes()
    assert {"k_usado", "metodo_escolha_k", "silhueta", "segmentos", "estabilidade", "excluidos", "e_dai",
            "versao_base", "janela"} <= r.keys()
    assert {"nome", "households", "recencia_media_dias", "frequencia_media", "valor_medio_usd", "pct_faturamento"} <= r["segmentos"][0].keys()
    texto = json.dumps(r, ensure_ascii=False)                    # serializa em JSON
    assert len(texto.encode()) < 12_000 and "household_key" not in texto
    assert r["versao_base"] == "sintetica1" and r["janela"]["atual"]["semanas"] == [76, 101]
    assert {"ari_sementes_min", "ari_subamostras_min", "sementes", "subamostras"} <= r["estabilidade"].keys()


def test_segmentos_somam_100_por_cento_e_todos_tem_nome(ambiente):
    r = segmentar_clientes()
    assert sum(s["pct_faturamento"] for s in r["segmentos"]) == pytest.approx(100, abs=0.2)
    assert sum(s["pct_households"] for s in r["segmentos"]) == pytest.approx(100, abs=0.2)
    nomes = [s["nome"] for s in r["segmentos"]]
    assert all(n.strip() for n in nomes) and len(set(nomes)) == len(nomes) == r["k_usado"]
    assert nomes[0] == "Fiéis" and r["segmentos"][0]["valor_medio_usd"] == max(s["valor_medio_usd"] for s in r["segmentos"])


def test_exclusoes_sao_contadas_com_o_motivo(ambiente):
    r = segmentar_clientes()
    por_motivo = {e["motivo"].split(" ")[0] + e["motivo"].split(" ")[1]: e["households"] for e in r["excluidos"]}
    assert por_motivo == {"semcompra": 7, "valorlíquido": 1}
    assert sum(s["households"] for s in r["segmentos"]) == sum(p["n"] for p in sc.SEGMENTOS.values())


def test_k_informado_sobrepoe_a_regra(ambiente):
    r = segmentar_clientes(n_clusters=3)
    assert r["k_usado"] == 3 and "informado pelo usuário" in r["metodo_escolha_k"] and len(r["segmentos"]) == 3


@pytest.mark.parametrize("valor", [1, 9, 0, -2, "muitos", 2.5e9])
def test_k_invalido_devolve_erro_legivel(ambiente, valor):
    r = segmentar_clientes(n_clusters=valor)
    assert "erro" in r and "sugestao" in r and "segmentos" not in r


def test_resultado_e_cacheado_e_reproduzivel(ambiente, monkeypatch):
    primeiro = segmentar_clientes()
    chamadas = []
    original = rfm._calcular
    monkeypatch.setattr(rfm, "_calcular", lambda *a, **k: chamadas.append(1) or original(*a, **k))
    segundo = segmentar_clientes()
    assert chamadas == [] and segundo == primeiro                  # cache por versao_base
    cache.limpar()
    terceiro = segmentar_clientes()
    assert chamadas == [1]
    assert [(s["nome"], s["households"]) for s in terceiro["segmentos"]] == [(s["nome"], s["households"]) for s in primeiro["segmentos"]]


def test_ordem_das_linhas_no_banco_nao_muda_o_resultado(ambiente):
    """O SQL é ordenado por household_key: a mesma base em outra ordem física dá os mesmos segmentos."""
    embaralhado = sc.criar_banco(ambiente / "b.duckdb", embaralhar=True)
    banco.definir_banco(embaralhado)
    try:
        b = segmentar_clientes()
    finally:
        banco.definir_banco(ambiente / "a.duckdb")
    cache.limpar()
    a = segmentar_clientes()
    # base b não tem o household de valor 0, então compara os tamanhos dos 4 segmentos plantados
    assert [(s["nome"], s["households"]) for s in b["segmentos"]] == [(s["nome"], s["households"]) for s in a["segmentos"]]


def test_chamada_gera_linha_de_log(ambiente):
    segmentar_clientes()
    ultimo = json.loads((ambiente / "chamadas.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert ultimo["ferramenta"] == "segmentar_clientes" and ultimo["erro"] is None


def test_sem_base_devolve_erro_legivel(tmp_path):
    anterior = banco._ativo
    banco.definir_banco(tmp_path / "nao_existe.duckdb")
    try:
        assert "Nenhuma base" in segmentar_clientes()["erro"]
    finally:
        banco.definir_banco(anterior)


def test_base_pequena_demais_devolve_erro_sem_stack_trace(tmp_path):
    pequena = sc.gerar_clientes().head(6)
    anterior = banco._ativo
    banco.definir_banco(sc.criar_banco(tmp_path / "p.duckdb", clientes=pequena, sem_compra=0))
    try:
        r = segmentar_clientes()
        assert "erro" in r and "sugestao" in r and "Traceback" not in json.dumps(r)
    finally:
        banco.fechar_todas()
        banco.definir_banco(anterior)


# --- coorte ----------------------------------------------------------------------------------------------

def test_coorte_calcula_retencao_por_bloco_e_omite_coortes_pequenas(tmp_path):
    destino = sc.criar_banco(tmp_path / "c.duckdb")
    c = duckdb.connect(str(destino))
    c.execute("UPDATE vw_janela SET semana_fim_atual = 16")             # 4 blocos completos de 4 semanas (0..3)
    linhas = []
    for h in range(1, 61):                                              # coorte A: entra na semana 1 (60 households)
        sem = [1] + ([5] if h <= 30 else []) + ([9] if h <= 15 else []) + ([13] if h <= 6 else [])
        linhas += [(h, s) for s in sem]
    for h in range(101, 141):                                           # coorte B: entra na semana 5 (40 households)
        linhas += [(h, 5)] + ([(h, 9)] if h <= 120 else [])
    linhas += [(h, 9) for h in range(201, 206)]                         # coorte pequena demais (5 households, bloco 9-12)
    linhas += [(1, 15)]                                                 # semana 15 pertence ao bloco 3 (13-16), completo
    c.executemany("INSERT INTO vw_cliente_semana VALUES (?, ?, 1, 1.0, 1.0, 0.0, 1.0)", linhas)
    c.close()
    anterior = banco._ativo
    banco.definir_banco(destino)
    try:
        co = coorte_retencao(banco.cursor())
    finally:
        banco.fechar_todas()
        banco.definir_banco(anterior)
    por_nome = {x["coorte"]: x for x in co["coortes"]}
    assert list(por_nome) == ["Sem. 1–4", "Sem. 5–8"] and co["omitidas"]["households"] == 5
    a = por_nome["Sem. 1–4"]
    assert a["households"] == 60
    # lag 1 = semanas 5-8 (30 de 60), lag 2 = semanas 9-12 (15 de 60), lag 3 = semanas 13-16 (6 + household 1 na semana 15 já contado)
    assert a["retencao_pct"] == {1: 50.0, 2: 25.0, 3: 10.0}
    assert por_nome["Sem. 5–8"]["retencao_pct"] == {1: 50.0, 2: 0.0}      # 20 de 40 voltam em 9-12
    assert "painel em formação" in co["limitacao"]
