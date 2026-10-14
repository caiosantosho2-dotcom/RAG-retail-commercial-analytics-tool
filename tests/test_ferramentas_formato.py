"""Formato de cada ferramenta conforme docs/spec_ferramentas_mcp.md (seções 2 e 3): campos de saída, bloco e_dai, rastreabilidade,
tamanho, erro legível, log por chamada e resultado repetível. Roda sobre a base real (as funções do núcleo, sem MCP; o MCP
repete a comparação em tests/test_mcp_server.py)."""

import json
import re

import pytest

from src.config import CFG, RAIZ
from src.nucleo import banco, cache, log
from src.nucleo.churn import prever_churn
from src.nucleo.clv import calcular_clv
from src.nucleo.consulta import executar_consulta
from src.nucleo.descrever import descrever_dados
from src.nucleo.rfm import segmentar_clientes
from src.nucleo.teste_desconto import testar_desconto_entre_segmentos

BANCO = RAIZ / CFG["banco"]["arquivo"]
pytestmark = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")

# Saída de cada ferramenta, como a spec define (nomes do código onde a spec descreve em palavras).
SPEC = {
    "descrever_dados": {"views", "metricas", "janela_atual", "janela_ano_anterior", "limitacoes", "versao_base"},
    "executar_consulta": {"colunas", "linhas", "total_linhas", "truncado", "sql_executado", "versao_base"},
    "segmentar_clientes": {"k_usado", "metodo_escolha_k", "silhueta", "segmentos", "estabilidade", "excluidos", "e_dai", "versao_base"},
    "calcular_clv": {"segmentos", "premissas", "e_dai", "versao_base"},
    "prever_churn": {"definicao_churn", "periodo_treino", "periodo_teste", "auc_modelo", "auc_baseline", "precisao_recall_classe_churn",
                     "matriz_confusao", "principais_fatores", "risco_por_segmento", "e_dai", "versao_base"},
    "testar_desconto_entre_segmentos": {"normalidade_por_grupo", "kruskal_wallis", "post_hoc", "ic_diferencas", "e_dai", "versao_base"},
}
ANALISES = ["segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos"]
TAMANHO_MAXIMO = {"descrever_dados": 8_000, "executar_consulta": CFG["consulta"]["max_bytes_retorno"], "segmentar_clientes": 16_000,
                  "calcular_clv": 16_000, "prever_churn": 16_000, "testar_desconto_entre_segmentos": 16_000}


@pytest.fixture(scope="module")
def retornos(tmp_path_factory):
    anterior = (banco._ativo, log.CAMINHO)
    pasta = tmp_path_factory.mktemp("formato")
    log.CAMINHO = pasta / "chamadas.jsonl"
    banco.definir_banco(BANCO)
    cache.limpar()
    r = {"descrever_dados": descrever_dados(), "executar_consulta": executar_consulta("SELECT STORE_ID FROM dim_loja ORDER BY 1"),
         "segmentar_clientes": segmentar_clientes(), "calcular_clv": calcular_clv(), "prever_churn": prever_churn(),
         "testar_desconto_entre_segmentos": testar_desconto_entre_segmentos()}
    # chamadas com parâmetro inválido: o erro também é registrado e tem o formato da spec
    erros = {"segmentar_clientes": segmentar_clientes(n_clusters=1), "calcular_clv": calcular_clv(segmento="Segmento Que Nao Existe"),
             "prever_churn": prever_churn(segmento="Segmento Que Nao Existe"), "executar_consulta": executar_consulta("DROP TABLE dim_loja")}
    linhas_do_log = [json.loads(l) for l in (pasta / "chamadas.jsonl").read_text(encoding="utf-8").splitlines()]   # só as chamadas acima
    yield {"ok": r, "erros": erros, "log": linhas_do_log}
    banco.fechar_todas()
    banco.definir_banco(anterior[0])
    log.CAMINHO = anterior[1]
    cache.limpar()


@pytest.mark.parametrize("nome", list(SPEC))
def test_saida_tem_os_campos_da_spec(retornos, nome):
    r = retornos["ok"][nome]
    assert "erro" not in r, r.get("erro")
    assert SPEC[nome] <= r.keys(), SPEC[nome] - r.keys()


@pytest.mark.parametrize("nome", ANALISES)
def test_e_dai_tem_os_quatro_blocos_em_texto_sem_placeholder(retornos, nome):
    e = retornos["ok"][nome]["e_dai"]
    assert set(e) == {"conclusao", "evidencia", "acao_recomendada", "impacto_estimado", "limitacoes", "detalhes_tecnicos"}
    assert isinstance(e["detalhes_tecnicos"], list) and e["detalhes_tecnicos"]
    textos = [v for k, v in e.items() if k != "detalhes_tecnicos"] + e["detalhes_tecnicos"]
    assert all(isinstance(v, str) and len(v) > 20 and "{" not in v and "}" not in v and not re.search(r"\b(None|nan|NaN)\b", v) for v in textos)
    assert len(e["conclusao"].split()) <= 20 and e["conclusao"].endswith(".")


@pytest.mark.parametrize("nome", list(SPEC))
def test_todo_retorno_traz_versao_da_base_e_janela_usada(retornos, nome):
    r = retornos["ok"][nome]
    assert r["versao_base"] and len(r["versao_base"]) >= 8
    j = r.get("janela") or {"atual": r.get("janela_atual"), "base": r.get("janela_ano_anterior")}
    assert j["atual"]["semanas"] == [76, 101] and j["base"]["semanas"] == [24, 49]


def test_todos_os_retornos_da_mesma_chamada_citam_a_mesma_base(retornos):
    assert len({r["versao_base"] for r in retornos["ok"].values()}) == 1


