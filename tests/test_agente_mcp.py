"""Agente via servidor MCP: as seis ferramentas chegam ao agente pelo protocolo, cada sessão tem o seu processo e o seu banco,
o processo é encerrado (por pedido ou por ociosidade) e, se o servidor não subir, o erro é legível."""

import json
import time
import types

import pytest

from src import agente as ag
from src import cliente_mcp
from src.cliente_mcp import ErroServidorMCP, ServidorMCP, texto_do_conteudo
from src.config import CFG, RAIZ
from src.nucleo import banco, cache, log
from src.nucleo.descrever import catalogo_compacto, compactar_catalogo
from tests import sintetico_clv as scv
from tests.fakes import ModeloRoteirizado, chamada, texto

REAL = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not REAL.exists(), reason="rode `python -m src.etl`")
NOMES = {"descrever_dados", "executar_consulta", "segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos"}
SQL_SEMANAS = "SELECT MAX(WEEK_NO) AS ultima FROM vw_cliente_semana"


@pytest.fixture(scope="module")
def pasta(tmp_path_factory):
    return tmp_path_factory.mktemp("agente_mcp")


@pytest.fixture(scope="module")
def servidor(pasta):
    caminho, _, _ = scv.criar_banco(pasta / "a.duckdb")
    s = ServidorMCP(caminho_banco=caminho, caminho_log=pasta / "chamadas.jsonl")
    yield s
    s.fechar()


def montar(servidor, *roteiro):
    llm = ModeloRoteirizado(roteiro=list(roteiro), vistas=[])
    return ag.criar_agente(llm=llm, servidor=servidor, catalogo="catálogo de teste"), llm


def test_o_agente_recebe_as_seis_ferramentas_da_spec(servidor):
    assert {f.name for f in servidor.ferramentas} == NOMES and servidor.aberto


def test_descricoes_dizem_quando_usar_e_a_de_consulta_diz_quando_nao_usar(servidor):
    por_nome = {f.name: f.description for f in servidor.ferramentas}
    assert all("Use" in d for d in por_nome.values())
    assert "Não use" in por_nome["executar_consulta"] or "não use" in por_nome["executar_consulta"].lower()
    assert "Kruskal-Wallis" in por_nome["testar_desconto_entre_segmentos"] and "não efeito causal" in por_nome["testar_desconto_entre_segmentos"].replace(", ", " ")


def test_texto_do_conteudo_aceita_string_e_blocos():
    assert texto_do_conteudo("abc") == "abc"
    assert texto_do_conteudo([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}, {"type": "image", "data": "x"}]) == "ab"
    assert texto_do_conteudo(None) == ""


def test_consulta_pelo_agente_chega_ao_chat_com_sql_colunas_e_linhas(servidor):
    agente, _ = montar(servidor, chamada(SQL_SEMANAS), texto("A última semana é a 101."))
    r = ag.perguntar(agente, "Qual a última semana?", registrar=False)
    assert r.erro is None and r.ferramentas == ["executar_consulta"] and r.texto == "A última semana é a 101."
    c = r.consultas[0]
    assert c.sql == SQL_SEMANAS and c.colunas == ["ultima"] and c.linhas == [[101]] and c.erro is None


def test_consulta_bloqueada_pelo_guard_rail_aparece_com_o_erro(servidor):
    agente, _ = montar(servidor, chamada("DROP TABLE vw_cliente_semana"), texto("Não posso fazer isso."))
    r = ag.perguntar(agente, "Apague a tabela de vendas", registrar=False)
    assert r.consultas[0].erro and r.consultas[0].linhas == [] and r.erro is None
    # a tabela continua lá
    assert servidor.chamar("executar_consulta", sql="SELECT COUNT(*) AS n FROM vw_cliente_semana")["linhas"][0][0] > 0


def test_ferramenta_de_analise_pelo_agente_devolve_o_e_dai_ao_modelo(servidor):
    agente, llm = montar(servidor, chamada("", nome="testar_desconto_entre_segmentos"), texto("Os segmentos recebem desconto parecido."))
    r = ag.perguntar(agente, "Os segmentos recebem desconto diferente?", registrar=False)
    assert r.erro is None and r.ferramentas == ["testar_desconto_entre_segmentos"] and r.consultas == []
    retorno = next(m for m in llm.vistas[-1] if m.type == "tool")
    dado = json.loads(texto_do_conteudo(retorno.content))
    assert {"conclusao", "evidencia", "acao_recomendada", "impacto_estimado", "limitacoes", "detalhes_tecnicos"} == set(dado["e_dai"]) and "não efeito causal" in dado["e_dai"]["limitacoes"]


