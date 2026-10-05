"""
teste_hipotese.py
REAPROVEITÁVEIS 100% (agnósticas de schema — recebem nomes de coluna como
parâmetro): testar_normalidade_por_grupo, teste_kruskal_wallis,
post_hoc_pairwise_mannwhitney.

A REESCREVER: calcular_desconto_percentual e preparar_dados_teste são
do schema antigo. Reescrever para o Dunnhumby: % de desconto por household =
(RETAIL_DISC + COUPON_DISC + COUPON_MATCH_DISC) / valor bruto, usando as views
de métricas do projeto (verificar antes o sinal das colunas de desconto).
"""

import pandas as pd
from itertools import combinations
from scipy import stats
from statsmodels.stats.multitest import multipletests


# ==========================================
# A REESCREVER PARA O DUNNHUMBY — isto é só o exemplo do schema antigo
# ==========================================
def calcular_desconto_percentual(engine) -> pd.DataFrame:
    """SUBSTITUIR: query do schema antigo. Reescrever sobre as views do Dunnhumby."""
    query = """
        SELECT
            cliente_id,
            SUM(faturamento) AS faturamento_bruto,
            SUM(desconto) AS desconto_total,
            (SUM(desconto) / NULLIF(SUM(faturamento), 0)) * 100 AS percentual_desconto
        FROM fato_vendas
        WHERE cliente_id IS NOT NULL
        GROUP BY cliente_id
        HAVING SUM(faturamento) > 0
    """
    return pd.read_sql(query, engine)


def preparar_dados_teste(df_nomeado: pd.DataFrame, engine) -> pd.DataFrame:
    """SUBSTITUIR: junta segmento RFM com a variável testada (hoje: desconto)."""
    df_desconto = calcular_desconto_percentual(engine)
    return df_nomeado[["cliente_id", "nome_segmento"]].merge(
        df_desconto[["cliente_id", "percentual_desconto"]], on="cliente_id", how="inner"
    )


# ==========================================
# REAPROVEITÁVEL 100% — não precisa mudar nada abaixo
# ==========================================
def testar_normalidade_por_grupo(
    df: pd.DataFrame, coluna_valor: str, coluna_grupo: str
) -> pd.DataFrame:
    resultados = []
    for grupo, dados in df.groupby(coluna_grupo)[coluna_valor]:
        dados = dados.dropna()
        if len(dados) >= 3:
            estat, p_valor = stats.shapiro(dados)
            resultados.append({
                "segmento": grupo, "n": len(dados),
                "shapiro_p_valor": round(p_valor, 4),
                "normal_a_5pct": p_valor > 0.05,
            })
    return pd.DataFrame(resultados)


def teste_kruskal_wallis(df: pd.DataFrame, coluna_valor: str, coluna_grupo: str) -> dict:
    grupos_validos = [
        dados.dropna().values
        for _, dados in df.groupby(coluna_grupo)[coluna_valor]
        if len(dados.dropna()) >= 3
    ]
    if len(grupos_validos) < 2:
        raise ValueError("Poucos segmentos com dados suficientes (mín. 3) para o teste.")

    estat_h, p_valor = stats.kruskal(*grupos_validos)
    n_total = sum(len(g) for g in grupos_validos)
    k = len(grupos_validos)
    eta_quadrado_aprox = (estat_h - k + 1) / (n_total - k) if n_total > k else float("nan")

    return {
        "estatistica_H": round(estat_h, 4),
        "p_valor": p_valor,
        "significativo_5pct": p_valor < 0.05,
        "n_grupos_testados": k,
        "n_total_observacoes": n_total,
        "eta_quadrado_aprox": round(eta_quadrado_aprox, 4),
    }


def post_hoc_pairwise_mannwhitney(
    df: pd.DataFrame, coluna_valor: str, coluna_grupo: str, metodo_correcao: str = "holm"
) -> pd.DataFrame:
    grupos = sorted(df[coluna_grupo].dropna().unique())
    pares = list(combinations(grupos, 2))
    resultados = []
    for grupo_1, grupo_2 in pares:
        dados_1 = df.loc[df[coluna_grupo] == grupo_1, coluna_valor].dropna()
        dados_2 = df.loc[df[coluna_grupo] == grupo_2, coluna_valor].dropna()
        if len(dados_1) < 3 or len(dados_2) < 3:
            continue
        estat_u, p_valor = stats.mannwhitneyu(dados_1, dados_2, alternative="two-sided")
        resultados.append({
            "grupo_1": grupo_1, "grupo_2": grupo_2,
            "mediana_1": round(dados_1.median(), 2), "mediana_2": round(dados_2.median(), 2),
            "p_valor_bruto": p_valor,
        })

    df_resultados = pd.DataFrame(resultados)
    if df_resultados.empty:
        return df_resultados

    rejeitar, p_ajustado, _, _ = multipletests(df_resultados["p_valor_bruto"], method=metodo_correcao)
    df_resultados["p_valor_ajustado"] = p_ajustado.round(4)
    df_resultados["significativo_5pct"] = rejeitar
    return df_resultados.sort_values("p_valor_ajustado").reset_index(drop=True)
