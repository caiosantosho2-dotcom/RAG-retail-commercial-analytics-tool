"""Guard-rails do núcleo (spec, seção 2): cada regra tem um teste.

Roda sobre a base sintética (tests/sintetico.py), que contém também tabelas que o agente
não pode enxergar (raw_*, fato_ajustes, log_cargas, meta).
"""

import json

import duckdb
import pytest

from src.nucleo import banco, consulta, descrever, log
from src.nucleo.consulta import executar_consulta
from src.nucleo.descrever import descrever_dados
from tests import sintetico

TRES_VEZES = "SELECT a.BASKET_ID FROM vw_vendas_item a, vw_vendas_item b, vw_vendas_item c"   # 9 x 9 x 9 = 729 linhas


@pytest.fixture(scope="module", autouse=True)
def ambiente(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("nucleo")
    arquivo = sintetico.criar_arquivo(pasta / "teste.duckdb")
    mp = pytest.MonkeyPatch()
    mp.setattr(log, "CAMINHO", pasta / "chamadas.jsonl")
    banco.definir_banco(arquivo)
    yield pasta
    banco.fechar_todas()
    banco.definir_banco(None)
    mp.undo()


def linhas_do_log(pasta):
    caminho = pasta / "chamadas.jsonl"
    return [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines()] if caminho.exists() else []


def recusada(r):
    assert "erro" in r and "sugestao" in r and "linhas" not in r, r
    assert "Traceback" not in json.dumps(r)
    return r["erro"]


# --- Só leitura -----------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "DELETE FROM fato_transacoes", "DROP TABLE fato_transacoes", "UPDATE fato_transacoes SET QUANTITY = 0",
    "INSERT INTO fato_transacoes SELECT * FROM fato_transacoes", "CREATE TABLE x AS SELECT 1",
    "CREATE VIEW v AS SELECT 1", "ALTER TABLE fato_transacoes ADD COLUMN x INT", "ATTACH 'outro.db' AS o",
    "COPY (SELECT 1) TO 'saida.csv'", "COPY fato_transacoes TO 'saida.csv'", "PRAGMA version",
    "PRAGMA database_list", "SET enable_external_access = true", "CALL pragma_version()",
    "EXPLAIN SELECT 1", "INSTALL httpfs", "LOAD httpfs", "TRUNCATE fato_transacoes", "VACUUM", "CHECKPOINT",
    "EXPORT DATABASE 'pasta'", "DETACH DATABASE x", "USE memory",
])
def test_escrita_e_comandos_sao_bloqueados(sql):
    recusada(executar_consulta(sql))


@pytest.mark.parametrize("sql", [
    "SELECT 1 AS x", "WITH a AS (SELECT 1 AS x) SELECT * FROM a", "SELECT * FROM vw_janela",
    "SELECT 1;", "SELECT 1 -- ; DROP TABLE fato_transacoes", "select * from VW_JANELA",
    "SELECT * FROM (VALUES (1), (2)) t(a)", "FROM vw_janela SELECT semanas",
    "SELECT * FROM vw_janela a JOIN dim_loja b ON TRUE",
])
def test_select_e_with_passam(sql):
    r = executar_consulta(sql)
    assert "erro" not in r, r
    assert r["colunas"] and r["linhas"]


def test_ponto_e_virgula_dentro_de_string_nao_conta_como_instrucao():
    assert executar_consulta("SELECT ';' AS s")["linhas"] == [[";"]]


def test_motor_recusa_escrita_mesmo_sem_o_validador():
    cur = banco.cursor()
    for sql in ["CREATE TABLE t(a INT)", "DELETE FROM fato_transacoes", "DROP VIEW vw_janela"]:
        with pytest.raises(duckdb.Error):
            cur.execute(sql)


