"""Relatório de qualidade dos dados: completa o que o ETL registrou, reconcilia com o bruto
e renderiza em Markdown. O mesmo dict alimenta o expander do app e o notebook."""

import json

import duckdb
import pandas as pd


def _q(con, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def _n(con, sql: str):
    return con.execute(sql).fetchone()[0]


def completar_relatorio(con, rel: dict, cfg: dict) -> dict:
    tol = cfg["banco"]["tolerancia_reconciliacao_usd"]

    # --- Reconciliação: bruto = limpo + ajustes, no total e por semana -------------------------
    con.execute("""CREATE TABLE reconciliacao_semanal AS
        WITH bruto AS (
            SELECT WEEK_NO, COUNT(*) AS linhas_bruto, SUM(SALES_VALUE) AS vendas_bruto,
                   SUM(QUANTITY) AS qtd_bruto
            FROM raw_transaction_data GROUP BY 1),
        limpo AS (
            SELECT d.WEEK_NO, COUNT(*) AS linhas_limpo, SUM(f.SALES_VALUE) AS vendas_limpo,
                   SUM(f.QUANTITY) AS qtd_limpo
            FROM fato_transacoes f JOIN dim_data d ON d.data_id = f.data_id GROUP BY 1),
        aj AS (
            SELECT WEEK_NO, COUNT(*) AS linhas_ajustes, SUM(SALES_VALUE) AS vendas_ajustes,
                   SUM(QUANTITY) AS qtd_ajustes
            FROM fato_ajustes GROUP BY 1)
        SELECT b.WEEK_NO, b.linhas_bruto,
               COALESCE(l.linhas_limpo, 0) AS linhas_limpo, COALESCE(a.linhas_ajustes, 0) AS linhas_ajustes,
               b.vendas_bruto, COALESCE(l.vendas_limpo, 0) AS vendas_limpo,
               COALESCE(a.vendas_ajustes, 0) AS vendas_ajustes,
               b.vendas_bruto - COALESCE(l.vendas_limpo, 0) - COALESCE(a.vendas_ajustes, 0) AS diferenca_vendas,
               b.linhas_bruto - COALESCE(l.linhas_limpo, 0) - COALESCE(a.linhas_ajustes, 0) AS diferenca_linhas
        FROM bruto b LEFT JOIN limpo l USING (WEEK_NO) LEFT JOIN aj a USING (WEEK_NO)
        ORDER BY 1""")
    sem = _q(con, "SELECT * FROM reconciliacao_semanal")
    tot_bruto, vend_bruto = con.execute("SELECT COUNT(*), SUM(SALES_VALUE) FROM raw_transaction_data").fetchone()
    n_limpo, v_limpo = con.execute("SELECT COUNT(*), COALESCE(SUM(SALES_VALUE), 0) FROM fato_transacoes").fetchone()
    n_aj, v_aj = con.execute("SELECT COUNT(*), COALESCE(SUM(SALES_VALUE), 0) FROM fato_ajustes").fetchone()
    max_dif = float(sem["diferenca_vendas"].abs().max())
    semanas_div = int(((sem["diferenca_linhas"] != 0) | (sem["diferenca_vendas"].abs() > tol)).sum())
    ok = (tot_bruto == n_limpo + n_aj and abs(float(vend_bruto - v_limpo - v_aj)) <= tol and semanas_div == 0
          and rel["linhas_brutas"] == tot_bruto)
    rel["reconciliacao"] = {
        "ok": bool(ok), "linhas_brutas": int(tot_bruto), "linhas_limpas": int(n_limpo),
        "linhas_ajustes": int(n_aj), "vendas_brutas_usd": float(vend_bruto),
        "vendas_limpas_usd": float(v_limpo), "vendas_ajustes_usd": float(v_aj),
        "semanas_conferidas": int(len(sem)), "semanas_divergentes": semanas_div,
        "maior_diferenca_semanal_usd": max_dif, "tolerancia_usd": tol,
    }
    rel["linhas_limpas"], rel["linhas_ajustes"] = int(n_limpo), int(n_aj)

    # --- Nulos e duplicados no bruto -----------------------------------------------------------
    cols = _q(con, "DESCRIBE raw_transaction_data").column_name.tolist()
    rel["nulos_por_coluna"] = {c: int(_n(con, f'SELECT COUNT(*) - COUNT("{c}") FROM raw_transaction_data'))
                               for c in cols if c != "row_id"}
    rel["duplicados"]["cesta_produto_repetido"] = int(_n(
        con, "SELECT COUNT(*) - COUNT(DISTINCT (BASKET_ID, PRODUCT_ID)) FROM raw_transaction_data"))
    rel["duplicados"]["linhas_identicas"] = int(_n(
        con, "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * EXCLUDE (row_id) "
             "FROM raw_transaction_data)) FROM raw_transaction_data"))

    # --- Casos que ficam na venda, mas merecem registro ------------------------------------------
    rel["casos_mantidos"] = {
        "itens_gratis_sales_zero_qtd_positiva": int(_n(con, "SELECT COUNT(*) FROM fato_transacoes WHERE SALES_VALUE = 0")),
        "retail_disc_positivo_estorno": int(_n(con, "SELECT COUNT(*) FROM fato_transacoes WHERE RETAIL_DISC > 0")),
        "coupon_disc_positivo": int(_n(con, "SELECT COUNT(*) FROM fato_transacoes WHERE COUPON_DISC > 0")),
        "coupon_match_positivo": int(_n(con, "SELECT COUNT(*) FROM fato_transacoes WHERE COUPON_MATCH_DISC > 0")),
        "departamento_vazio": int(_n(con, "SELECT COUNT(*) FROM fato_transacoes f JOIN dim_produto p USING (PRODUCT_ID) "
                                          "WHERE p.DEPARTMENT IS NULL OR TRIM(p.DEPARTMENT) = ''")),
        "quantidade_extrema_gt_100": int(_n(con, "SELECT COUNT(*) FROM fato_transacoes WHERE QUANTITY > 100")),
    }

    # --- Cobertura -----------------------------------------------------------------------------------
    rel["cobertura"] = {
        "households": int(_n(con, "SELECT COUNT(*) FROM dim_household")),
        "households_sem_demografia": int(_n(con, "SELECT COUNT(*) FROM dim_household WHERE NOT tem_demografia")),
        "lojas": int(_n(con, "SELECT COUNT(*) FROM dim_loja")),
        "semanas": int(_n(con, "SELECT COUNT(DISTINCT WEEK_NO) FROM dim_data WHERE WEEK_NO IS NOT NULL")),
        "semanas_incompletas": _q(con, "SELECT DISTINCT WEEK_NO, dias_na_semana FROM dim_data "
                                       "WHERE NOT semana_completa AND WEEK_NO IS NOT NULL ORDER BY 1").to_dict("records"),
        "dia_min": int(_n(con, "SELECT MIN(data_id) FROM dim_data")), "dia_max": int(_n(con, "SELECT MAX(data_id) FROM dim_data")),
        "data_min": str(_n(con, "SELECT MIN(data) FROM dim_data")), "data_max": str(_n(con, "SELECT MAX(data) FROM dim_data")),
        "causal_semana_min": _n(con, "SELECT MIN(WEEK_NO) FROM causal_semana_loja"),
        "causal_semana_max": _n(con, "SELECT MAX(WEEK_NO) FROM causal_semana_loja"),
    }

    # --- Sanity check provisório (a definição oficial vem das views, fase 3) --------------------------
    s = con.execute("""SELECT SUM(SALES_VALUE), COUNT(DISTINCT BASKET_ID), SUM(QUANTITY),
                              SUM(RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC)
                       FROM fato_transacoes""").fetchone()
    vendas, cestas, qtd, desc = (float(x) for x in s)
    rel["sanity_check"] = {
        "nota": "Provisório: a definição oficial vem das views da fase 3.",
        "vendas_liquidas_usd": vendas, "cestas": int(cestas),
        "ticket_medio_usd": vendas / cestas,
        "itens_por_cesta": qtd / cestas,
        "desconto_total_usd": desc,
        "desconto_pct_do_bruto": -desc / (vendas - desc) * 100,
    }
    return json.loads(json.dumps(rel, default=str))


def _tabela(linhas: list[dict], colunas: list[str]) -> str:
    if not linhas:
        return "_(nenhum)_\n"
    out = ["| " + " | ".join(colunas) + " |", "|" + "|".join("---" for _ in colunas) + "|"]
    for l in linhas:
        out.append("| " + " | ".join(_fmt(l.get(c)) for c in colunas) + " |")
    return "\n".join(out) + "\n"


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v)


