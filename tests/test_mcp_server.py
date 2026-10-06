"""Servidor MCP: sobe como subprocesso (stdio, como o Claude Desktop e o app fazem) e confere pelo protocolo que ele só
embrulha o núcleo: as seis ferramentas, o mesmo resultado da função direta, o mesmo bloqueio, o log e o banco só leitura."""

import asyncio
import inspect
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src import mcp_server
from src.config import CFG, RAIZ
from src.nucleo import banco, cache, log
from src.nucleo.churn import prever_churn
from src.nucleo.clv import calcular_clv
from src.nucleo.consulta import executar_consulta
from src.nucleo.descrever import descrever_dados
from src.nucleo.rfm import segmentar_clientes
from src.nucleo.teste_desconto import testar_desconto_entre_segmentos
from tests import sintetico_clv as scv

REAL = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not REAL.exists(), reason="rode `python -m src.etl`")
NOMES = ["descrever_dados", "executar_consulta", "segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos"]
DIRETAS = {"descrever_dados": descrever_dados, "executar_consulta": executar_consulta, "segmentar_clientes": segmentar_clientes,
           "calcular_clv": calcular_clv, "prever_churn": prever_churn, "testar_desconto_entre_segmentos": testar_desconto_entre_segmentos}


async def _sessao(caminho_banco, caminho_log, chamadas):
    params = StdioServerParameters(command=sys.executable, args=["-m", "src.mcp_server"], cwd=str(RAIZ),
                                   env={**os.environ, "ASSISTENTE_BANCO": str(caminho_banco), "ASSISTENTE_LOG": str(caminho_log), "PYTHONPATH": str(RAIZ)})
    async with stdio_client(params) as (leitura, escrita):
        async with ClientSession(leitura, escrita) as s:
            await s.initialize()
            ferramentas = (await s.list_tools()).tools
            resultados = []
            for nome, args in chamadas:
                r = await s.call_tool(nome, args)
                resultados.append((nome, r.isError, r.content[0].text, r.structuredContent))
            return ferramentas, resultados


def rodar(caminho_banco, caminho_log, chamadas):
    return asyncio.run(asyncio.wait_for(_sessao(caminho_banco, caminho_log, chamadas), timeout=300))


# --- base sintética: as quatro análises e a consulta, comparadas com a função direta ----------------------------------

CHAMADAS_SINTETICAS = [("executar_consulta", {"sql": "SELECT COUNT(*) AS n FROM vw_cliente_semana"}), ("segmentar_clientes", {}), ("calcular_clv", {}),
                       ("prever_churn", {}), ("testar_desconto_entre_segmentos", {}), ("calcular_clv", {"segmento": "Fiéis"})]