def test_motor_recusa_arquivos_e_configuracao_mesmo_sem_o_validador(tmp_path):
    arquivo = tmp_path / "x.csv"
    arquivo.write_text("a\n1\n", encoding="utf-8")
    cur = banco.cursor()
    for sql in [f"SELECT * FROM read_csv('{arquivo.as_posix()}')", f"COPY (SELECT 1) TO '{(tmp_path / 'y.csv').as_posix()}'",
                "SET enable_external_access = true", f"ATTACH '{(tmp_path / 'z.db').as_posix()}'"]:
        with pytest.raises(duckdb.Error):
            cur.execute(sql)
    assert not (tmp_path / "y.csv").exists()


# --- Uma instrução --------------------------------------------------------------------------

@pytest.mark.parametrize("sql", ["SELECT 1; DROP TABLE x", "SELECT 1; SELECT 2", "SELECT 1;; SELECT 2",
                                 "SELECT 1; -- c\nDELETE FROM fato_transacoes"])
def test_mais_de_uma_instrucao_e_bloqueada(sql):
    assert "uma instrução" in recusada(executar_consulta(sql))


# --- Fontes de dados ------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "SELECT * FROM raw_transaction_data", "SELECT * FROM fato_ajustes", "SELECT * FROM log_cargas",
    "SELECT * FROM meta", "SELECT * FROM main.raw_transaction_data", "SELECT * FROM information_schema.tables",
    "SELECT * FROM _mat_vw_yoy_categoria",
    "SELECT * FROM vw_janela WHERE semanas > (SELECT COUNT(*) FROM fato_ajustes)",
    "SELECT * FROM vw_janela JOIN meta ON TRUE",
    "SELECT 1 UNION SELECT household_key FROM raw_transaction_data",
    "WITH a AS (SELECT * FROM fato_ajustes) SELECT * FROM a",
    # CTE com nome de tabela proibida, definida em outro escopo, não libera a referência real:
    "SELECT * FROM (WITH raw_transaction_data AS (SELECT 1 a) SELECT * FROM raw_transaction_data), raw_transaction_data",
    "WITH raw_transaction_data AS (SELECT * FROM fato_ajustes) SELECT * FROM raw_transaction_data",
])
def test_tabelas_fora_da_allowlist_sao_bloqueadas(sql):
    assert "não está disponível" in recusada(executar_consulta(sql))


def test_cte_com_nome_de_tabela_proibida_e_inofensiva_quando_so_referencia_a_cte():
    r = executar_consulta("WITH raw_transaction_data AS (SELECT 1 AS a) SELECT * FROM raw_transaction_data")
    assert r["linhas"] == [[1]]


@pytest.mark.parametrize("sql", [
    "SELECT * FROM read_csv('x.csv')", "SELECT * FROM read_text('CLAUDE.md')", "SELECT * FROM glob('*')",
    "SELECT * FROM duckdb_tables()", "SELECT * FROM duckdb_settings()", "SELECT * FROM pragma_database_size()",
    "SELECT * FROM range(5)", "SELECT * FROM generate_series(1, 3)", "SELECT * FROM unnest([1, 2])",
    "SHOW TABLES", "DESCRIBE vw_janela", "SUMMARIZE vw_janela",
    "SELECT * FROM vw_janela PIVOT (COUNT(*) FOR semanas IN (2))",
])
def test_funcoes_de_tabela_e_comandos_de_catalogo_sao_bloqueados(sql):
    recusada(executar_consulta(sql))


# --- Limites --------------------------------------------------------------------------------

def test_limite_padrao_e_20():
    r = executar_consulta(TRES_VEZES)
    assert len(r["linhas"]) == 20 and r["limite_aplicado"] == 20
    assert r["truncado"] is True and r["total_linhas"] == 729


def test_limite_informado_e_respeitado():
    r = executar_consulta(TRES_VEZES, limite=5)
    assert len(r["linhas"]) == 5 and r["truncado"] is True and r["total_linhas"] == 729


def test_limite_nunca_passa_de_200():
    r = executar_consulta(TRES_VEZES, limite=100000)
    assert len(r["linhas"]) == 200 and r["limite_aplicado"] == 200 and r["truncado"] is True