def test_argumento_invalido_volta_ao_modelo_como_erro_sem_derrubar_o_agente(servidor):
    agente, llm = montar(servidor, chamada(SQL_SEMANAS, limite="muitas"), texto("Reformulei."))
    r = ag.perguntar(agente, "Qual a última semana?", registrar=False)
    assert r.erro is None and r.texto == "Reformulei."
    retorno = next(m for m in llm.vistas[-1] if m.type == "tool")
    assert "limite" in texto_do_conteudo(retorno.content)


def test_o_servidor_grava_o_log_das_chamadas_do_agente(servidor, pasta):
    linhas = [json.loads(l) for l in (pasta / "chamadas.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {"executar_consulta", "testar_desconto_entre_segmentos"} <= {l["ferramenta"] for l in linhas}


def test_sessoes_com_bancos_diferentes_tem_processos_e_dados_separados(pasta):
    a, _, _ = scv.criar_banco(pasta / "x.duckdb")
    b, _, _ = scv.criar_banco(pasta / "y.duckdb", ultima_semana=90)
    s1, s2 = ServidorMCP(caminho_banco=a, caminho_log=pasta / "l1.jsonl"), ServidorMCP(caminho_banco=b, caminho_log=pasta / "l2.jsonl")
    try:
        for _ in range(2):      # intercalado: nenhum vaza para o outro
            assert s1.chamar("executar_consulta", sql=SQL_SEMANAS)["linhas"] == [[101]]
            assert s2.chamar("executar_consulta", sql=SQL_SEMANAS)["linhas"] == [[90]]
        assert s1.caminho_banco != s2.caminho_banco
    finally:
        s1.fechar(), s2.fechar()


def test_fechar_encerra_o_processo_e_pode_ser_repetido(pasta):
    caminho, _, _ = scv.criar_banco(pasta / "z.duckdb")
    s = ServidorMCP(caminho_banco=caminho, caminho_log=pasta / "lz.jsonl")
    assert s.aberto
    s.fechar()
    s.fechar()
    assert not s.aberto and not s._thread.is_alive() and s not in cliente_mcp._abertos
    with pytest.raises(ErroServidorMCP, match="encerrado"):
        s.chamar("executar_consulta", sql="SELECT 1")


def test_sessao_ociosa_libera_o_processo_sozinha(pasta):
    caminho, _, _ = scv.criar_banco(pasta / "o.duckdb")
    s = ServidorMCP(caminho_banco=caminho, caminho_log=pasta / "lo.jsonl", ocioso_s=1.5)
    try:
        assert s.chamar("executar_consulta", sql="SELECT 1 AS x")["linhas"] == [[1]]
        limite = time.monotonic() + 30
        while s.aberto and time.monotonic() < limite:
            time.sleep(0.25)
        assert not s.aberto, "o servidor deveria ter sido encerrado por ociosidade"
        with pytest.raises(ErroServidorMCP):
            s.chamar("executar_consulta", sql="SELECT 1")
    finally:
        s.fechar()
    assert not s._thread.is_alive()


def test_uso_mantem_a_sessao_viva(pasta):
    caminho, _, _ = scv.criar_banco(pasta / "v.duckdb")
    s = ServidorMCP(caminho_banco=caminho, caminho_log=pasta / "lv.jsonl", ocioso_s=3.0)
    try:
        for _ in range(5):
            time.sleep(1.0)
            assert s.chamar("executar_consulta", sql="SELECT 1 AS x")["linhas"] == [[1]]
        assert s.aberto
    finally:
        s.fechar()


def test_servidor_que_nao_sobe_vira_erro_legivel_e_nao_deixa_thread(monkeypatch):
    monkeypatch.setattr(cliente_mcp, "sys", types.SimpleNamespace(executable="C:/caminho/que/nao/existe/python.exe"))
    antes = {s for s in cliente_mcp._abertos}
    with pytest.raises(ErroServidorMCP, match="Não consegui iniciar"):
        ServidorMCP(timeout_inicio=30)
    assert {s for s in cliente_mcp._abertos} == antes


@precisa_do_banco
def test_catalogo_do_agente_pelo_mcp_e_igual_ao_da_chamada_direta():
    s = ServidorMCP(caminho_banco=REAL)
    try:
        pelo_mcp = compactar_catalogo(s.chamar("descrever_dados", detalhe="tudo"))
    finally:
        s.fechar()
    banco.definir_banco(REAL)
    try:
        assert pelo_mcp == catalogo_compacto() and "vw_yoy_resumo" in pelo_mcp
    finally:
        banco.fechar_todas()


def test_prompt_manda_usar_as_ferramentas_de_analise_e_nao_empurra_para_as_abas():
    p = ag.INSTRUCOES_SISTEMA
    for nome in ("segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos"):
        assert nome in p
    assert "e_dai" in p and "abas de análise" not in p and "pausa de 8 semanas" in p
