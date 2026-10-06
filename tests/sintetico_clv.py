"""Base sintética semanal (101 semanas) com quatro tipos de household, para testar CLV, churn e teste de desconto.

Cada household compra a cada semana com uma probabilidade própria (processo estacionário), com valor lognormal. As
tabelas criadas têm os nomes das views que as análises leem (vw_cliente_semana, vw_metricas_cliente, vw_janela ...).
Devolve também a tabela semanal em pandas, para os testes recalcularem os números por um caminho independente do SQL.
"""

from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.nucleo import rfm

# tipo: (probabilidade de comprar na semana, valor médio por compra, households)
TIPOS = {"fieis": (0.93, 42.0, 220), "regulares": (0.55, 27.0, 260), "esporadicos": (0.17, 24.0, 170), "pausa": (0.06, 22.0, 100)}
SEMANAS = 101
DATA_BASE = date(2016, 1, 1)


def gerar_semanal(semente: int = 11) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(semente)
    linhas, hh, h = [], [], 1
    for tipo, (p, media, n) in TIPOS.items():
        for _ in range(n):
            hh.append({"household_key": h, "tipo": tipo})
            comprou = rng.random(SEMANAS) < p
            for w in np.flatnonzero(comprou) + 1:
                cestas = 1 + int(rng.random() < 0.3)
                valor = float(np.round(rng.lognormal(np.log(media), 0.35) * cestas, 2))
                dia = int((w - 1) * 7 + int(rng.integers(1, 8)))
                linhas.append({"household_key": h, "WEEK_NO": int(w), "cestas": cestas, "faturamento": valor, "itens": cestas * 9.0,
                               "desconto_total": round(valor * 0.15 / 0.85, 2), "valor_bruto": round(valor / 0.85, 2),
                               "ultima_data": DATA_BASE + timedelta(days=dia - 1)})
            h += 1
    return pd.DataFrame(linhas), pd.DataFrame(hh)


def criar_banco(destino: Path, semente: int = 11, ultima_semana: int = SEMANAS) -> tuple[Path, pd.DataFrame, pd.DataFrame]:
    semanal, hh = gerar_semanal(semente)
    semanal = semanal[semanal["WEEK_NO"] <= ultima_semana].reset_index(drop=True)
    c = duckdb.connect(str(destino))
    c.register("semanal_df", semanal)
    c.execute("CREATE TABLE vw_cliente_semana AS SELECT * FROM semanal_df")
    c.execute(f"""CREATE TABLE dim_data AS SELECT d AS data_id, DATE '{DATA_BASE}' + CAST(d - 1 AS INTEGER) AS data,
        CAST((d - 1) // 7 + 1 AS INTEGER) AS WEEK_NO, 7 AS dias_na_semana, TRUE AS semana_completa
        FROM range(1, {ultima_semana * 7 + 1}) t(d)""")
    c.register("hh_df", hh[["household_key"]].assign(tem_demografia=False))
    c.execute("CREATE TABLE dim_household AS SELECT * FROM hh_df")
    c.execute("CREATE TABLE meta (chave VARCHAR, valor VARCHAR)")
    c.execute("INSERT INTO meta VALUES ('versao_base', 'sintetica_clv')")
    fim_atual, ini_atual, fim_base, ini_base = ultima_semana, ultima_semana - 25, ultima_semana - 52, ultima_semana - 77
    def data_do_dia(semana_ini, semana_fim, ultimo):
        return (DATA_BASE + timedelta(days=(semana_fim * 7 if ultimo else (semana_ini - 1) * 7 + 1) - 1)).isoformat()
    c.execute(f"""CREATE TABLE vw_janela AS SELECT {ini_atual} AS semana_ini_atual, {fim_atual} AS semana_fim_atual,
        {ini_base} AS semana_ini_base, {fim_base} AS semana_fim_base, 26 AS semanas, 52 AS offset_semanas, 8 AS cliente_ativo_semanas,
        DATE '{data_do_dia(ini_atual, fim_atual, False)}' AS data_ini_atual, DATE '{data_do_dia(ini_atual, fim_atual, True)}' AS data_fim_atual,
        DATE '{data_do_dia(ini_base, fim_base, False)}' AS data_ini_base, DATE '{data_do_dia(ini_base, fim_base, True)}' AS data_fim_base""")
    cur = c.cursor()
    partes = []
    for periodo, (a, b) in {"atual": (ini_atual, fim_atual), "base": (ini_base, fim_base)}.items():
        df, _ = rfm.base_rfm(cur, a, b)
        partes.append(df.assign(periodo=periodo))
    c.register("metricas_df", pd.concat(partes, ignore_index=True))
    c.execute("CREATE TABLE vw_metricas_cliente AS SELECT household_key, periodo, recencia_dias, frequencia, valor, ticket_medio, "
              "pct_desconto, desconto_total, valor_bruto, tem_demografia FROM metricas_df")
    c.close()
    return destino, semanal, hh
