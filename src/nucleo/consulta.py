"""executar_consulta: SQL de leitura nas views do projeto, com os guard-rails da spec no código.

Camadas (nenhuma depende de texto de prompt):
  1. uma única instrução (contada pelo parser do DuckDB, então `;` dentro de string não conta);
  2. só consulta de leitura: a árvore da consulta (json_serialize_sql) só existe para SELECT/WITH,
     o que rejeita PRAGMA, SET, CALL, EXPLAIN, INSERT, DELETE, DROP, CREATE ...;
  3. fontes de dados permitidas: nada de funções de tabela (read_csv, glob, duckdb_tables ...),
     e só tabelas da allowlist, com escopo de CTE respeitado;
  4. o motor: conexão read_only, sem acesso a arquivos, configuração travada, teto de memória
     (ver banco.py);
  5. limite de linhas e de bytes aplicados no retorno, e timeout por interrupção.
Toda falha devolve {"erro", "sugestao"} sem stack trace.
"""

import datetime
import fnmatch
import json
import math
import re
import threading
from decimal import Decimal

import duckdb

from src.config import CFG
from src.nucleo import banco
from src.nucleo.log import registrar_chamada

LIMITE_PADRAO = CFG["consulta"]["limite_padrao"]
LIMITE_MAXIMO = CFG["consulta"]["limite_maximo"]
TIMEOUT_S = CFG["consulta"]["timeout_segundos"]
MAX_BYTES = CFG["consulta"]["max_bytes_retorno"]
TABELAS_PERMITIDAS = [p.lower() for p in CFG["consulta"]["tabelas_permitidas"]]
FONTES_PERMITIDAS = {"BASE_TABLE", "JOIN", "SUBQUERY", "EXPRESSION_LIST", "EMPTY"}


class ConsultaRecusada(Exception):
    """Consulta que o guard-rail não deixa executar; carrega a mensagem e a sugestão."""

    def __init__(self, erro: str, sugestao: str):
        super().__init__(erro)
        self.erro, self.sugestao = erro, sugestao


def _tabela_permitida(nome: str) -> bool:
    return any(fnmatch.fnmatchcase(nome.lower(), p) for p in TABELAS_PERMITIDAS)


def _analisar(arvore: dict) -> tuple[set, set]:
    """Devolve (tabelas referenciadas fora de CTE, tipos de fonte usados). O escopo de CTE é por nó."""
    tabelas, tipos = set(), set()

    def percorrer(no, escopo: frozenset):
        if isinstance(no, dict):
            cte = no.get("cte_map")
            if isinstance(cte, dict) and cte.get("map"):
                escopo = escopo | {item["key"].lower() for item in cte["map"]}
            if no.get("type") == "BASE_TABLE":
                catalogo, esquema, nome = no.get("catalog_name", ""), no.get("schema_name", ""), no.get("table_name", "")
                if not (catalogo == "" and esquema == "" and nome.lower() in escopo):
                    tabelas.add((catalogo, esquema, nome))
            # `from_table` é sempre uma fonte; `left`/`right` só são fontes em JOIN (em comparações
            # como `a > b` são expressões e não podem ser tratadas como fonte de dados).
            for chave in ("from_table",) + (("left", "right") if no.get("type") == "JOIN" else ()):
                sub = no.get(chave)
                if isinstance(sub, dict) and "type" in sub:
                    tipos.add(sub["type"])
            for valor in no.values():
                percorrer(valor, escopo)
        elif isinstance(no, list):
            for item in no:
                percorrer(item, escopo)

    percorrer(arvore, frozenset())
    return tabelas, tipos


def validar_sql(cur, sql: str) -> None:
    """Levanta ConsultaRecusada se a consulta não puder ser executada."""
    if not sql or not sql.strip():
        raise ConsultaRecusada("A consulta está vazia.", "Envie uma instrução SELECT.")
    try:
        instrucoes = cur.extract_statements(sql)
    except duckdb.Error as e:
        raise ConsultaRecusada(f"SQL inválido: {_limpar(e)}", "Corrija a sintaxe e tente de novo.")
    if len(instrucoes) != 1:
        raise ConsultaRecusada("Só é permitida uma instrução por consulta.",
                               "Envie uma instrução por chamada, sem `;` separando comandos.")
    try:
        bruto = cur.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0]
    except duckdb.Error as e:
        raise ConsultaRecusada(f"SQL inválido: {_limpar(e)}", "Corrija a sintaxe e tente de novo.")
    arvore = json.loads(bruto)
    if arvore.get("error"):
        mensagem = arvore.get("error_message", "")
        if "Only SELECT" in mensagem:
            raise ConsultaRecusada("Só consultas de leitura (SELECT ou WITH) são permitidas.",
                                   "Reescreva como SELECT. Para a estrutura das views use descrever_dados().")
        raise ConsultaRecusada(f"SQL inválido: {mensagem[:300]}", "Corrija a sintaxe e tente de novo.")

    tabelas, tipos = _analisar(arvore)
    proibidos = tipos - FONTES_PERMITIDAS
    if proibidos:
        raise ConsultaRecusada(
            f"Fonte de dados não permitida ({', '.join(sorted(proibidos))}): funções de tabela e comandos "
            "como SHOW, DESCRIBE ou PIVOT não são aceitos.",
            "Consulte as views vw_*; para ver colunas e métricas use descrever_dados().")
    for catalogo, esquema, nome in sorted(tabelas):
        if catalogo != "" or esquema not in ("", "main") or not _tabela_permitida(nome):
            qual = f"{esquema}.{nome}" if esquema else nome
            raise ConsultaRecusada(f"A tabela '{qual}' não está disponível para consulta.",
                                   "Use as views vw_*, as dimensões dim_* ou fato_transacoes; veja descrever_dados().")


