"""App Streamlit (AppTest, em processo): chat como primeira aba, tokens na sidebar, SQL num expander,
carga com mensagens claras. O modelo é roteirizado e a carga é substituída por uma base já construída."""

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import agente, carga
from src.config import CFG
from src.etl import ErroCarga
from src.nucleo import banco
from tests.fakes import ModeloRoteirizado, chamada, texto
from tests.test_carga import upload_csv

APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
SQL = "SELECT COUNT(*) AS n FROM fato_transacoes"


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    resultado = carga.carregar(upload=upload_csv(), pasta_bancos=tmp_path_factory.mktemp("bancos"))
    yield resultado
    banco.fechar_todas()
    banco.definir_banco(None)


@pytest.fixture
def app(base, monkeypatch):
    """App com a base de teste carregada na abertura e um modelo roteirizado no lugar do Groq."""
    monkeypatch.setattr(carga, "carregar", lambda **kw: base)
    monkeypatch.setattr(agente, "criar_modelo",
                        lambda api_key, modelo=None: ModeloRoteirizado(
                            roteiro=[chamada(SQL), texto("Há 4 linhas de venda na base.")], vistas=[]))
    monkeypatch.setattr(agente, "CAMINHO_USO", base.caminho_banco.parent / "uso_chat.jsonl")
    return AppTest.from_file(APP, default_timeout=60)


def com_chave(at):
    at.sidebar.text_input[0].set_value("gsk_chave_de_teste").run()
    return at


def textos_visiveis(at) -> str:
    partes = [e.value for tipo in ("markdown", "caption", "title", "subheader", "header", "info", "warning", "error")
              for e in getattr(at, tipo)]
    partes += [t.label for t in at.tabs] + [b.label for b in at.button] + [m.label for m in at.metric]
    return "\n".join(str(p) for p in partes)


def test_chat_e_a_primeira_aba(app):
    at = app.run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Chat", "Segmentos (RFM)", "Valor do cliente (CLV)", "Risco de pausa (churn)", "Desconto por segmento", "Dados e qualidade"]
    assert len(at.chat_input) == 1


def test_barra_lateral_tem_chave_modelo_e_contador_de_tokens(app):
    at = app.run()
    from streamlit.proto.TextInput_pb2 import TextInput as CampoDeTexto
    campo = at.sidebar.text_input[0]
    assert campo.label == "Chave do Groq" and campo.proto.type == CampoDeTexto.PASSWORD   # mascarada
    assert at.sidebar.selectbox[0].value == CFG["agente"]["modelo"]
    assert {m.label: m.value for m in at.sidebar.metric} == {"Última resposta": "0", "Sessão": "0"}


def test_exemplos_de_pergunta_aparecem_antes_da_primeira_pergunta(app):
    at = app.run()
    exemplos = [b.label for b in at.button if b.key and b.key.startswith("exemplo_")]
    assert len(exemplos) == 4 and any("loja 367" in e for e in exemplos)


def test_sem_chave_pede_a_chave_e_nao_chama_o_modelo(app):
    at = app.run()
    at.chat_input[0].set_value("qual o faturamento?").run()
    assert any("chave do Groq" in i.value for i in at.info)
    assert len(at.chat_message) == 0


def test_pergunta_responde_mostra_sql_e_conta_tokens(app):
    at = com_chave(app.run())
    at.chat_input[0].set_value("quantas linhas de venda existem?").run()
    assert not at.exception
    papeis = [m.name for m in at.chat_message]
    assert papeis == ["user", "assistant"]
    assert any("Há 4 linhas de venda na base." in m.value for m in at.chat_message[1].markdown)
    assert [e.label for e in at.expander if e.label == "Consulta SQL usada"] == ["Consulta SQL usada"]
    assert at.code[0].value == SQL and at.code[0].language == "sql"
    tokens = {m.label: m.value for m in at.sidebar.metric}
    assert tokens == {"Última resposta": "220", "Sessão": "220"}   # 2 chamadas ao modelo x 110 tokens
    assert any("2 chamadas ao modelo" in c.value for c in at.sidebar.caption)


def test_exemplo_clicado_vira_pergunta(app):
    at = com_chave(app.run())
    at.button(key="exemplo_1").click().run()
    assert [m.name for m in at.chat_message] == ["user", "assistant"]
    assert "loja 367" in at.chat_message[0].markdown[0].value


def test_resultado_da_consulta_aparece_no_expander(app):
    at = com_chave(app.run())
    at.chat_input[0].set_value("quantas linhas?").run()
    assert at.dataframe[0].value.iloc[0, 0] == 4


def test_historico_e_zerado_quando_a_base_muda(app, base, monkeypatch):
    at = com_chave(app.run())
    at.chat_input[0].set_value("quantas linhas?").run()
    assert len(at.chat_message) == 2
    from dataclasses import replace
    monkeypatch.setattr(carga, "carregar", lambda **kw: replace(base, versao_base="outraversao"))
    at.session_state.carga = None
    at.run()
    assert len(at.chat_message) == 0


def test_aba_de_dados_mostra_resumo_avisos_e_relatorio(app):
    at = app.run()
    rotulos = {m.label for m in at.metric}
    assert {"Período dos dados", "Linhas de venda", "Lojas", "Households"} <= rotulos
    assert any("ficam vazias" in w.value for w in at.warning)
    assert "Relatório de qualidade dos dados" in [e.label for e in at.expander]
    assert any("Reconciliação com o bruto:** OK" in m.value for m in at.markdown)


def test_sem_dados_mostra_a_tela_de_carga_com_instrucao(app, monkeypatch):
    def sem_dados(**kw):
        raise ErroCarga("Nenhum dado encontrado. Arraste os arquivos exportados do BI.")
    monkeypatch.setattr(carga, "carregar", sem_dados)
    at = app.run()
    assert not at.exception and not at.error
    assert any("Comece carregando os dados" in s.value for s in at.subheader)
    assert len(at.chat_input) == 0
    assert any("transaction_data" in m.value and "product" in m.value for m in at.markdown)
    assert any("Nenhum dado carregado ainda" in i.value for i in at.info)


def test_erro_de_carga_aparece_com_a_mensagem_clara(app, monkeypatch):
    def coluna_faltando(**kw):
        raise ErroCarga("No arquivo 'transaction_data.csv' faltam as colunas: SALES_VALUE.")
    monkeypatch.setattr(carga, "carregar", coluna_faltando)
    at = app.run()
    assert any("SALES_VALUE" in e.value and "transaction_data.csv" in e.value for e in at.error)


def test_falha_inesperada_na_carga_nao_vaza_detalhes(app, monkeypatch):
    def quebra(**kw):
        raise RuntimeError("caminho C:\\segredo\\interno")
    monkeypatch.setattr(carga, "carregar", quebra)
    at = app.run()
    assert any("RuntimeError" in e.value and "segredo" not in e.value for e in at.error)


def test_app_nao_menciona_versao_anterior_nem_saida_de_emprego(app):
    at = com_chave(app.run())
    at.chat_input[0].set_value("quantas linhas?").run()
    tudo = textos_visiveis(at).lower()
    for proibido in ("versão anterior", "versao anterior", "one up", "saí do", "saida de emprego", "emprego", "p&g", "não consegui aplicar"):
        assert proibido not in tudo, proibido


def test_chave_nunca_aparece_na_tela(app):
    at = com_chave(app.run())
    at.chat_input[0].set_value("quantas linhas?").run()
    assert "gsk_chave_de_teste" not in textos_visiveis(at)
    assert re.search(r"gsk_", str(at.session_state.mensagens)) is None