def test_limite_minimo_e_1_e_texto_numerico_e_aceito():
    assert len(executar_consulta(TRES_VEZES, limite=0)["linhas"]) == 1
    assert len(executar_consulta(TRES_VEZES, limite="7")["linhas"]) == 7
    assert "inteiro" in recusada(executar_consulta(TRES_VEZES, limite="muitas"))


def test_resultado_pequeno_nao_e_truncado():
    r = executar_consulta("SELECT * FROM dim_loja ORDER BY STORE_ID")
    assert r["truncado"] is False and r["total_linhas"] == len(r["linhas"]) == 3


def test_ordem_do_sql_e_preservada_com_limite():
    r = executar_consulta("SELECT STORE_ID FROM dim_loja ORDER BY STORE_ID DESC", limite=2)
    assert r["linhas"] == [[3], [2]]


def test_retorno_nao_passa_do_limite_de_bytes(monkeypatch):
    monkeypatch.setattr(consulta, "MAX_BYTES", 900)
    r = executar_consulta(TRES_VEZES, limite=200)
    assert len(json.dumps(r, ensure_ascii=False).encode()) <= 900 or not r["linhas"]
    assert r["truncado"] is True and "aviso" in r


# --- Timeout --------------------------------------------------------------------------------

def test_consulta_longa_e_interrompida_com_erro_claro(monkeypatch):
    monkeypatch.setattr(consulta, "TIMEOUT_S", 0.5)
    dez = ", ".join(f"vw_vendas_item t{i}" for i in range(10))
    erro = recusada(executar_consulta(f"SELECT COUNT(*) FROM {dez}"))
    assert "tempo máximo" in erro
    assert executar_consulta("SELECT 1 AS ok")["linhas"] == [[1]]   # a conexão segue utilizável


# --- Erros legíveis -------------------------------------------------------------------------

@pytest.mark.parametrize("sql,trecho", [
    ("", "vazia"), ("   ", "vazia"), ("SELEC 1", "inválido"), ("SELECT coluna_que_nao_existe FROM vw_janela", "Erro ao executar"),
    ("SELECT * FROM vw_inexistente", "Erro ao executar"),   # casa com vw_*; falha na execução, com mensagem legível
])
def test_erros_tem_formato_erro_e_sugestao(sql, trecho):
    assert trecho in recusada(executar_consulta(sql))


def test_erro_nao_vaza_caminho_nem_stack_trace():
    r = executar_consulta("SELECT x FROM vw_janela")
    texto = json.dumps(r)
    assert "Traceback" not in texto and "site-packages" not in texto and 'File \\"' not in texto
    assert "\n" not in r["erro"] and len(r["erro"]) <= 400   # uma linha só, sem despejo do motor


def test_sem_base_carregada_devolve_erro_legivel(tmp_path):
    anterior = banco._ativo
    banco.definir_banco(tmp_path / "nao_existe.duckdb")
    try:
        assert "Nenhuma base" in recusada(executar_consulta("SELECT 1"))
        assert "Nenhuma base" in recusada(descrever_dados())
    finally:
        banco.definir_banco(anterior)


# --- Rastreabilidade ------------------------------------------------------------------------

def test_todo_retorno_traz_versao_da_base_e_janela():
    ok = executar_consulta("SELECT 1 AS x")
    bloqueada = executar_consulta("DROP TABLE x")
    invalida = executar_consulta("SELECT coluna FROM vw_janela")
    for r in (ok, bloqueada, invalida, descrever_dados()):
        assert r["versao_base"] == "teste123"
        assert r["janela"]["atual"]["semanas"] == [9, 10] and r["janela"]["base"]["semanas"] == [5, 6]


def test_numero_da_ferramenta_e_igual_ao_da_view():
    sql = ("SELECT ticket_medio FROM vw_metricas_loja_semana "
           "WHERE STORE_ID = 1 AND periodo = 'atual' AND semana_alinhada = 9")
    r = executar_consulta(sql)
    direto = banco.cursor().execute(sql).fetchone()[0]
    assert r["linhas"] == [[direto]] and direto == pytest.approx(9.5)
    assert r["sql_executado"] == sql