def _limpar(erro) -> str:
    texto = str(erro).split("\n")[0]
    return re.sub(r"\s+", " ", texto)[:300]


def _seguro(v):
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return None if math.isnan(v) or math.isinf(v) else round(v, 4)
    if isinstance(v, Decimal):
        return round(float(v), 4)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return str(v)


def _erro(erro: str, sugestao: str, rastro: dict | None = None) -> dict:
    return {"erro": erro, "sugestao": sugestao, **(rastro or {})}


@registrar_chamada("executar_consulta")
def executar_consulta(sql: str, limite: int = LIMITE_PADRAO) -> dict:
    """Executa uma consulta SQL de leitura nas views do projeto e devolve o resultado.

    Use para perguntas pontuais (vendas de uma loja, ticket médio, comparação com o ano anterior).
    Não use para segmentação, CLV, churn ou testes estatísticos: para isso existem ferramentas próprias.
    Entrada: uma instrução SELECT ou WITH; limite de 1 a 200 linhas (padrão 20).
    """
    try:
        limite = max(1, min(int(limite), LIMITE_MAXIMO))
    except (TypeError, ValueError):
        return _erro("O limite precisa ser um número inteiro entre 1 e %d." % LIMITE_MAXIMO,
                     "Informe, por exemplo, limite=20.")
    try:
        cur = banco.cursor()
    except FileNotFoundError:
        return _erro("Nenhuma base carregada.", "Carregue os arquivos de dados antes de consultar.")

    rastro = banco.rastreabilidade(cur)
    sql_original = (sql or "").strip()
    try:
        validar_sql(cur, sql_original)
    except ConsultaRecusada as e:
        return _erro(e.erro, e.sugestao, rastro)

    nucleo = re.sub(r"[;\s]+$", "", sql_original)
    estourou = threading.Event()

    def interromper():
        estourou.set()
        cur.interrupt()

    temporizador = threading.Timer(TIMEOUT_S, interromper)
    temporizador.start()
    try:
        resultado = cur.execute(f"SELECT * FROM (\n{nucleo}\n) AS _consulta LIMIT {limite + 1}")
        colunas = [d[0] for d in resultado.description]
        linhas = [[_seguro(v) for v in r] for r in resultado.fetchall()]
        truncado = len(linhas) > limite
        linhas = linhas[:limite]
        total = len(linhas)
        if truncado:
            total = cur.execute(f"SELECT COUNT(*) FROM (\n{nucleo}\n) AS _consulta").fetchone()[0]
    except duckdb.InterruptException:
        return _erro(f"A consulta passou do tempo máximo de {TIMEOUT_S} s e foi interrompida.",
                     "Filtre por período, loja ou categoria, ou agregue antes de listar.", rastro)
    except duckdb.Error as e:
        if estourou.is_set():
            return _erro(f"A consulta passou do tempo máximo de {TIMEOUT_S} s e foi interrompida.",
                         "Filtre por período, loja ou categoria, ou agregue antes de listar.", rastro)
        return _erro(f"Erro ao executar a consulta: {_limpar(e)}",
                     "Confira nomes de colunas e views com descrever_dados() e tente de novo.", rastro)
    finally:
        temporizador.cancel()

    retorno = {"colunas": colunas, "linhas": linhas, "total_linhas": int(total), "truncado": truncado,
               "limite_aplicado": limite, "sql_executado": sql_original, **rastro}
    while len(json.dumps(retorno, ensure_ascii=False).encode()) > MAX_BYTES and retorno["linhas"]:
        retorno["linhas"] = retorno["linhas"][: max(0, len(retorno["linhas"]) // 2)]
        retorno["truncado"] = True
        retorno["aviso"] = "Retorno reduzido pelo limite de tamanho; refine a consulta (agregue ou filtre)."
    return retorno
