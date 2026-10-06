"""Base sintética de clientes com segmentos plantados, para testar as análises sem depender das views.

Cria, num arquivo DuckDB, as tabelas que as análises leem (com os nomes das views, como tabelas):
vw_metricas_cliente, dim_household, vw_janela, vw_cliente_semana e meta.
"""

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# média e desvio de R (dias) e de ln(1+F), ln(1+V); n de households. Bem separados de propósito.
SEGMENTOS = {
    "fieis": dict(r=(3, 2), f=(4.0, 0.25), v=(7.4, 0.30), n=300),
    "regulares": dict(r=(11, 4), f=(2.9, 0.30), v=(6.3, 0.35), n=330),
    "esporadicos": dict(r=(28, 8), f=(1.8, 0.35), v=(4.8, 0.40), n=140),
    "inativos": dict(r=(108, 25), f=(1.4, 0.30), v=(4.5, 0.40), n=70),
}


def gerar_clientes(semente: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(semente)
    linhas, h = [], 1
    for nome, p in SEGMENTOS.items():
        n = p["n"]
        r = np.clip(rng.normal(*p["r"], n), 0, 181).round()
        f = np.maximum(1, np.expm1(rng.normal(*p["f"], n)).round())
        v = np.maximum(1.0, np.expm1(rng.normal(*p["v"], n))).round(2)
        for i in range(n):
            pct = float(np.clip(rng.normal(15.5, 5), 0, 60))
            bruto = float(v[i]) / (1 - pct / 100)
            linhas.append({"household_key": h, "segmento_plantado": nome, "recencia_dias": int(r[i]),
                           "frequencia": int(f[i]), "valor": float(v[i]), "ticket_medio": float(v[i] / f[i]),
                           "pct_desconto": pct, "desconto_total": bruto - float(v[i]), "valor_bruto": bruto,
                           "tem_demografia": bool(i % 3 == 0)})
            h += 1
    return pd.DataFrame(linhas)


def criar_banco(destino: Path, clientes: pd.DataFrame | None = None, sem_compra: int = 7, extras: list[dict] | None = None,
                embaralhar: bool = False) -> Path:
    clientes = gerar_clientes() if clientes is None else clientes
    if extras:   # linhas a mais (ex.: household com valor <= 0)
        clientes = pd.concat([clientes, pd.DataFrame(extras)], ignore_index=True)
    ordem = clientes.sample(frac=1, random_state=3) if embaralhar else clientes
    c = duckdb.connect(str(destino))
    c.register("df", ordem.assign(periodo="atual")[["household_key", "periodo", "recencia_dias", "frequencia", "valor",
                                                      "ticket_medio", "pct_desconto", "desconto_total", "valor_bruto", "tem_demografia"]])
    c.execute("CREATE TABLE vw_metricas_cliente AS SELECT * FROM df")
    todos = list(clientes["household_key"]) + [int(clientes["household_key"].max()) + 1 + i for i in range(sem_compra)]
    c.execute("CREATE TABLE dim_household AS SELECT * FROM (VALUES " + ",".join(f"({h}, TRUE)" for h in todos)
              + ") t(household_key, tem_demografia)")
    c.execute("CREATE TABLE meta (chave VARCHAR, valor VARCHAR)")
    c.execute("INSERT INTO meta VALUES ('versao_base', 'sintetica1')")
    c.execute("""CREATE TABLE vw_janela AS SELECT 76 AS semana_ini_atual, 101 AS semana_fim_atual, 24 AS semana_ini_base,
        49 AS semana_fim_base, 26 AS semanas, 52 AS offset_semanas, 8 AS cliente_ativo_semanas,
        DATE '2017-06-07' AS data_ini_atual, DATE '2017-12-05' AS data_fim_atual,
        DATE '2016-06-08' AS data_ini_base, DATE '2016-12-06' AS data_fim_base""")
    c.execute("CREATE TABLE vw_cliente_semana (household_key BIGINT, WEEK_NO INTEGER, cestas BIGINT, faturamento DOUBLE, "
              "itens DOUBLE, desconto_total DOUBLE, valor_bruto DOUBLE)")
    c.close()
    return destino