# --- Log ------------------------------------------------------------------------------------

def test_cada_chamada_gera_uma_linha_de_log_com_os_campos_da_spec(ambiente):
    antes = len(linhas_do_log(ambiente))
    executar_consulta("SELECT * FROM dim_loja")
    executar_consulta("DROP TABLE x")
    descrever_dados()
    novas = linhas_do_log(ambiente)[antes:]
    assert [l["ferramenta"] for l in novas] == ["executar_consulta", "executar_consulta", "descrever_dados"]
    for l in novas:
        assert {"ts", "ferramenta", "parametros", "tempo_ms", "n_linhas", "tamanho_bytes", "erro"} <= l.keys()
    assert novas[0]["n_linhas"] == 3 and novas[0]["erro"] is None and novas[0]["parametros"]["sql"] == "SELECT * FROM dim_loja"
    assert novas[1]["erro"] and novas[1]["n_linhas"] is None
    assert novas[0]["tamanho_bytes"] > 0 and novas[0]["tempo_ms"] >= 0


def test_falha_ao_gravar_log_nao_derruba_a_ferramenta(tmp_path, monkeypatch):
    arquivo_no_lugar_de_pasta = tmp_path / "bloqueio"
    arquivo_no_lugar_de_pasta.write_text("x", encoding="utf-8")
    monkeypatch.setattr(log, "CAMINHO", arquivo_no_lugar_de_pasta / "chamadas.jsonl")
    assert executar_consulta("SELECT 1 AS x")["linhas"] == [[1]]


# --- descrever_dados ------------------------------------------------------------------------

def test_descrever_dados_traz_lista_curta_sem_linhas_de_dados():
    d = descrever_dados()
    assert {"views", "tabelas", "metricas", "janela_atual", "janela_ano_anterior", "limitacoes",
            "versao_base", "como_ver_mais"} <= d.keys()
    assert "linhas" not in d and "erro" not in d
    nomes_views = {v["nome"] for v in d["views"]}
    assert {"vw_janela", "vw_vendas_item", "vw_yoy_resumo", "vw_metricas_loja_semana"} <= nomes_views
    assert all(v["descricao"] and "colunas" not in v for v in d["views"])             # colunas só com detalhe
    assert {"ticket_medio", "faturamento", "like_for_like"} <= {m["nome"] for m in d["metricas"]}
    assert all(set(m) == {"nome", "view_origem"} for m in d["metricas"])
    assert d["janela_atual"]["semanas"] == [9, 10]
    assert any("amostra_pequena" in l for l in d["limitacoes"])


def test_descrever_dados_nao_expoe_tabelas_proibidas():
    for d in (descrever_dados(), descrever_dados(detalhe="tudo")):
        todas = {t["nome"] for t in d["tabelas"]} | {v["nome"] for v in d["views"]}
        assert not any(n.startswith(("raw_", "_mat_")) or n in ("fato_ajustes", "log_cargas", "meta") for n in todas)
        assert {"dim_loja", "dim_produto", "fato_transacoes"} <= todas


def test_descrever_dados_tudo_traz_colunas_com_tipo_e_definicao_das_metricas():
    d = descrever_dados(detalhe="tudo")
    assert all(v["descricao"] and v["colunas"] and {"nome", "tipo"} <= v["colunas"][0].keys() for v in d["views"])
    assert all({"definicao", "formula", "view_origem"} <= m.keys() for m in d["metricas"])


def test_descrever_dados_detalhe_de_view_tabela_e_metrica():
    v = descrever_dados(detalhe="VW_JANELA")                       # sem diferenciar maiúsculas
    assert v["tipo"] == "view" and v["nome"] == "vw_janela" and v["colunas"] and {"nome", "tipo"} <= v["colunas"][0].keys()
    assert v["versao_base"] == "teste123" and v["janela"]["atual"]["semanas"] == [9, 10] and "linhas" not in v
    t = descrever_dados(detalhe="dim_loja")
    assert t["tipo"] == "tabela" and [c["nome"] for c in t["colunas"]] == ["STORE_ID"]
    m = descrever_dados(detalhe="Ticket Médio".replace(" ", "_").replace("é", "e"))
    assert m["tipo"] == "metrica" and m["nome"] == "ticket_medio" and m["definicao"] and m["formula"] and m["view_origem"]


