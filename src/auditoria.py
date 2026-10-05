"""Auditoria inicial da base bruta (fase 1). Só lê data/raw/; não altera nada.

Responde às perguntas do passo 2 do guia de boas práticas: granularidade, chaves,
nulos, sinais, linhas estranhas, cobertura temporal. Gera relatorios/auditoria_fase1.md.

Uso: python -m src.auditoria
"""

from pathlib import Path

import duckdb
import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
RAW = RAIZ / CFG["dados"]["pasta_raw"]
TABELAS = ["transaction_data", "product", "hh_demographic", "campaign_table",
           "campaign_desc", "coupon", "coupon_redempt", "causal_data"]


def _md(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False) if len(df) else "_(vazio)_"


def auditar() -> str:
    con = duckdb.connect()
    for t in TABELAS:
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_csv_auto('{(RAW / (t + '.csv')).as_posix()}')")

    q = lambda sql: con.execute(sql).df()
    out = ["# Auditoria da base bruta (fase 1)\n"]

    # 1. Tamanho e colunas
    linhas = []
    for t in TABELAS:
        n = q(f"SELECT COUNT(*) n FROM {t}").n[0]
        cols = ", ".join(q(f"DESCRIBE {t}").column_name)
        linhas.append({"tabela": t, "linhas": n, "colunas": cols})
    out += ["## 1. Tabelas, linhas e colunas", _md(pd.DataFrame(linhas)), ""]

    # 2. Granularidade e chaves
    chaves = q("""
        SELECT 'transaction_data: (BASKET_ID, PRODUCT_ID) duplicado' AS checagem,
               COUNT(*) - COUNT(DISTINCT (BASKET_ID, PRODUCT_ID)) AS valor FROM transaction_data
        UNION ALL SELECT 'transaction_data: linhas 100% idênticas',
               COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM transaction_data)) FROM transaction_data
        UNION ALL SELECT 'product: PRODUCT_ID duplicado', COUNT(*) - COUNT(DISTINCT PRODUCT_ID) FROM product
        UNION ALL SELECT 'hh_demographic: household_key duplicado', COUNT(*) - COUNT(DISTINCT household_key) FROM hh_demographic
        UNION ALL SELECT 'transaction_data: PRODUCT_ID órfão (fora de product)',
               COUNT(*) FROM transaction_data t WHERE NOT EXISTS (SELECT 1 FROM product p WHERE p.PRODUCT_ID = t.PRODUCT_ID)
        UNION ALL SELECT 'households em transaction_data', COUNT(DISTINCT household_key) FROM transaction_data
        UNION ALL SELECT 'households sem demografia',
               COUNT(DISTINCT household_key) FROM transaction_data t
               WHERE NOT EXISTS (SELECT 1 FROM hh_demographic h WHERE h.household_key = t.household_key)
        UNION ALL SELECT 'lojas distintas', COUNT(DISTINCT STORE_ID) FROM transaction_data
        UNION ALL SELECT 'cestas distintas', COUNT(DISTINCT BASKET_ID) FROM transaction_data
        UNION ALL SELECT 'cestas que aparecem em mais de uma loja ou household',
               COUNT(*) FROM (SELECT BASKET_ID FROM transaction_data GROUP BY 1
                              HAVING COUNT(DISTINCT STORE_ID) > 1 OR COUNT(DISTINCT household_key) > 1)
    """)
    out += ["## 2. Granularidade e chaves", _md(chaves), ""]

    # 3. Nulos e tipos
    nulos = []
    for t in TABELAS:
        for c in q(f"DESCRIBE {t}").column_name:
            n = q(f'SELECT COUNT(*) - COUNT("{c}") n FROM {t}').n[0]
            if n:
                nulos.append({"tabela": t, "coluna": c, "nulos": n})
    out += ["## 3. Nulos por coluna", _md(pd.DataFrame(nulos)), ""]

    # 4. Valores: sinais, zeros, extremos
    valores = q("""
        SELECT
          SUM((SALES_VALUE < 0)::INT) AS sales_negativo, SUM((SALES_VALUE = 0)::INT) AS sales_zero,
          SUM((QUANTITY <= 0)::INT) AS qtd_nao_positiva, SUM((QUANTITY = 0)::INT) AS qtd_zero,
          SUM((QUANTITY > 100)::INT) AS qtd_maior_100, MAX(QUANTITY) AS qtd_max,
          SUM((RETAIL_DISC > 0)::INT) AS retail_disc_positivo, SUM((RETAIL_DISC < 0)::INT) AS retail_disc_negativo,
          SUM((COUPON_DISC > 0)::INT) AS coupon_disc_positivo, SUM((COUPON_DISC < 0)::INT) AS coupon_disc_negativo,
          SUM((COUPON_MATCH_DISC > 0)::INT) AS match_disc_positivo, SUM((COUPON_MATCH_DISC < 0)::INT) AS match_disc_negativo
        FROM transaction_data
    """).T.reset_index()
    valores.columns = ["metrica", "linhas"]
    out += ["## 4. Sinais e valores estranhos (contagem de linhas)", _md(valores), ""]

    resumo_num = q("""
        SELECT 'SALES_VALUE' c, MIN(SALES_VALUE) min, quantile_cont(SALES_VALUE,0.5) mediana,
               quantile_cont(SALES_VALUE,0.99) p99, MAX(SALES_VALUE) max, SUM(SALES_VALUE) soma FROM transaction_data
        UNION ALL SELECT 'RETAIL_DISC', MIN(RETAIL_DISC), quantile_cont(RETAIL_DISC,0.5), quantile_cont(RETAIL_DISC,0.99), MAX(RETAIL_DISC), SUM(RETAIL_DISC) FROM transaction_data
        UNION ALL SELECT 'COUPON_DISC', MIN(COUPON_DISC), quantile_cont(COUPON_DISC,0.5), quantile_cont(COUPON_DISC,0.99), MAX(COUPON_DISC), SUM(COUPON_DISC) FROM transaction_data
        UNION ALL SELECT 'COUPON_MATCH_DISC', MIN(COUPON_MATCH_DISC), quantile_cont(COUPON_MATCH_DISC,0.5), quantile_cont(COUPON_MATCH_DISC,0.99), MAX(COUPON_MATCH_DISC), SUM(COUPON_MATCH_DISC) FROM transaction_data
    """).round(2)
    out += ["### Distribuição numérica", _md(resumo_num), ""]

    # Preço unitário implícito (sanidade) e combustível
    fuel = q("""
        SELECT p.DEPARTMENT, COUNT(*) linhas, ROUND(SUM(t.SALES_VALUE),0) vendas
        FROM transaction_data t LEFT JOIN product p USING (PRODUCT_ID)
        WHERE p.DEPARTMENT IS NULL OR p.DEPARTMENT ILIKE '%FUEL%' OR p.DEPARTMENT ILIKE '%GAS%'
              OR p.DEPARTMENT ILIKE '%MISC%' OR p.DEPARTMENT ILIKE '%COUPON%' OR p.DEPARTMENT = ''
        GROUP BY 1 ORDER BY vendas DESC
    """)
    out += ["### Departamentos suspeitos (combustível, cupom, misc, sem cadastro)", _md(fuel), ""]

    depto = q("""
        SELECT COALESCE(p.DEPARTMENT,'(sem cadastro)') departamento, COUNT(*) linhas,
               ROUND(SUM(t.SALES_VALUE),0) vendas
        FROM transaction_data t LEFT JOIN product p USING (PRODUCT_ID)
        GROUP BY 1 ORDER BY vendas DESC
    """)
    out += ["### Vendas por departamento (todas)", _md(depto), ""]

    # Relação SALES_VALUE x descontos: SALES_VALUE já é líquido?
    rel = q("""
        SELECT ROUND(SUM(SALES_VALUE),0) sales_total, ROUND(SUM(RETAIL_DISC),0) retail_total,
               ROUND(SUM(COUPON_DISC),0) coupon_total, ROUND(SUM(COUPON_MATCH_DISC),0) match_total,
               ROUND(-SUM(RETAIL_DISC + COUPON_MATCH_DISC) / NULLIF(SUM(SALES_VALUE - RETAIL_DISC - COUPON_MATCH_DISC),0) * 100, 2)
                 AS pct_desc_loja_sobre_bruto_hipotese
        FROM transaction_data
    """)
    out += ["### Totais de venda e desconto (conferir sinal antes de somar)", _md(rel), ""]

    # 5. Cobertura temporal
    temporal = q("""
        SELECT MIN(DAY) dia_min, MAX(DAY) dia_max, MIN(WEEK_NO) sem_min, MAX(WEEK_NO) sem_max,
               COUNT(DISTINCT DAY) dias_distintos, COUNT(DISTINCT WEEK_NO) semanas_distintas
        FROM transaction_data
    """)
    out += ["## 5. Cobertura temporal", _md(temporal), ""]

    inconsist = q("""
        SELECT COUNT(*) AS linhas_semana_diferente_de_formula FROM transaction_data
        WHERE WEEK_NO <> CEIL(DAY / 7.0)
    """)
    out += ["Linhas em que `WEEK_NO` ≠ `ceil(DAY/7)`:", _md(inconsist), ""]

    buracos = q("""
        WITH todos AS (SELECT UNNEST(range((SELECT MIN(DAY) FROM transaction_data),
                                           (SELECT MAX(DAY) FROM transaction_data) + 1)) AS d)
        SELECT d AS dia_sem_transacao FROM todos
        WHERE d NOT IN (SELECT DISTINCT DAY FROM transaction_data) ORDER BY d LIMIT 50
    """)
    out += ["Dias sem nenhuma transação (até 50):", _md(buracos), ""]

    semanal = q("""
        SELECT WEEK_NO, COUNT(DISTINCT DAY) dias, COUNT(DISTINCT STORE_ID) lojas,
               COUNT(DISTINCT household_key) households, COUNT(DISTINCT BASKET_ID) cestas,
               ROUND(SUM(SALES_VALUE),0) vendas
        FROM transaction_data GROUP BY 1 ORDER BY 1
    """)
    out += ["### Volume por semana (conferir semanas iniciais/finais incompletas)", _md(semanal), ""]

    # 6. Janela e like-for-like (prévia)
    smax = int(semanal.WEEK_NO.max())
    n = CFG["janela"]["semanas_atuais"]
    off = CFG["janela"]["offset_ano_anterior"]
    atual = (smax - n + 1, smax)
    base = (atual[0] - off, atual[1] - off)
    lfl = q(f"""
        WITH a AS (SELECT DISTINCT STORE_ID FROM transaction_data WHERE WEEK_NO BETWEEN {atual[0]} AND {atual[1]}),
             b AS (SELECT DISTINCT STORE_ID FROM transaction_data WHERE WEEK_NO BETWEEN {base[0]} AND {base[1]})
        SELECT (SELECT COUNT(*) FROM a) lojas_janela_atual, (SELECT COUNT(*) FROM b) lojas_base,
               (SELECT COUNT(*) FROM a JOIN b USING (STORE_ID)) lojas_nos_dois,
               (SELECT COUNT(*) FROM a WHERE STORE_ID NOT IN (SELECT STORE_ID FROM b)) so_na_atual,
               (SELECT COUNT(*) FROM b WHERE STORE_ID NOT IN (SELECT STORE_ID FROM a)) so_na_base
    """)
    out += [f"## 6. Janela proposta: semanas {atual[0]}–{atual[1]} contra {base[0]}–{base[1]}", _md(lfl), ""]

    # 7. Campanhas / causal
    camp = q("SELECT CAMPAIGN, DESCRIPTION, START_DAY, END_DAY FROM campaign_desc ORDER BY START_DAY")
    out += ["## 7. Campanhas (para explicar a base de comparação)", _md(camp), ""]
    causal = q("""SELECT MIN(WEEK_NO) sem_min, MAX(WEEK_NO) sem_max, COUNT(*) linhas FROM causal_data""")
    out += ["`causal_data` cobre:", _md(causal), ""]

    return "\n".join(out)


if __name__ == "__main__":
    texto = auditar()
    destino = RAIZ / "relatorios"
    destino.mkdir(exist_ok=True)
    (destino / "auditoria_fase1.md").write_text(texto, encoding="utf-8")
    print(f"Relatório salvo em {destino / 'auditoria_fase1.md'}")
