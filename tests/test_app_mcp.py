"""O chat do app usa o servidor MCP: um por sessão, aberto na primeira pergunta, fechado quando a base muda, e com
reserva (funções do núcleo direto) se o servidor não subir."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import agente, carga, cliente_mcp
from src.cliente_mcp import ErroServidorMCP
from src.nucleo import banco
from tests.fakes import ModeloRoteirizado, chamada, texto
from tests.test_carga import upload_csv

APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
SQL = "SELECT COUNT(*) AS n FROM fato_transacoes"


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    resultado = carga.carregar(upload=upload_csv(), pasta_bancos=tmp_path_factory.mktemp("bancos_mcp"))
    yield resultado
    banco.fechar_todas()
    banco.definir_banco(None)


def montar(base, monkeypatch, roteiro):
    monkeypatch.setattr(carga, "carregar", lambda **kw: base)
    monkeypatch.setattr(agente, "criar_modelo", lambda api_key, modelo=None: ModeloRoteirizado(roteiro=roteiro, vistas=[]))
    monkeypatch.setattr(agente, "CAMINHO_USO", base.caminho_banco.parent / "uso_chat.jsonl")
    return AppTest.from_file(APP, default_timeout=120)


def perguntar(at, pergunta="qual o faturamento?"):
    at.run()
    at.sidebar.text_input[0].set_value("gsk_chave_de_teste").run()
    at.chat_input[0].set_value(pergunta).run()
    return at


def legendas_da_barra(at) -> str:
    return " ".join(c.value for c in at.sidebar.caption)


def test_a_primeira_pergunta_abre_o_servidor_da_sessao_preso_ao_banco_dela(base, monkeypatch):
    at = perguntar(montar(base, monkeypatch, [chamada(SQL), texto("Há 4 linhas de venda na base.")]))
    assert not at.exception and at.session_state.modo_ferramentas == "mcp"
    servidor = at.session_state.servidor_mcp
    assert servidor is not None and servidor.aberto and servidor.caminho_banco == base.caminho_banco.resolve()
    assert "Ferramentas pelo servidor MCP." in legendas_da_barra(at)
    assert any("Há 4 linhas" in m.value for m in at.chat_message[-1].markdown)


def test_sem_pergunta_nenhum_processo_e_aberto(base, monkeypatch):
    at = montar(base, monkeypatch, [texto("oi")]).run()
    assert at.session_state.servidor_mcp is None and "servidor MCP" not in legendas_da_barra(at)


def test_a_segunda_pergunta_reaproveita_o_mesmo_servidor(base, monkeypatch):
    at = perguntar(montar(base, monkeypatch, [chamada(SQL), texto("Primeira."), chamada(SQL, id_="c2"), texto("Segunda.")]))
    primeiro = at.session_state.servidor_mcp
    at.chat_input[0].set_value("e agora?").run()
    assert at.session_state.servidor_mcp is primeiro and primeiro.aberto
    assert not at.exception


def test_pergunta_de_analise_pelo_chat_usa_a_ferramenta_do_servidor(base, monkeypatch):
    # a base de teste (4 linhas de venda) é pequena demais para o CLV: a ferramenta devolve erro legível e o agente responde
    at = perguntar(montar(base, monkeypatch, [chamada("", nome="calcular_clv"), texto("Não consegui calcular o CLV com esta base.")]), "quanto vale cada grupo?")
    assert not at.exception and any("Não consegui calcular" in m.value for m in at.chat_message[-1].markdown)
    assert at.session_state.mensagens[-1]["consultas"] == []        # não é consulta SQL: nada no expander de SQL


def test_se_o_servidor_nao_sobe_o_chat_segue_em_modo_direto_e_avisa(base, monkeypatch):
    def falha(**kw):
        raise ErroServidorMCP("Não consegui iniciar o servidor de ferramentas.")

    monkeypatch.setattr(cliente_mcp, "ServidorMCP", falha)
    at = montar(base, monkeypatch, [chamada(SQL), texto("Há 4 linhas de venda na base.")])
    monkeypatch.setattr("src.cliente_mcp.ServidorMCP", falha)
    perguntar(at)
    assert not at.exception and at.session_state.modo_ferramentas == "direto" and at.session_state.servidor_mcp is None
    assert "modo direto" in legendas_da_barra(at)
    assert any("Há 4 linhas" in m.value for m in at.chat_message[-1].markdown)
    assert at.session_state.mensagens[-1]["consultas"][0]["linhas"] == [[4]]


def test_recarregar_os_dados_fecha_o_servidor_da_sessao(base, monkeypatch):
    at = perguntar(montar(base, monkeypatch, [chamada(SQL), texto("ok")]))
    servidor = at.session_state.servidor_mcp
    assert servidor.aberto
    at.session_state.carga = None
    at.session_state.autocarga_tentada = False        # o app volta a carregar a base
    at.run()
    assert not servidor.aberto and at.session_state.servidor_mcp is None and not at.exception