@pytest.mark.parametrize("pedido", ["raw_transaction_data", "fato_ajustes", "meta", "nao_existe", "vw_janela; DROP TABLE dim_loja",
                                    "' OR 1=1 --", "../../.env", ""])
def test_descrever_dados_detalhe_desconhecido_ou_proibido_vira_erro_legivel_sem_expor_nada(pedido):
    r = descrever_dados(detalhe=pedido)
    assert r["erro"] and r["sugestao"].startswith("Opções: ") and "colunas" not in r and "Traceback" not in json.dumps(r)
    assert "raw_transaction_data" not in r["sugestao"] and "fato_ajustes" not in r["sugestao"] and r["versao_base"] == "teste123"
    assert banco.cursor().execute("SELECT COUNT(*) FROM dim_loja").fetchone()[0] == 3     # o texto nunca vira SQL


def test_lista_curta_e_bem_menor_que_o_catalogo_completo():
    curta, completa = len(json.dumps(descrever_dados())), len(json.dumps(descrever_dados(detalhe="tudo")))
    assert curta < 0.6 * completa


def test_catalogo_compacto_cabe_no_prompt():
    texto = descrever.catalogo_compacto()
    assert "vw_yoy_resumo" in texto and "Janela atual: semanas 9-10" in texto
    assert len(texto) < 9000   # ~2.500 tokens no máximo: o catálogo de verdade tem 11 views


@pytest.mark.parametrize("sql,nome", [
    ("SELECT * FROM segmentar_clientes()", "segmentar_clientes"),
    ("SELECT * FROM calcular_clv() LIMIT 20", "calcular_clv"),
    ("SELECT * FROM prever_churn()", "prever_churn"),
    ("SELECT * FROM testar_desconto_entre_segmentos()", "testar_desconto_entre_segmentos"),
])
def test_nome_de_ferramenta_como_funcao_sql_diz_para_chamar_a_ferramenta(sql, nome):
    r = executar_consulta(sql)
    recusada(r)
    assert f"'{nome}' é uma ferramenta, não uma função SQL" in r["erro"]
    assert f"Chame a ferramenta {nome} diretamente" in r["sugestao"] and "executar_consulta" in r["sugestao"]


def test_funcao_de_tabela_que_nao_e_ferramenta_mantem_a_sugestao_antiga():
    r = executar_consulta("SELECT * FROM range(5)")
    assert "não é uma ferramenta" not in r["erro"] and "ferramenta" not in r["erro"].split("(")[0]
    assert "vw_*" in r["sugestao"]


def test_consulta_sem_filtro_de_periodo_em_fonte_de_historico_traz_aviso_periodo():
    r = executar_consulta("SELECT SUM(faturamento) AS f FROM vw_vendas_item")
    assert "aviso_periodo" in r and "todo o histórico" in r["aviso_periodo"]
    assert "referência do projeto" in r["janela"]["regra"] and "não é o filtro da sua consulta" in r["janela"]["regra"]


@pytest.mark.parametrize("sql", [
    "SELECT SUM(faturamento) AS f FROM vw_vendas_item WHERE periodo = 'atual'",
    "SELECT periodo, SUM(faturamento) AS f FROM vw_vendas_item GROUP BY periodo",
    "SELECT faturamento_atual FROM vw_yoy_resumo",
    "SELECT COUNT(*) AS n FROM dim_produto",
])
def test_consulta_com_periodo_ou_fora_das_fontes_de_historico_nao_traz_aviso_periodo(sql):
    r = executar_consulta(sql)
    assert "erro" not in r and "aviso_periodo" not in r
