"""ETL: arquivos brutos -> DuckDB com Star Schema, limpeza instrumentada e reconciliação.

Camadas:
  raw_transaction_data  cópia tipada de toda linha do arquivo (nunca alterada)
  fato_transacoes       venda válida de mercadoria
  fato_ajustes          linhas retiradas da venda, cada uma com o motivo
Toda regra registra linhas afetadas e valor em US$. Todo JOIN tem a contagem de linhas
conferida antes e depois. O total limpo reconcilia com o bruto (por semana).

Uso: python -m src.etl
"""

import functools
import hashlib
import json
from datetime import datetime
from pathlib import Path

import duckdb

from src import qualidade, views
from src.config import CFG, RAIZ

TABELAS = [
    "transaction_data", "product", "hh_demographic", "campaign_table",
    "campaign_desc", "coupon", "coupon_redempt", "causal_data",
]

COLUNAS_OBRIGATORIAS = {
    "transaction_data": ["household_key", "BASKET_ID", "DAY", "PRODUCT_ID", "QUANTITY", "SALES_VALUE",
                         "STORE_ID", "RETAIL_DISC", "COUPON_DISC", "COUPON_MATCH_DISC", "WEEK_NO",
                         "TRANS_TIME"],
    "product": ["PRODUCT_ID", "DEPARTMENT", "COMMODITY_DESC", "SUB_COMMODITY_DESC", "MANUFACTURER",
                "BRAND", "CURR_SIZE_OF_PRODUCT"],
    "hh_demographic": ["household_key", "AGE_DESC", "MARITAL_STATUS_CODE", "INCOME_DESC",
                       "HOMEOWNER_DESC", "HOUSEHOLD_SIZE_DESC", "KID_CATEGORY_DESC"],
    "campaign_table": ["household_key", "CAMPAIGN", "DESCRIPTION"],
    "campaign_desc": ["CAMPAIGN", "DESCRIPTION", "START_DAY", "END_DAY"],
    "coupon": ["COUPON_UPC", "PRODUCT_ID", "CAMPAIGN"],
    "coupon_redempt": ["household_key", "DAY", "COUPON_UPC", "CAMPAIGN"],
    "causal_data": ["PRODUCT_ID", "STORE_ID", "WEEK_NO", "display", "mailer"],
}


TIPOS_AUXILIARES = {
    "campaign_table": {"household_key": "BIGINT", "CAMPAIGN": "BIGINT", "DESCRIPTION": "VARCHAR"},
    "campaign_desc": {"CAMPAIGN": "BIGINT", "DESCRIPTION": "VARCHAR", "START_DAY": "INTEGER", "END_DAY": "INTEGER"},
    "coupon": {"COUPON_UPC": "VARCHAR", "PRODUCT_ID": "BIGINT", "CAMPAIGN": "BIGINT"},
    "coupon_redempt": {"household_key": "BIGINT", "DAY": "INTEGER", "COUPON_UPC": "VARCHAR", "CAMPAIGN": "BIGINT"},
}


class ErroCarga(Exception):
    """Falha de carga com mensagem legível para o usuário (arquivo, coluna, regra)."""


def _lit(texto: str) -> str:
    return "'" + str(texto).replace("'", "''") + "'"


def _csv(caminho: Path) -> str:
    return f"read_csv({_lit(Path(caminho).as_posix())}, header=true, all_varchar=true)"


@functools.lru_cache(maxsize=64)
def _md5_do_arquivo(caminho: str, tamanho: int, modificado_ns: int) -> str:
    h = hashlib.md5()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _md5(caminho: Path) -> str:
    """MD5 do arquivo; guardado por (caminho, tamanho, data de modificação) para não reler 700 MB a cada sessão."""
    info = Path(caminho).stat()
    return _md5_do_arquivo(str(caminho), info.st_size, info.st_mtime_ns)


def localizar_fontes(pasta: Path) -> dict[str, Path]:
    return {t: Path(pasta) / f"{t}.csv" for t in TABELAS}


def colunas_faltantes(caminho: Path, tabela: str) -> list[str]:
    """Colunas obrigatórias da tabela que não aparecem no cabeçalho do arquivo (sem diferenciar maiúsculas)."""
    con = duckdb.connect()
    try:
        cols = [c.lower() for c in con.execute(f"SELECT * FROM {_csv(caminho)} LIMIT 0").df().columns]
    finally:
        con.close()
    return [c for c in COLUNAS_OBRIGATORIAS[tabela] if c.lower() not in cols]


