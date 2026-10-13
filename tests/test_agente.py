"""Agente: fluxo pergunta -> ferramenta -> resposta, glossário injetado, tokens, log e falhas legíveis.
Usa um modelo roteirizado (tests/fakes.py): sem rede e sem chave."""

import json

import groq
import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src import agente
from src.nucleo import banco, log
from src.token_counter import ContadorTokens
from tests import sintetico
from tests.fakes import ModeloRoteirizado, chamada, texto

SQL_TICKET = ("SELECT ticket_medio FROM vw_metricas_loja_semana "
              "WHERE STORE_ID = 1 AND periodo = 'atual' AND semana_alinhada = 9")


@pytest.fixture(scope="module", autouse=True)
def ambiente(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("agente")
    mp = pytest.MonkeyPatch()
    mp.setattr(log, "CAMINHO", pasta / "chamadas.jsonl")
    mp.setattr(agente, "CAMINHO_USO", pasta / "uso_chat.jsonl")
    banco.definir_banco(sintetico.criar_arquivo(pasta / "t.duckdb"))
    yield pasta
    banco.fechar_todas()
    banco.definir_banco(None)
    mp.undo()


def montar(*roteiro, **kw):
    llm = ModeloRoteirizado(roteiro=list(roteiro), vistas=[])
    return agente.criar_agente(llm=llm, **kw), llm


def erro_groq(classe, mensagem):
    resposta = httpx.Response(429 if classe is groq.RateLimitError else 400, request=httpx.Request("POST", "http://x"))
    if classe is groq.AuthenticationError:
        resposta = httpx.Response(401, request=httpx.Request("POST", "http://x"))
    return classe(mensagem, response=resposta, body=None)


def test_fluxo_basico_pergunta_ferramenta_resposta():
    ag, _ = montar(chamada(SQL_TICKET), texto("O ticket médio da loja 1 foi US$ 9,50."))
    r = agente.perguntar(ag, "qual o ticket médio da loja 1?", registrar=False)
    assert r.erro is None and r.texto == "O ticket médio da loja 1 foi US$ 9,50."
    assert r.ferramentas == ["executar_consulta"]
    assert len(r.consultas) == 1 and r.consultas[0].sql == SQL_TICKET
    assert r.consultas[0].linhas == [[9.5]] and r.consultas[0].colunas == ["ticket_medio"] and r.consultas[0].erro is None


def test_prompt_do_sistema_traz_regras_e_catalogo():
    ag, llm = montar(texto("oi"))
    agente.perguntar(ag, "oi", registrar=False)
    sistema = llm.vistas[0][0]
    assert isinstance(sistema, SystemMessage)
    for trecho in ("executar_consulta", "nunca responda só com SQL", "LIMIT 20", "ILIKE", "vw_yoy_resumo",
                   "amostra_pequena", "Janela atual: semanas 9-10"):
        assert trecho in sistema.content or trecho.lower() in sistema.content.lower(), trecho
    assert "{catalogo}" not in sistema.content


def test_glossario_e_injetado_na_pergunta_antes_do_modelo():
    ag, llm = montar(texto("ok"))
    agente.perguntar(ag, "qual o ticket médio da filial 1?", registrar=False)
    pergunta = [m for m in llm.vistas[0] if isinstance(m, HumanMessage)][-1].content
    assert pergunta.startswith("qual o ticket médio da filial 1?")
    assert "Definições de negócio relevantes:" in pergunta and "Ticket médio" in pergunta and "STORE_ID" in pergunta


def test_pergunta_sem_termo_do_glossario_vai_sem_bloco_extra():
    ag, llm = montar(texto("Bom dia!"))
    r = agente.perguntar(ag, "bom dia", registrar=False)
    assert [m for m in llm.vistas[0] if isinstance(m, HumanMessage)][-1].content == "bom dia"
    assert r.glossario == "" and r.consultas == []


def test_consulta_bloqueada_aparece_com_o_sql_e_o_erro():
    ag, _ = montar(chamada("DROP TABLE fato_transacoes"), texto("Não posso executar isso."))
    r = agente.perguntar(ag, "apague a tabela", registrar=False)
    assert r.consultas[0].sql == "DROP TABLE fato_transacoes"
    assert r.consultas[0].erro and r.consultas[0].linhas == []


def test_erro_de_sql_permite_nova_tentativa():
    ag, _ = montar(chamada("SELECT coluna_errada FROM vw_janela", "c1"), chamada(SQL_TICKET, "c2"), texto("US$ 9,50"))
    r = agente.perguntar(ag, "ticket da loja 1", registrar=False)
    assert [bool(c.erro) for c in r.consultas] == [True, False]
    assert r.ferramentas == ["executar_consulta", "executar_consulta"]


def test_descrever_dados_e_registrado_como_ferramenta_sem_virar_consulta():
    ag, _ = montar(chamada("", nome="descrever_dados"), texto("Tenho 11 views."))
    r = agente.perguntar(ag, "o que você sabe?", registrar=False)
    assert r.ferramentas == ["descrever_dados"] and r.consultas == []


def test_historico_leva_so_as_ultimas_6_mensagens_em_texto():
    historico = [("user" if i % 2 == 0 else "assistant", f"mensagem {i}") for i in range(10)]
    ag, llm = montar(texto("ok"))
    agente.perguntar(ag, "e a loja 2?", historico=historico, registrar=False)
    conteudo = [m.content for m in llm.vistas[0] if not isinstance(m, SystemMessage)]
    assert conteudo[:6] == [f"mensagem {i}" for i in range(4, 10)] and conteudo[6].startswith("e a loja 2?")


def test_tokens_por_resposta_e_da_sessao():
    contador = ContadorTokens()
    ag, _ = montar(chamada(SQL_TICKET), texto("ok"))
    r = agente.perguntar(ag, "ticket da loja 1", contador=contador, registrar=False)
    assert r.tokens["chamadas_llm"] == 2 and r.tokens["total_tokens"] == 220 and r.tokens["prompt_tokens"] == 200
    ag2, _ = montar(texto("de novo"))
    r2 = agente.perguntar(ag2, "oi", contador=contador, registrar=False)
    assert r2.tokens["total_tokens"] == 110                       # só esta resposta
    assert contador.resumo()["total_tokens"] == 330 and contador.resumo()["chamadas_llm"] == 3   # a sessão toda


def test_limite_de_uso_espera_e_tenta_de_novo(monkeypatch):
    dormiu = []
    monkeypatch.setattr(agente.time, "sleep", lambda s: dormiu.append(s))
    ag, _ = montar(erro_groq(groq.RateLimitError, "Rate limit reached. Please try again in 2.5s."),
                   chamada(SQL_TICKET), texto("US$ 9,50"))
    r = agente.perguntar(ag, "ticket da loja 1", registrar=False)
    assert r.erro is None and r.texto == "US$ 9,50" and dormiu == [3.5]


def test_limite_de_uso_longo_demais_vira_mensagem_legivel(monkeypatch):
    monkeypatch.setattr(agente.time, "sleep", lambda s: pytest.fail("não deveria esperar"))
    ag, _ = montar(erro_groq(groq.RateLimitError, "Rate limit reached. Please try again in 7m12.5s."))
    r = agente.perguntar(ag, "ticket", registrar=False)
    assert "limite de uso" in r.erro and "432 s" in r.erro and r.texto == r.erro


def test_chave_recusada_diz_para_conferir_a_chave():
    ag, _ = montar(erro_groq(groq.AuthenticationError, "Invalid API Key"))
    r = agente.perguntar(ag, "oi", registrar=False)
    assert "chave" in r.erro.lower() and "Invalid API Key" not in r.erro


def test_chamada_de_ferramenta_malformada_tenta_de_novo():
    ag, _ = montar(erro_groq(groq.BadRequestError, "tool_use_failed: Failed to call a function"),
                   chamada(SQL_TICKET), texto("US$ 9,50"))
    r = agente.perguntar(ag, "ticket da loja 1", registrar=False)
    assert r.erro is None and r.texto == "US$ 9,50"


def test_falha_inesperada_nunca_levanta():
    ag, _ = montar(RuntimeError("falha de rede com detalhes internos"))
    r = agente.perguntar(ag, "oi", registrar=False)
    assert r.erro and "RuntimeError" in r.erro and "detalhes internos" not in r.erro


def test_loop_de_ferramentas_e_cortado_pelo_limite_de_recursao():
    ag, _ = montar(*[chamada(SQL_TICKET, f"c{i}") for i in range(40)])
    r = agente.perguntar(ag, "ticket", registrar=False)
    assert r.erro and r.texto == r.erro


def test_uso_e_registrado_em_arquivo(ambiente):
    ag, _ = montar(chamada(SQL_TICKET), texto("ok"))
    agente.perguntar(ag, "ticket da loja 1?", contador=ContadorTokens())
    linhas = [json.loads(l) for l in (ambiente / "uso_chat.jsonl").read_text(encoding="utf-8").splitlines()]
    ultimo = linhas[-1]
    assert ultimo["pergunta"] == "ticket da loja 1?" and ultimo["sql"] == [SQL_TICKET]
    assert ultimo["ferramentas"] == ["executar_consulta"] and ultimo["erro"] is None
    assert {"ts", "tokens", "tempo_s"} <= ultimo.keys()


def test_ferramentas_dizem_quando_usar_e_quando_nao_usar():
    por_nome = {t.name: t for t in agente.ferramentas_do_nucleo()}
    assert set(por_nome) == {"executar_consulta", "descrever_dados"}
    def descricao(nome):
        return " ".join(por_nome[nome].description.split())   # o docstring quebra linha no meio das frases

    assert "Use para perguntas pontuais" in descricao("executar_consulta")
    assert "Não use para segmentação, CLV, churn" in descricao("executar_consulta")
    assert set(por_nome["executar_consulta"].args) == {"sql", "limite"}
    assert "Use antes de escrever uma consulta" in descricao("descrever_dados")


def test_o_modelo_so_e_criado_em_um_lugar():
    import inspect
    fonte = inspect.getsource(agente)
    assert fonte.count("ChatGroq(") == 1 and "def criar_modelo" in fonte


def test_sessoes_com_bancos_diferentes_nao_se_misturam(tmp_path):
    """Num app público cada visitante pode ter sua base: as ferramentas ficam presas ao banco da sessão,
    mesmo com chamadas concorrentes e com outro banco definido como padrão do processo."""
    import threading

    import duckdb

    a = sintetico.criar_arquivo(tmp_path / "a.duckdb")
    b = sintetico.criar_arquivo(tmp_path / "b.duckdb")
    c = duckdb.connect(str(b))
    c.execute("UPDATE meta SET valor = 'base_b' WHERE chave = 'versao_base'")
    c.close()
    ferramentas = {nome: {t.name: t for t in agente.ferramentas_do_nucleo(caminho)}
                   for nome, caminho in (("a", a), ("b", b))}
    vistos = {"a": set(), "b": set()}
    falhas = []

    def sessao(nome):
        try:
            for _ in range(6):
                saida = ferramentas[nome]["executar_consulta"].invoke({"sql": "SELECT 1 AS x"})
                vistos[nome].add(saida["versao_base"])
        except Exception as e:   # uma falha de thread não pode virar um conjunto vazio em silêncio
            falhas.append(repr(e))

    threads = [threading.Thread(target=sessao, args=(n,)) for n in ("a", "b") * 4]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert falhas == []
    assert vistos == {"a": {"teste123"}, "b": {"base_b"}}
    # o banco padrão do processo continua sendo o do módulo, intacto
    assert executar_consulta_padrao()["versao_base"] == "teste123"


def executar_consulta_padrao():
    from src.nucleo.consulta import executar_consulta
    return executar_consulta("SELECT 1 AS x")


def test_prompt_traz_as_regras_de_ids_faturamento_liquido_e_fieis():
    p = agente.INSTRUCOES_SISTEMA
    assert "sem separador de milhar" in p and "5569230" in p                       # IDs sem separador
    assert "já é líquido" in p and "nunca desconte de novo" in p                   # faturamento líquido
    assert "nome de um segmento RFM" in p and "nunca se chama \"Fiéis\"" in p       # Fiéis é do RFM
    assert "Não use SQL como calculadora" in p


def test_prompt_separa_total_geral_do_total_like_for_like():
    p = agente.INSTRUCOES_SISTEMA
    assert "cobrem só as lojas like-for-like" in p
    assert "nunca use esse total no lugar do total geral" in p


def test_prompt_manda_margem_esperada_para_calcular_clv_sem_perguntar():
    p = agente.INSTRUCOES_SISTEMA
    assert "só quando nenhuma ferramenta nem premissa do projeto cobre o caso" in p
    assert "chame calcular_clv" in p and "nunca peça a fórmula da margem" in p


def test_prompt_define_o_padrao_de_escrita_dos_valores_monetarios():
    p = agente.INSTRUCOES_SISTEMA
    assert "US$ 1.103.220" in p and "nenhum espaço dentro do número" in p