def renderizar_markdown(rel: dict) -> str:
    r = rel["reconciliacao"]
    sc = rel["sanity_check"]
    cob = rel["cobertura"]
    L = ["# Relatório de qualidade dos dados", "",
         f"- **versao_base:** `{rel['versao_base']}` · carga em {rel['data_carga']}",
         f"- **Reconciliação com o bruto:** {'OK' if r['ok'] else 'FALHOU'} "
         f"({r['semanas_conferidas']} semanas conferidas, {r['semanas_divergentes']} divergentes, "
         f"maior diferença semanal US$ {r['maior_diferenca_semanal_usd']:.4f})", "",
         "## 1. Do bruto ao limpo",
         f"{r['linhas_brutas']:,} linhas brutas = {r['linhas_limpas']:,} em `fato_transacoes` "
         f"+ {r['linhas_ajustes']:,} em `fato_ajustes`. Vendas: US$ {r['vendas_brutas_usd']:,.2f} bruto = "
         f"US$ {r['vendas_limpas_usd']:,.2f} limpo + US$ {r['vendas_ajustes_usd']:,.2f} ajustes.", "",
         "Cada linha cai numa única regra (por precedência, na ordem abaixo). "
         "`linhas_afetadas` conta quem satisfaz a regra independentemente das outras.", "",
         _tabela(rel["regras"], ["regra", "descricao", "linhas_afetadas", "linhas_atribuidas",
                                 "valor_atribuido_usd", "motivo"]),
         "## 2. Conversão numérica (QUANTITY, SALES_VALUE, descontos, chaves)",
         _tabela([{"coluna": c, **v} for c, v in rel["conversao_numerica"].items()],
                 ["coluna", "ausentes", "nao_numericos", "arredondadas", "efeito_arredondamento_usd"]),
         "Valores monetários são lidos com 4 casas decimais. `arredondadas` conta as linhas com mais casas "
         "que isso (ruído de ponto flutuante do arquivo, como 5.55E-17) e `efeito_arredondamento_usd` a "
         "diferença que o arredondamento causa na soma.", "",
         "Descontos nulos convertidos para 0 na venda válida: "
         + ", ".join(f"{c} = {n:,}" for c, n in rel["descontos_nulos_para_zero"].items())
         + f". Horários inválidos (`hora` fica nula): {rel['hora_invalida']:,}.", "",
         "## 3. JOINs (linhas antes e depois)",
         _tabela(rel["joins"], ["join", "antes", "depois", "ok"]),
         "## 4. Nulos e duplicados no bruto",
         _tabela([{"coluna": c, "nulos": n} for c, n in rel["nulos_por_coluna"].items()], ["coluna", "nulos"]),
         "Duplicados e órfãos: " + ", ".join(f"{c} = {n:,}" for c, n in rel["duplicados"].items()), "",
         "## 5. Casos mantidos na venda (registro)",
         _tabela([{"caso": c, "linhas": n} for c, n in rel["casos_mantidos"].items()], ["caso", "linhas"]),
         "## 6. Cobertura",
         f"- Households: {cob['households']:,} ({cob['households_sem_demografia']:,} sem demografia, "
         f"{cob['households_sem_demografia'] / cob['households']:.0%}) · lojas: {cob['lojas']:,} · "
         f"semanas: {cob['semanas']}",
         f"- DAY {cob['dia_min']}–{cob['dia_max']} (datas {cob['data_min']} a {cob['data_max']}; "
         "data-base arbitrária, o dataset não tem calendário real)",
         "- Semanas incompletas: "
         + ", ".join(f"WEEK_NO {s['WEEK_NO']} ({s['dias_na_semana']} dias)" for s in cob["semanas_incompletas"]),
         f"- `causal_data` (display/mailer) cobre as semanas {cob['causal_semana_min']}–{cob['causal_semana_max']}", "",
         "## 7. Sanity check (provisório)",
         f"- Ticket médio: US$ {sc['ticket_medio_usd']:.2f} · itens por cesta: {sc['itens_por_cesta']:.1f} · "
         f"desconto: {sc['desconto_pct_do_bruto']:.1f}% do bruto "
         f"(US$ {-sc['desconto_total_usd']:,.0f} sobre US$ {sc['vendas_liquidas_usd']:,.0f} líquidos)",
         f"- {sc['nota']}", ""]
    if rel["avisos"]:
        L += ["## Avisos", *[f"- {a}" for a in rel["avisos"]], ""]
    return "\n".join(L)