def validar_fontes(fontes: dict[str, Path]) -> None:
    """Confere se cada tabela existe e traz as colunas obrigatórias."""
    ausentes = [t for t in TABELAS if t not in fontes or not Path(fontes[t]).exists()]
    if ausentes:
        raise ErroCarga(f"Arquivos ausentes: {', '.join(t + '.csv' for t in ausentes)}.")
    for tabela in COLUNAS_OBRIGATORIAS:
        faltam = colunas_faltantes(fontes[tabela], tabela)
        if faltam:
            raise ErroCarga(f"{tabela}.csv: faltam as colunas {', '.join(faltam)}.")


# Muda quando a lógica de limpeza, do esquema ou das views muda: invalida bancos em cache.
ETL_VERSAO = "4"


def calcular_versao(fontes: dict[str, Path], cfg: dict | None = None) -> tuple[str, list[dict]]:
    """Hash da carga: conteúdo dos arquivos + parâmetros que afetam o resultado + versão da lógica."""
    cfg = cfg or CFG
    arquivos = []
    for t in TABELAS:
        caminho = Path(fontes[t])
        arquivos.append({"tabela": t, "arquivo": caminho.name, "md5": _md5(caminho),
                         "tamanho_bytes": caminho.stat().st_size})
    parametros = json.dumps({k: cfg.get(k) for k in ("dados", "janela", "metricas", "limpeza")},
                            sort_keys=True, default=str)
    base = "".join(a["md5"] for a in arquivos) + parametros + ETL_VERSAO
    return hashlib.md5(base.encode()).hexdigest()[:12], arquivos


def _n(con, sql: str):
    return con.execute(sql).fetchone()[0]


def _regras_exclusao(cfg: dict) -> list[dict]:
    deptos = ", ".join(_lit(d.upper()) for d in cfg["limpeza"]["departamentos_excluidos"])
    commods = ", ".join(_lit(c.upper()) for c in cfg["limpeza"]["commodities_excluidas"])
    return [
        {"regra": "valor_nao_numerico",
         "predicado": "QUANTITY IS NULL OR SALES_VALUE IS NULL",
         "descricao": "QUANTITY ou SALES_VALUE ausente ou não numérico",
         "motivo": "Sem quantidade ou valor a linha não é venda mensurável."},
        {"regra": "cesta_ausente",
         "predicado": "BASKET_ID IS NULL",
         "descricao": "BASKET_ID ausente",
         "motivo": "Venda válida exige cesta; sem ela não há transação concluída."},
        {"regra": "chave_ou_data_invalida",
         "predicado": ("DAY IS NULL OR DAY < 1 OR WEEK_NO IS NULL OR household_key IS NULL "
                       "OR STORE_ID IS NULL OR PRODUCT_ID IS NULL"),
         "descricao": "DAY, WEEK_NO, household, loja ou produto ausente/inválido",
         "motivo": "Sem data não entra em recência/cohort; sem chave não entra no esquema."},
        {"regra": "nao_mercadoria",
         "predicado": (f"UPPER(TRIM(DEPARTMENT)) IN ({deptos}) "
                       f"OR UPPER(TRIM(COMMODITY_DESC)) IN ({commods})"),
         "descricao": "Combustível, transações diversas e pseudo-itens de cupom",
         "motivo": ("Não é mercadoria: distorce itens por cesta e ticket "
                    "(pseudo-itens chegam a 89 mil unidades). Decisão A, 2026-10-05.")},
        {"regra": "quantidade_nao_positiva",
         "predicado": "QUANTITY <= 0",
         "descricao": "QUANTITY menor ou igual a zero",
         "motivo": "Venda válida exige QUANTITY > 0. Na auditoria só havia QUANTITY = 0 (sem devoluções)."},
    ]