@pytest.mark.parametrize("nome", list(SPEC))
def test_retorno_e_json_e_nao_passa_do_tamanho_maximo(retornos, nome):
    texto = json.dumps(retornos["ok"][nome], ensure_ascii=False, default=str)
    assert 0 < len(texto.encode()) <= TAMANHO_MAXIMO[nome], len(texto.encode())
    assert "NaN" not in texto and "Infinity" not in texto          # JSON válido para qualquer cliente MCP


def test_nenhuma_ferramenta_devolve_a_lista_de_households_nem_linhas_de_dados_alem_do_limite(retornos):
    for nome in ("segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos"):
        texto = json.dumps(retornos["ok"][nome], ensure_ascii=False, default=str)
        assert "household_key" not in texto and not isinstance(retornos["ok"][nome].get("linhas"), list), nome   # (churn tem "linhas": contagens)
    assert len(retornos["ok"]["executar_consulta"]["linhas"]) == CFG["consulta"]["limite_padrao"]


def test_campos_com_regra_da_spec_segmentos_nomeados_nome_unico_e_premissas_explicitas(retornos):
    seg = retornos["ok"]["segmentar_clientes"]["segmentos"]
    assert all(s["nome"].strip() for s in seg) and len({s["nome"] for s in seg}) == len(seg)
    clv = retornos["ok"]["calcular_clv"]
    assert all({"clv_medio", "ic_95", "n"} <= s.keys() and s["ic_95"][0] <= s["clv_medio"] <= s["ic_95"][1] for s in clv["segmentos"])
    assert {"horizonte_semanas", "margem", "metodo"} <= clv["premissas"].keys() and clv["premissas"]["margem_e_premissa"] is True
    churn = retornos["ok"]["prever_churn"]
    assert churn["auc_baseline"] > 0.5 and all({"coeficiente_padronizado", "leitura"} <= f.keys() for f in churn["principais_fatores"])
    d = retornos["ok"]["testar_desconto_entre_segmentos"]
    assert {"estatistica_H", "p_valor", "eta_quadrado_aprox"} <= d["kruskal_wallis"].keys()
    assert (d["post_hoc"] is not None) == d["kruskal_wallis"]["significativo_5pct"]                # post-hoc só se o geral for significativo
    assert "não efeito causal" in d["e_dai"]["limitacoes"]


@pytest.mark.parametrize("nome", ["segmentar_clientes", "calcular_clv", "prever_churn", "executar_consulta"])
def test_parametro_invalido_devolve_erro_legivel_sem_traceback(retornos, nome):
    r = retornos["erros"][nome]
    assert set(r) >= {"erro", "sugestao"} and r["erro"].strip() and r["sugestao"].strip()
    assert "Traceback" not in json.dumps(r) and "linhas" not in r and "versao_base" in r


@pytest.mark.parametrize("funcao", [descrever_dados, segmentar_clientes, calcular_clv, prever_churn, testar_desconto_entre_segmentos,
                                    lambda: executar_consulta("SELECT 1")])
def test_sem_base_toda_ferramenta_devolve_erro_legivel(tmp_path, funcao):
    anterior = banco._ativo
    banco.definir_banco(tmp_path / "nao_existe.duckdb")
    try:
        r = funcao()
    finally:
        banco.definir_banco(anterior)
    assert "Nenhuma base" in r["erro"] and r["sugestao"] and "Traceback" not in json.dumps(r)


def test_cada_chamada_gera_uma_linha_de_log_com_os_campos_da_spec(retornos):
    linhas = retornos["log"]
    assert [l["ferramenta"] for l in linhas] == (list(SPEC) + ["segmentar_clientes", "calcular_clv", "prever_churn", "executar_consulta"])
    for l in linhas:
        assert {"ts", "ferramenta", "parametros", "tempo_ms", "n_linhas", "tamanho_bytes", "erro"} <= l.keys() and l["tamanho_bytes"] > 0
    assert [l["erro"] is not None for l in linhas] == [False] * 6 + [True] * 4
    assert linhas[1]["n_linhas"] == CFG["consulta"]["limite_padrao"] and linhas[1]["parametros"]["sql"].startswith("SELECT STORE_ID")
    assert linhas[6]["parametros"] == {"n_clusters": 1}


@pytest.mark.parametrize("funcao", [segmentar_clientes, testar_desconto_entre_segmentos])
def test_resultado_e_repetivel_com_o_cache_limpo(retornos, funcao):
    primeiro = json.dumps(funcao(), ensure_ascii=False, default=str, sort_keys=True)
    cache.limpar()
    assert json.dumps(funcao(), ensure_ascii=False, default=str, sort_keys=True) == primeiro      # semente fixa


def test_descrever_dados_curta_cabe_em_poucos_tokens_e_detalhe_sob_pedido(retornos):
    tam = lambda r: len(json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode())
    assert tam(retornos["ok"]["descrever_dados"]) <= 8_000                       # ~2 mil tokens (antes ~21 KB)
    view = descrever_dados(detalhe="vw_vendas_item")
    assert view["tipo"] == "view" and tam(view) <= 4_000 and {"nome", "tipo"} <= view["colunas"][0].keys()
    assert any(c["nome"] == "desconto_total" for c in view["colunas"]) and view["versao_base"] == retornos["ok"]["descrever_dados"]["versao_base"]
    metrica = descrever_dados(detalhe="ticket_medio")
    assert metrica["tipo"] == "metrica" and metrica["definicao"] and metrica["formula"]
    assert tam(descrever_dados(detalhe="tudo")) <= 30_000
    assert "erro" in descrever_dados(detalhe="raw_transaction_data")                 # tabela interna não é descrita