@pytest.fixture(scope="module")
def sintetico(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("mcp")
    caminho, _, _ = scv.criar_banco(pasta / "s.duckdb")
    ferramentas, resultados = rodar(caminho, pasta / "chamadas.jsonl", CHAMADAS_SINTETICAS)
    anterior = (banco._ativo, log.CAMINHO)
    banco.definir_banco(caminho)
    log.CAMINHO = pasta / "direto.jsonl"       # as chamadas diretas não poluem o log do servidor
    cache.limpar()
    yield {"ferramentas": ferramentas, "resultados": resultados, "pasta": pasta}
    banco.fechar_todas()
    banco.definir_banco(anterior[0])
    log.CAMINHO = anterior[1]
    cache.limpar()


def test_lista_as_seis_ferramentas_da_spec_e_nenhuma_a_mais(sintetico):
    assert sorted(t.name for t in sintetico["ferramentas"]) == sorted(NOMES)


def test_descricao_e_parametros_vem_do_nucleo(sintetico):
    for t in sintetico["ferramentas"]:
        funcao = DIRETAS[t.name]
        assert t.description.strip() == inspect.getdoc(funcao).strip(), t.name
        esperados = list(inspect.signature(funcao).parameters)
        assert list(t.inputSchema.get("properties", {})) == esperados, t.name
    consulta = next(t for t in sintetico["ferramentas"] if t.name == "executar_consulta")
    assert consulta.inputSchema["required"] == ["sql"]


def test_resultado_pelo_mcp_e_identico_ao_da_funcao_direta(sintetico):
    for (nome, args), (nome_r, erro, texto, _) in zip(CHAMADAS_SINTETICAS, sintetico["resultados"]):
        assert nome == nome_r and not erro
        direto = json.loads(json.dumps(DIRETAS[nome](**args), ensure_ascii=False, default=str))
        pelo_mcp = json.loads(texto)
        if nome == "executar_consulta":
            direto.pop("tempo_ms", None), pelo_mcp.pop("tempo_ms", None)
        assert pelo_mcp == direto, nome


def test_retorno_e_json_compacto_sem_indentacao(sintetico):
    for _, _, texto, _ in sintetico["resultados"]:
        assert json.dumps(json.loads(texto), ensure_ascii=False, separators=(",", ":")) == texto


def test_todo_retorno_tem_rastreabilidade(sintetico):
    for nome, _, texto, _ in sintetico["resultados"]:
        r = json.loads(texto)
        assert r["versao_base"] == "sintetica_clv" and "semanas" in json.dumps(r["janela"]), nome


def test_o_servidor_grava_uma_linha_de_log_por_chamada(sintetico):
    linhas = [json.loads(l) for l in (sintetico["pasta"] / "chamadas.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [l["ferramenta"] for l in linhas] == [n for n, _ in CHAMADAS_SINTETICAS]
    assert all(l["erro"] is None and l["tamanho_bytes"] > 0 and l["tempo_ms"] >= 0 for l in linhas)
    assert linhas[0]["parametros"]["sql"].startswith("SELECT COUNT")


def test_o_servidor_e_so_um_embrulho_sem_logica_propria():
    codigo = inspect.getsource(mcp_server)
    assert set(mcp_server.FERRAMENTAS) == set(NOMES)
    assert all(mcp_server.FERRAMENTAS[n] is DIRETAS[n] for n in NOMES)      # exatamente as funções do núcleo
    for proibido in ("import duckdb", "import pandas", "sklearn", "scipy", "execute("):
        assert proibido not in codigo, proibido


# --- base real: guard-rails, banco só leitura e descrever_dados pelo protocolo ------------------------------------------

CHAMADAS_REAIS = [("executar_consulta", {"sql": "SELECT COUNT(*) AS n FROM dim_household"}), ("descrever_dados", {}),
                  ("executar_consulta", {"sql": "DROP TABLE dim_household"}), ("executar_consulta", {"sql": "SELECT 1; SELECT 2"}),
                  ("executar_consulta", {"sql": "PRAGMA version"}), ("executar_consulta", {"sql": "SELECT * FROM read_csv('data/raw/product.csv')"}),
                  ("executar_consulta", {"sql": "SELECT * FROM raw_transaction_data"}), ("executar_consulta", {"sql": "SELECT household_key FROM dim_household", "limite": 5000}),
                  ("segmentar_clientes", {"n_clusters": 99})]


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("mcp_real")
    _, resultados = rodar(REAL, pasta / "chamadas.jsonl", CHAMADAS_REAIS)
    return {"resultados": [(n, e, json.loads(t)) for n, e, t, _ in resultados], "pasta": pasta}


@precisa_do_banco
def test_real_consulta_e_descricao_pelo_protocolo(real):
    (_, e1, c), (_, e2, d) = real["resultados"][0], real["resultados"][1]
    assert not e1 and c["linhas"] == [[2500]] and c["janela"]["atual"]["semanas"] == [76, 101]
    assert not e2 and {"views", "metricas", "limitacoes", "versao_base"} <= d.keys() and "linhas" not in d


@precisa_do_banco
@pytest.mark.parametrize("indice,trecho", [(2, "leitura"), (3, "uma instrução"), (4, "leitura"), (5, "não"), (6, "não")])
def test_real_guard_rails_bloqueiam_pelo_mcp_com_erro_legivel(real, indice, trecho):
    _, erro_protocolo, r = real["resultados"][indice]
    assert not erro_protocolo                      # o bloqueio é dado ({erro, sugestao}), não falha de transporte
    assert r["erro"] and r["sugestao"] and "linhas" not in r and "Traceback" not in json.dumps(r)


@precisa_do_banco
def test_real_limite_de_linhas_e_aplicado_no_codigo(real):
    r = real["resultados"][7][2]
    assert len(r["linhas"]) <= CFG["consulta"]["limite_maximo"] and r["truncado"] is True


@precisa_do_banco
def test_real_parametro_invalido_de_ferramenta_de_analise_devolve_erro_legivel(real):
    r = real["resultados"][8][2]
    assert "n_clusters" in r["erro"] and r["sugestao"]


@precisa_do_banco
def test_real_tabelas_do_banco_continuam_intactas_depois_das_tentativas_de_escrita(real):
    banco.definir_banco(REAL)
    try:
        assert banco.cursor().execute("SELECT COUNT(*) FROM dim_household").fetchone()[0] == 2500
    finally:
        banco.fechar_todas()