def construir_banco(fontes: dict[str, Path], destino: Path | None = None, cfg: dict | None = None,
                    log=print) -> dict:
    """Constrói o banco a partir dos arquivos. Devolve o relatório de qualidade (dict)."""
    cfg = cfg or CFG
    destino = Path(destino or RAIZ / cfg["banco"]["arquivo"])
    destino.parent.mkdir(parents=True, exist_ok=True)
    validar_fontes(fontes)

    historico = _ler_historico(destino)
    tmp = destino.with_name(destino.stem + ".construindo.duckdb")
    for p in (tmp, Path(str(tmp) + ".wal")):
        p.unlink(missing_ok=True)

    con = duckdb.connect(str(tmp))
    rel: dict = {"joins": [], "avisos": []}
    data_carga = datetime.now().replace(microsecond=0)

    # --- 1. Versão da base (hash dos arquivos) e log de cargas ------------------------------
    log("Calculando hash dos arquivos ...")
    versao_base, arquivos = calcular_versao(fontes, cfg)
    rel.update(versao_base=versao_base, data_carga=data_carga.isoformat(), arquivos=arquivos)

    # --- 2. Estágio texto -> bruto tipado --------------------------------------------------
    log("Lendo transaction_data ...")
    con.execute(f"CREATE TABLE stg_transaction AS SELECT row_number() OVER () AS row_id, * "
                f"FROM {_csv(fontes['transaction_data'])}")
    linhas_brutas = _n(con, "SELECT COUNT(*) FROM stg_transaction")
    rel["linhas_brutas"] = linhas_brutas

    tipos = {"household_key": "BIGINT", "BASKET_ID": "BIGINT", "DAY": "INTEGER", "PRODUCT_ID": "BIGINT",
             "QUANTITY": "DOUBLE", "SALES_VALUE": "DECIMAL(18,4)", "STORE_ID": "BIGINT",
             "RETAIL_DISC": "DECIMAL(18,4)", "COUPON_DISC": "DECIMAL(18,4)",
             "COUPON_MATCH_DISC": "DECIMAL(18,4)", "WEEK_NO": "INTEGER"}
    conv = {}
    for col, tipo in tipos.items():
        ausentes = _n(con, f'SELECT COUNT(*) FROM stg_transaction WHERE "{col}" IS NULL OR TRIM("{col}") = \'\'')
        falhas = _n(con, f'SELECT COUNT(*) FROM stg_transaction WHERE "{col}" IS NOT NULL '
                         f'AND TRIM("{col}") <> \'\' AND TRY_CAST("{col}" AS {tipo}) IS NULL')
        conv[col] = {"ausentes": ausentes, "nao_numericos": falhas, "arredondadas": 0, "efeito_arredondamento_usd": 0.0}
        if tipo.startswith("DECIMAL"):
            # O arquivo traz ruído de ponto flutuante (ex.: 5.55E-17) e valores com mais de 4 casas.
            # Arredondar muda a soma; por isso a quantidade e o efeito entram no relatório.
            n_arr, efeito = con.execute(
                f'SELECT COUNT(*) FILTER (WHERE ABS(x - CAST(y AS DOUBLE)) > 0), '
                f'COALESCE(SUM(x) - SUM(CAST(y AS DOUBLE)), 0) FROM '
                f'(SELECT TRY_CAST("{col}" AS DOUBLE) AS x, TRY_CAST("{col}" AS {tipo}) AS y FROM stg_transaction)'
            ).fetchone()
            conv[col]["arredondadas"], conv[col]["efeito_arredondamento_usd"] = int(n_arr), float(efeito)
    rel["conversao_numerica"] = conv

    selecao = ", ".join(f'TRY_CAST("{c}" AS {t}) AS "{c}"' for c, t in tipos.items())
    con.execute(f"CREATE TABLE raw_transaction_data AS SELECT row_id, {selecao}, "
                f"TRIM(TRANS_TIME) AS TRANS_TIME FROM stg_transaction")
    con.execute("DROP TABLE stg_transaction")

    # --- 3. Dimensões de apoio e tabelas pequenas ---------------------------------------------
    log("Montando dimensões ...")
    n_prod_raw = _n(con, f"SELECT COUNT(*) FROM {_csv(fontes['product'])}")
    n_prod_id = _n(con, f"SELECT COUNT(DISTINCT PRODUCT_ID) FROM {_csv(fontes['product'])}")
    rel["duplicados"] = {"product_id_duplicado": n_prod_raw - n_prod_id}
    if n_prod_raw != n_prod_id:
        rel["avisos"].append(f"product: {n_prod_raw - n_prod_id} PRODUCT_ID duplicados; mantida a 1ª ocorrência.")
    con.execute(f"""CREATE TABLE dim_produto AS
        SELECT TRY_CAST(PRODUCT_ID AS BIGINT) AS PRODUCT_ID, DEPARTMENT, COMMODITY_DESC, SUB_COMMODITY_DESC,
               MANUFACTURER, BRAND, CURR_SIZE_OF_PRODUCT
        FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY PRODUCT_ID) AS rn FROM {_csv(fontes['product'])})
        WHERE rn = 1""")
    rel["joins"].append({"join": "product -> dim_produto (chave única)", "antes": n_prod_id,
                         "depois": _n(con, "SELECT COUNT(*) FROM dim_produto"),
                         "ok": n_prod_id == _n(con, "SELECT COUNT(*) FROM dim_produto")})

    # Tabelas auxiliares com tipos explícitos (um arquivo vazio faria o DuckDB inferir tudo como texto).
    # Valor que não converte vira nulo, mas a quantidade vai para os avisos do relatório.
    for t, tipos_aux in TIPOS_AUXILIARES.items():
        origem = _csv(fontes[t])
        con.execute(f"CREATE TABLE {t} AS SELECT "
                    + ", ".join(f'TRY_CAST("{c}" AS {tp}) AS "{c}"' for c, tp in tipos_aux.items())
                    + f" FROM {origem}")
        for c, tp in tipos_aux.items():
            perdidos = _n(con, f'SELECT COUNT(*) FROM {origem} WHERE "{c}" IS NOT NULL AND TRIM("{c}") <> \'\' '
                               f'AND TRY_CAST("{c}" AS {tp}) IS NULL')
            if perdidos:
                rel["avisos"].append(f"{t}.{c}: {perdidos:,} valores não conversíveis para {tp} viraram nulos.")

    con.execute(f"""CREATE TABLE causal_semana_loja AS
        SELECT TRY_CAST(WEEK_NO AS INTEGER) AS WEEK_NO, TRY_CAST(STORE_ID AS BIGINT) AS STORE_ID,
               COUNT(*) AS linhas,
               SUM((display IS NOT NULL AND TRIM(display) NOT IN ('', '0'))::INT) AS linhas_display,
               SUM((mailer IS NOT NULL AND TRIM(mailer) NOT IN ('', '0'))::INT) AS linhas_mailer
        FROM {_csv(fontes['causal_data'])} GROUP BY 1, 2""")

    # --- 4. Classificação das linhas (limpeza instrumentada) -----------------------------------
    log("Classificando linhas ...")
    regras = _regras_exclusao(cfg)
    case = "CASE " + " ".join(f"WHEN {r['predicado']} THEN '{r['regra']}'" for r in regras) + " END"
    con.execute(f"""CREATE TABLE stg_classificada AS
        SELECT t.*, p.DEPARTMENT, p.COMMODITY_DESC FROM raw_transaction_data t
        LEFT JOIN dim_produto p ON p.PRODUCT_ID = t.PRODUCT_ID""")
    depois_join = _n(con, "SELECT COUNT(*) FROM stg_classificada")
    rel["joins"].append({"join": "raw_transaction_data -> dim_produto (LEFT)", "antes": linhas_brutas,
                         "depois": depois_join, "ok": depois_join == linhas_brutas})
    if depois_join != linhas_brutas:
        raise ErroCarga("JOIN com produto multiplicou linhas; chave de produto não é única.")
    orfaos = _n(con, "SELECT COUNT(*) FROM stg_classificada WHERE DEPARTMENT IS NULL AND PRODUCT_ID IS NOT NULL "
                     "AND PRODUCT_ID NOT IN (SELECT PRODUCT_ID FROM dim_produto)")
    rel["duplicados"]["produto_orfao"] = orfaos

    con.execute(f"ALTER TABLE stg_classificada ADD COLUMN motivo VARCHAR")
    con.execute(f"UPDATE stg_classificada SET motivo = {case}")

    regras_rel = []
    for r in regras:
        afetadas = _n(con, f"SELECT COUNT(*) FROM stg_classificada WHERE {r['predicado']}")
        atrib, valor = con.execute(
            f"SELECT COUNT(*), COALESCE(SUM(SALES_VALUE), 0) FROM stg_classificada "
            f"WHERE motivo = '{r['regra']}'").fetchone()
        regras_rel.append({"regra": r["regra"], "descricao": r["descricao"], "motivo": r["motivo"],
                           "linhas_afetadas": afetadas, "linhas_atribuidas": atrib,
                           "valor_atribuido_usd": float(valor)})
    rel["regras"] = regras_rel

    # --- 5. Fato, ajustes e dimensões ------------------------------------------------------------
    hora = ("CASE WHEN TRY_CAST(SUBSTR(LPAD(TRANS_TIME, 4, '0'), 1, 2) AS INTEGER) BETWEEN 0 AND 23 "
            "AND TRY_CAST(SUBSTR(LPAD(TRANS_TIME, 4, '0'), 3, 2) AS INTEGER) BETWEEN 0 AND 59 "
            "THEN TRY_CAST(SUBSTR(LPAD(TRANS_TIME, 4, '0'), 1, 2) AS INTEGER) END")
    con.execute(f"""CREATE TABLE fato_transacoes AS
        SELECT household_key, BASKET_ID, DAY AS data_id, STORE_ID, PRODUCT_ID, QUANTITY, SALES_VALUE,
               COALESCE(RETAIL_DISC, 0) AS RETAIL_DISC, COALESCE(COUPON_DISC, 0) AS COUPON_DISC,
               COALESCE(COUPON_MATCH_DISC, 0) AS COUPON_MATCH_DISC, {hora} AS hora
        FROM stg_classificada WHERE motivo IS NULL""")
    con.execute("""CREATE TABLE fato_ajustes AS
        SELECT row_id, motivo, household_key, BASKET_ID, DAY, WEEK_NO, PRODUCT_ID, STORE_ID, QUANTITY,
               SALES_VALUE, RETAIL_DISC, COUPON_DISC, COUPON_MATCH_DISC, DEPARTMENT, COMMODITY_DESC
        FROM stg_classificada WHERE motivo IS NOT NULL""")
    nulos_desc = {c: _n(con, f"SELECT COUNT(*) FROM stg_classificada WHERE motivo IS NULL AND {c} IS NULL")
                  for c in ("RETAIL_DISC", "COUPON_DISC", "COUPON_MATCH_DISC")}
    rel["descontos_nulos_para_zero"] = nulos_desc
    rel["hora_invalida"] = _n(con, "SELECT COUNT(*) FROM stg_classificada WHERE motivo IS NULL AND "
                                   f"({hora}) IS NULL")
    con.execute("DROP TABLE stg_classificada")

    # dim_data: 1 linha por DAY. A data real é arbitrária: data_base + (DAY - 1).
    conflitos = _n(con, "SELECT COUNT(*) FROM (SELECT DAY FROM raw_transaction_data WHERE DAY IS NOT NULL "
                        "GROUP BY 1 HAVING COUNT(DISTINCT WEEK_NO) > 1)")
    if conflitos:
        raise ErroCarga(f"{conflitos} valores de DAY aparecem em mais de uma WEEK_NO.")
    con.execute(f"""CREATE TABLE dim_data AS
        WITH dias AS (SELECT UNNEST(range(1, (SELECT MAX(DAY) FROM raw_transaction_data) + 1)) AS data_id),
             semana AS (SELECT DAY AS data_id, MIN(WEEK_NO) AS WEEK_NO FROM raw_transaction_data GROUP BY 1)
        SELECT d.data_id, DATE {_lit(cfg['dados']['data_base'])} + CAST(d.data_id - 1 AS INTEGER) AS data,
               s.WEEK_NO,
               COUNT(*) OVER (PARTITION BY s.WEEK_NO) AS dias_na_semana,
               (COUNT(*) OVER (PARTITION BY s.WEEK_NO)) = 7 AS semana_completa
        FROM dias d LEFT JOIN semana s USING (data_id)""")
    con.execute("""ALTER TABLE dim_data ADD COLUMN dia_semana INTEGER;
                   ALTER TABLE dim_data ADD COLUMN mes INTEGER;
                   ALTER TABLE dim_data ADD COLUMN ano INTEGER;
                   UPDATE dim_data SET dia_semana = isodow(data), mes = month(data), ano = year(data);""")

    con.execute("CREATE TABLE dim_loja AS SELECT DISTINCT STORE_ID FROM raw_transaction_data "
                "WHERE STORE_ID IS NOT NULL ORDER BY 1")

    n_hh_demo = _n(con, f"SELECT COUNT(*) FROM {_csv(fontes['hh_demographic'])}")
    n_hh_demo_ids = _n(con, f"SELECT COUNT(DISTINCT household_key) FROM {_csv(fontes['hh_demographic'])}")
    if n_hh_demo != n_hh_demo_ids:
        raise ErroCarga("hh_demographic tem household_key duplicado.")
    n_hh = _n(con, "SELECT COUNT(DISTINCT household_key) FROM raw_transaction_data WHERE household_key IS NOT NULL")
    con.execute(f"""CREATE TABLE dim_household AS
        SELECT h.household_key, d.AGE_DESC, d.MARITAL_STATUS_CODE, d.INCOME_DESC, d.HOMEOWNER_DESC,
               d.HOUSEHOLD_SIZE_DESC, d.KID_CATEGORY_DESC, d.household_key IS NOT NULL AS tem_demografia
        FROM (SELECT DISTINCT household_key FROM raw_transaction_data WHERE household_key IS NOT NULL) h
        LEFT JOIN (SELECT * REPLACE (TRY_CAST(household_key AS BIGINT) AS household_key)
                   FROM {_csv(fontes['hh_demographic'])}) d ON d.household_key = h.household_key""")
    depois_hh = _n(con, "SELECT COUNT(*) FROM dim_household")
    rel["joins"].append({"join": "households -> hh_demographic (LEFT)", "antes": n_hh, "depois": depois_hh,
                         "ok": depois_hh == n_hh})
    if depois_hh != n_hh:
        raise ErroCarga("JOIN com demografia multiplicou households.")

    # --- 6. Metadados, log de cargas e relatório --------------------------------------------------
    con.execute("CREATE TABLE log_cargas (versao_base VARCHAR, tabela VARCHAR, arquivo VARCHAR, md5 VARCHAR, "
                "tamanho_bytes BIGINT, data_carga TIMESTAMP)")
    for h in historico:
        con.execute("INSERT INTO log_cargas VALUES (?, ?, ?, ?, ?, ?)", h)
    for a in arquivos:
        con.execute("INSERT INTO log_cargas VALUES (?, ?, ?, ?, ?, ?)",
                    [versao_base, a["tabela"], a["arquivo"], a["md5"], a["tamanho_bytes"], data_carga])
    con.execute("CREATE TABLE meta (chave VARCHAR, valor VARCHAR)")
    for k, v in {"versao_base": versao_base, "data_carga": data_carga.isoformat(),
                 "data_base": cfg["dados"]["data_base"]}.items():
        con.execute("INSERT INTO meta VALUES (?, ?)", [k, v])

    log("Criando views de métricas ...")
    views.criar_views(con, cfg)

    log("Gerando relatório de qualidade e reconciliando ...")
    rel = qualidade.completar_relatorio(con, rel, cfg)
    con.execute("INSERT INTO meta VALUES ('relatorio_qualidade', ?)", [json.dumps(rel, default=str)])
    ok = rel["reconciliacao"]["ok"]
    con.close()

    if not ok:
        raise ErroCarga("Reconciliação falhou: total limpo + ajustes difere do bruto. Banco não publicado. "
                        f"Detalhe: {rel['reconciliacao']}")
    for p in (destino, Path(str(destino) + ".wal")):
        p.unlink(missing_ok=True)
    tmp.replace(destino)
    return rel


def _ler_historico(destino: Path) -> list:
    if not destino.exists():
        return []
    try:
        con = duckdb.connect(str(destino), read_only=True)
        linhas = con.execute("SELECT versao_base, tabela, arquivo, md5, tamanho_bytes, data_carga "
                             "FROM log_cargas").fetchall()
        con.close()
        return linhas
    except duckdb.Error:
        return []


if __name__ == "__main__":
    relatorio = construir_banco(localizar_fontes(RAIZ / CFG["dados"]["pasta_raw"]))
    caminho = RAIZ / CFG["banco"]["relatorio_qualidade"]
    caminho.parent.mkdir(exist_ok=True)
    caminho.write_text(qualidade.renderizar_markdown(relatorio), encoding="utf-8")
    print(f"Banco: {RAIZ / CFG['banco']['arquivo']}")
    print(f"Relatório: {caminho}")
    print(f"versao_base: {relatorio['versao_base']}  |  reconciliação ok: {relatorio['reconciliacao']['ok']}")
