"""Segmentação RFM + K-Means: "quem são os clientes".

Decisão que a análise apoia: onde concentrar retenção e reativação. Base: vw_metricas_cliente (janela
atual). Escolhas estatísticas (cada uma com o motivo no retorno e no README):
- R em dias; F e V em log1p (valor tem cauda longa: p99 = 7x a mediana), tudo padronizado;
- K pela regra combinada de config.yaml (silhueta + estabilidade + tamanho), escrita antes de rodar;
- nomes dos segmentos derivados do perfil real, nunca de uma lista fixa por ordem;
- households sem compra na janela ficam fora da segmentação e são contados (ignorá-los enviesaria); eles voltam a
  aparecer no CLV, como grupo próprio.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from src.config import CFG
from src.nucleo import banco, cache
from src.nucleo.log import registrar_chamada

LADO = {  # nomes por quantidade de segmentos ativos (ordem: maior valor primeiro)
    1: ["Base ativa"],
    2: ["Fiéis", "Ocasionais"],
    3: ["Fiéis", "Regulares", "Esporádicos"],
    4: ["Fiéis", "Regulares", "Ocasionais", "Esporádicos"],
    5: ["Fiéis", "Regulares", "Ocasionais", "Esporádicos", "Raros"],
}
NOME_PAUSA = "Em pausa"
ACAO = {
    "Fiéis": "proteger com benefícios de fidelidade e acompanhar qualquer queda de frequência",
    "Regulares": "aumentar frequência e gasto por ida (ofertas cruzadas entre categorias)",
    "Ocasionais": "estimular a segunda compra do mês com ofertas de retorno",
    "Esporádicos": "reativar com ofertas de retorno antes que entrem em pausa longa",
    "Raros": "ações de baixo custo (mailer), sem investimento pesado",
    "Em pausa": "reativar com ofertas de retorno; pausa longa não é perda (a aba de CLV mostra quanto o grupo ainda vale)",
    "Base ativa": "acompanhar a evolução da frequência",
}


def _usd(x: float) -> str:
    return "US$ " + f"{x:,.0f}".replace(",", ".")


def _num(x: float, casas: int = 2) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _pct(x: float, casas: int = 0) -> str:
    return _num(x, casas) + "%"


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


# --------------------------------------------------------------------------- dados

COLUNAS_BASE = ["household_key", "recencia_dias", "frequencia", "valor", "ticket_medio", "pct_desconto", "desconto_total", "valor_bruto", "tem_demografia"]


def _finalizar_base(cur, df: pd.DataFrame, janela: str) -> tuple[pd.DataFrame, list[dict]]:
    for coluna in ("recencia_dias", "frequencia", "valor", "ticket_medio", "pct_desconto", "desconto_total", "valor_bruto"):
        df[coluna] = df[coluna].astype(float)
    total = cur.execute("SELECT COUNT(*) FROM dim_household").fetchone()[0]
    sem_compra = total - len(df)
    nao_positivo = int((df["valor"] <= 0).sum())
    df = df[df["valor"] > 0].reset_index(drop=True)
    excluidos = [
        {"motivo": f"sem compra na janela {janela} (pausa total: ficam fora da segmentação, mas entram no CLV como grupo próprio)",
         "households": int(sem_compra)},
        {"motivo": "valor líquido <= 0 na janela (devolução maior que a compra)", "households": nao_positivo},
    ]
    return df, excluidos


def carregar_base(cur, periodo: str = "atual") -> tuple[pd.DataFrame, list[dict]]:
    """Households de uma das duas janelas (atual ou base) lidos de vw_metricas_cliente, com as exclusões."""
    if periodo not in ("atual", "base"):
        raise ValueError("periodo precisa ser 'atual' ou 'base'")
    df = cur.execute(f"SELECT {', '.join(COLUNAS_BASE)} FROM vw_metricas_cliente WHERE periodo = ? "
                     "ORDER BY household_key", [periodo]).df()
    return _finalizar_base(cur, df, periodo)


def base_rfm(cur, semana_ini: int, semana_fim: int) -> tuple[pd.DataFrame, list[dict]]:
    """R, F e V de uma janela qualquer de semanas, a partir de vw_cliente_semana. Nas janelas atual e base o
    resultado é idêntico ao de vw_metricas_cliente (teste), para a definição não divergir."""
    df = cur.execute("""
        WITH fim AS (SELECT MAX(data) AS data_fim FROM dim_data WHERE WEEK_NO = ?),
        s AS (SELECT household_key, SUM(faturamento) AS valor, SUM(cestas) AS frequencia, MAX(ultima_data) AS ultima,
                     SUM(desconto_total) AS desconto, SUM(valor_bruto) AS bruto
              FROM vw_cliente_semana WHERE WEEK_NO BETWEEN ? AND ? GROUP BY household_key)
        SELECT s.household_key, date_diff('day', s.ultima, fim.data_fim) AS recencia_dias, s.frequencia, s.valor,
               CAST(s.valor AS DOUBLE) / NULLIF(s.frequencia, 0) AS ticket_medio,
               100.0 * CAST(s.desconto AS DOUBLE) / NULLIF(CAST(s.bruto AS DOUBLE), 0) AS pct_desconto,
               s.desconto AS desconto_total, s.bruto AS valor_bruto, h.tem_demografia
        FROM s CROSS JOIN fim LEFT JOIN dim_household h ON h.household_key = s.household_key
        ORDER BY s.household_key""", [semana_fim, semana_ini, semana_fim]).df()
    return _finalizar_base(cur, df, f"{semana_ini}-{semana_fim}")


def matriz(df: pd.DataFrame) -> np.ndarray:
    """R em dias, F e V em log1p, padronizados (média 0, desvio 1)."""
    x = np.column_stack([df["recencia_dias"], np.log1p(df["frequencia"]), np.log1p(df["valor"])])
    return StandardScaler().fit_transform(x)


# --------------------------------------------------------------------------- escolha de K

def avaliar_k(x: np.ndarray, ks: list[int], semente: int, cfg: dict | None = None) -> pd.DataFrame:
    """Para cada K: silhueta, inércia (cotovelo), estabilidade (ARI) e tamanho do menor segmento."""
    cfg = cfg or CFG["analises"]["rfm"]
    rng = np.random.default_rng(semente)
    linhas = []
    for k in ks:
        base = KMeans(k, n_init=cfg["n_init"], random_state=semente).fit(x)
        rotulos = base.labels_
        ari_sementes = [adjusted_rand_score(rotulos, KMeans(k, n_init=1, random_state=semente + 1 + s).fit(x).labels_)
                        for s in range(cfg["n_sementes"])]
        ari_sub = []
        for _ in range(cfg["n_subamostras"]):
            idx = rng.choice(len(x), int(cfg["fracao_subamostra"] * len(x)), replace=False)
            sub = KMeans(k, n_init=cfg["n_init"], random_state=int(rng.integers(1_000_000))).fit(x[idx]).labels_
            ari_sub.append(adjusted_rand_score(rotulos[idx], sub))
        tamanhos = np.bincount(rotulos, minlength=k)
        linhas.append({
            "k": k, "silhueta": float(silhouette_score(x, rotulos)), "inercia": float(base.inertia_),
            "ari_sementes_min": float(min(ari_sementes)), "ari_sementes_mediana": float(np.median(ari_sementes)),
            "ari_subamostras_min": float(min(ari_sub)), "ari_subamostras_mediana": float(np.median(ari_sub)),
            "menor_segmento_pct": float(tamanhos.min() / len(x) * 100), "tamanhos": sorted(map(int, tamanhos), reverse=True)})
    return pd.DataFrame(linhas)


def escolher_k(tabela: pd.DataFrame, cfg: dict | None = None) -> tuple[int, str, bool]:
    """Aplica a regra combinada. Devolve (K, descrição do método, regra cumprida)."""
    cfg = cfg or CFG["analises"]["rfm"]
    candidatos = tabela[(tabela["k"] >= cfg["k_min"]) & (tabela["ari_sementes_min"] >= cfg["ari_minimo"])
                        & (tabela["ari_subamostras_min"] >= cfg["ari_minimo"])
                        & (tabela["menor_segmento_pct"] >= cfg["tamanho_minimo_pct"])
                        & (tabela["silhueta"] >= cfg["silhueta_minima"])].sort_values("silhueta", ascending=False)
    melhor_silhueta = int(tabela.loc[tabela["silhueta"].idxmax(), "k"])
    regra = (f"K >= {cfg['k_min']}, ARI mínima >= {_num(cfg['ari_minimo'])} entre sementes e subamostras, menor "
             f"segmento >= {cfg['tamanho_minimo_pct']:.0f}% e silhueta >= {_num(cfg['silhueta_minima'])}; vence a maior silhueta")
    if len(candidatos):
        k = int(candidatos.iloc[0]["k"])
        passaram = ", ".join(str(int(v)) for v in candidatos["k"])
        extra = (f" A silhueta pura escolheria K={melhor_silhueta}, que só separa quem comprou há pouco de quem está em pausa."
                 if melhor_silhueta != k else "")
        return k, f"Regra combinada ({regra}). Passaram: K={passaram}. Escolhido K={k}.{extra}", True
    elegiveis = tabela[tabela["k"] >= cfg["k_min"]]
    k = int(elegiveis.loc[elegiveis["silhueta"].idxmax(), "k"])
    return k, (f"Nenhum K atendeu a regra combinada ({regra}); usada a maior silhueta entre K >= {cfg['k_min']}: "
               f"K={k}. Os segmentos podem não ser estáveis."), False


# --------------------------------------------------------------------------- nomes e perfil

def nomear(perfil: pd.DataFrame, limite_inativo_dias: float) -> dict[int, str]:
    """Nomes derivados do perfil: recência alta (>= limite) = Em pausa; os demais, por valor médio decrescente."""
    nomes: dict[int, str] = {}
    inativos = perfil[perfil["recencia_media_dias"] >= limite_inativo_dias].sort_values("recencia_media_dias", ascending=False)
    for i, seg in enumerate(inativos.index):
        nomes[seg] = NOME_PAUSA if i == 0 else f"{NOME_PAUSA} ({i + 1})"
    ativos = perfil.drop(index=inativos.index).sort_values("valor_medio_usd", ascending=False)
    escada = LADO.get(len(ativos)) or [f"Valor nível {i + 1}" for i in range(len(ativos))]
    for seg, nome in zip(ativos.index, escada):
        nomes[seg] = nome
    return nomes


def validar_nomes(nomes: dict[int, str], k: int) -> None:
    valores = list(nomes.values())
    if len(nomes) != k or any(not v.strip() for v in valores) or len(set(valores)) != len(valores):
        raise ValueError(f"nomes de segmento inválidos: {nomes}")


def montar_perfil(df: pd.DataFrame, rotulos: np.ndarray) -> pd.DataFrame:
    g = df.assign(seg=rotulos).groupby("seg")
    perfil = g.agg(households=("valor", "size"), recencia_media_dias=("recencia_dias", "mean"),
                   frequencia_media=("frequencia", "mean"), valor_medio_usd=("valor", "mean"),
                   ticket_medio_usd=("ticket_medio", "mean"), valor_total=("valor", "sum"))
    perfil["pct_households"] = perfil["households"] / len(df) * 100
    perfil["pct_faturamento"] = perfil["valor_total"] / df["valor"].sum() * 100
    # Definição oficial (views.METRICAS): 100 * soma do desconto / soma do valor bruto, não a média ponderada pelo líquido.
    soma = df.assign(seg=rotulos).groupby("seg")[["desconto_total", "valor_bruto"]].sum()
    perfil["desconto_medio_pct"] = 100 * soma["desconto_total"] / soma["valor_bruto"]
    return perfil


# --------------------------------------------------------------------------- bloco "e daí?"

def montar_e_dai(segmentos: list[dict], k: int, silhueta: float, estab: dict, regra_cumprida: bool,
                 melhor_silhueta_k: int, n_excluidos: int, total_households: int) -> dict:
    topo = max(segmentos, key=lambda s: s["valor_medio_usd"])
    em_pausa = next((s for s in segmentos if s["nome"] == NOME_PAUSA), None)
    ari = min(estab["ari_sementes_min"], estab["ari_subamostras_min"])
    conclusao = (f"{topo['nome']} são {_pct(topo['pct_households'])} dos households e fazem {_pct(topo['pct_faturamento'])} "
                 "do faturamento.")
    evidencia = (f"Os {topo['nome']} ({_milhar(topo['households'])} households) geram {_usd(topo['valor_total_usd'])} em 26 semanas.")
    if em_pausa:
        evidencia += (f" Os {NOME_PAUSA} ({_milhar(em_pausa['households'])} households) fazem {_pct(em_pausa['pct_faturamento'], 1)} "
                      "do faturamento.")
    detalhes = [f"{k} segmentos pela regra combinada (silhueta {_num(silhueta)}); estabilidade mínima de {_num(ari)} (ARI, entre "
                "sementes e subamostras)."]
    if not regra_cumprida:
        evidencia = "Atenção: a regra de estabilidade não foi atendida, trate os segmentos como indicativos. " + evidencia
        detalhes.append("A regra de estabilidade (ARI mínimo) não foi atendida.")
    ordem = [s for s in sorted(segmentos, key=lambda s: -s["valor_medio_usd"]) if s["nome"] in ACAO][:3]
    acao = "; ".join(f"{s['nome']}: {ACAO[s['nome']]}" for s in ordem) + "."
    perda_5pct = topo["valor_total_usd"] * 0.05
    impacto = (f"{topo['nome']} geram {_usd(topo['valor_total_usd'])} por janela de 26 semanas; perder 5% deles custa "
               f"cerca de {_usd(perda_5pct)}.")
    if em_pausa:
        impacto += (f" Os {NOME_PAUSA} ({em_pausa['households']} households) geram hoje {_usd(em_pausa['valor_total_usd'])} "
                    f"({_pct(em_pausa['pct_faturamento'], 1)}) da janela; a aba de CLV mostra quanto voltam a valer.")
    n_hh = _milhar(total_households)
    limitacoes = (
        f"Painel de {n_hh} households frequentes, não o cliente médio do varejista; os segmentos descrevem as últimas "
        f"26 semanas e mudam com a janela. {n_excluidos} households sem compra na janela ficam fora da segmentação (pausa total; entram no CLV como grupo próprio) e "
        f"não aparecem como segmento. Silhueta de {_num(silhueta)}: estrutura moderada, as fronteiras entre segmentos são "
        "graduais. O K vem da regra combinada (silhueta, estabilidade, tamanho)"
        + (f", não só da silhueta, que sozinha escolheria K={melhor_silhueta_k}" if melhor_silhueta_k != k else "")
        + ". Segmento descreve comportamento, não causa.")
    return {"conclusao": conclusao, "evidencia": evidencia, "acao_recomendada": acao, "impacto_estimado": impacto,
            "limitacoes": limitacoes, "detalhes_tecnicos": detalhes}


# --------------------------------------------------------------------------- ajuste dos segmentos

def ajustar_segmentos(df: pd.DataFrame, k: int, semente: int | None = None, n_init: int | None = None):
    """K-Means com K fixo, perfil e nomes derivados do perfil. Devolve (nome do segmento por linha de df, perfil)."""
    cfg = CFG["analises"]["rfm"]
    semente = CFG["semente"] if semente is None else semente
    rotulos = KMeans(k, n_init=n_init or cfg["n_init"], random_state=semente).fit_predict(matriz(df))
    perfil = montar_perfil(df, rotulos)
    nomes = nomear(perfil, CFG["metricas"]["cliente_ativo_semanas"] * 7)
    validar_nomes(nomes, k)
    perfil["nome"] = pd.Series(nomes)
    return pd.Series(rotulos).map(nomes).to_numpy(), perfil.sort_values("valor_medio_usd", ascending=False)


# --------------------------------------------------------------------------- análise

def _calcular(cur, n_clusters: int | None) -> tuple[dict, pd.DataFrame]:
    cfg = CFG["analises"]["rfm"]
    semente = CFG["semente"]
    df, excluidos = carregar_base(cur)
    total_households = cur.execute("SELECT COUNT(*) FROM dim_household").fetchone()[0]
    ks = sorted(set(cfg["k_avaliados"]) | ({n_clusters} if n_clusters else set()))
    x = matriz(df)
    tabela = avaliar_k(x, ks, semente, cfg)
    melhor_silhueta_k = int(tabela.loc[tabela["silhueta"].idxmax(), "k"])
    if n_clusters:
        k, metodo, cumprida = n_clusters, f"K={n_clusters} informado pelo usuário (a regra de escolha não foi aplicada).", True
    else:
        k, metodo, cumprida = escolher_k(tabela, cfg)
    linha = tabela[tabela["k"] == k].iloc[0]
    nome_por_linha, perfil = ajustar_segmentos(df, k, semente, cfg["n_init"])

    segmentos = [{
        "nome": r["nome"], "households": int(r["households"]), "pct_households": round(float(r["pct_households"]), 1),
        "recencia_media_dias": round(float(r["recencia_media_dias"]), 1), "frequencia_media": round(float(r["frequencia_media"]), 1),
        "valor_medio_usd": round(float(r["valor_medio_usd"]), 2), "valor_total_usd": round(float(r["valor_total"]), 2),
        "ticket_medio_usd": round(float(r["ticket_medio_usd"]), 2), "pct_faturamento": round(float(r["pct_faturamento"]), 1),
        "desconto_medio_pct": round(float(r["desconto_medio_pct"]), 1)} for _, r in perfil.iterrows()]
    estab = {"ari_sementes_min": round(float(linha["ari_sementes_min"]), 3), "ari_sementes_mediana": round(float(linha["ari_sementes_mediana"]), 3),
             "ari_subamostras_min": round(float(linha["ari_subamostras_min"]), 3), "ari_subamostras_mediana": round(float(linha["ari_subamostras_mediana"]), 3),
             "sementes": cfg["n_sementes"], "subamostras": cfg["n_subamostras"], "fracao_subamostra": cfg["fracao_subamostra"]}
    n_excluidos = sum(e["households"] for e in excluidos)
    retorno = {
        "k_usado": int(k), "metodo_escolha_k": metodo, "regra_k_cumprida": bool(cumprida),
        "silhueta": round(float(linha["silhueta"]), 3), "segmentos": segmentos, "estabilidade": estab,
        "avaliacao_k": [{**{c: (round(v, 3) if isinstance(v, float) else v) for c, v in r.items()}}
                        for r in tabela.to_dict("records")],
        "preparacao": "recência em dias; frequência e valor em log1p (cauda longa); padronizados; K-Means com semente fixa",
        "excluidos": excluidos,
        "e_dai": montar_e_dai(segmentos, int(k), float(linha["silhueta"]), estab, cumprida, melhor_silhueta_k,
                              n_excluidos, total_households)}
    atribuicao = df[["household_key"]].assign(segmento=nome_por_linha)
    return retorno, atribuicao


def _valido(n_clusters) -> tuple[int | None, dict | None]:
    if n_clusters is None:
        return None, None
    try:
        k = int(n_clusters)
    except (TypeError, ValueError):
        k = 0
    if not 2 <= k <= 8:
        return None, {"erro": "n_clusters precisa ser um inteiro entre 2 e 8.", "sugestao": "Omita n_clusters para o K ser escolhido pela regra combinada."}
    return k, None


def _resultado(cur, n_clusters: int | None) -> tuple[dict, pd.DataFrame]:
    chave = cache.chave(cur, "rfm", n_clusters=n_clusters, cfg=CFG["analises"]["rfm"], semente=CFG["semente"],
                        ativo=CFG["metricas"]["cliente_ativo_semanas"], janela=CFG["janela"])
    return cache.obter(chave, lambda: _calcular(cur, n_clusters))


@registrar_chamada("segmentar_clientes")
def segmentar_clientes(n_clusters: int | None = None) -> dict:
    """Segmenta os households por RFM com K-Means e devolve o perfil, o tamanho e a parcela do faturamento (pct_faturamento) de cada segmento.

    Use para "quem são os clientes", "quais segmentos existem", "que parcela do faturamento vem de cada grupo" ou
    antes de comparar segmentos.
    Se n_clusters não for informado, o K é escolhido pela regra combinada (silhueta, estabilidade e
    tamanho dos segmentos). Nunca devolve a lista de households.
    """
    k, erro = _valido(n_clusters)
    try:
        cur = banco.cursor()
    except FileNotFoundError:
        return {"erro": "Nenhuma base carregada.", "sugestao": "Rode `python baixar_dados.py` e `python -m src.etl` (ou carregue os arquivos exportados do BI no app)."}
    rastro = banco.rastreabilidade(cur)
    if erro:
        return {**erro, **rastro}      # a spec pede versao_base e janela em todo retorno, inclusive no erro
    try:
        retorno, _ = _resultado(cur, k)
    except Exception as e:   # base pequena, janela vazia etc.: mensagem curta, sem despejo técnico
        return {"erro": f"Não foi possível segmentar os clientes ({type(e).__name__}).",
                "sugestao": "Confira se a base tem compras na janela atual e households suficientes.", **rastro}
    return {**retorno, **rastro}


def segmentos_por_household(cur, n_clusters: int | None = None) -> pd.DataFrame:
    """Uso interno (CLV, churn, teste de desconto): household_key -> segmento. Não é uma ferramenta."""
    return _resultado(cur, n_clusters)[1]


# --------------------------------------------------------------------------- coorte

def coorte_retencao(cur) -> dict:
    """Retenção por coorte de entrada (apoio ao RFM). Entrada = primeira semana com compra no histórico.

    Blocos de `bloco_semanas` semanas; só aparecem blocos completos e coortes com pelo menos
    `coorte_minima_households` households (as demais são contadas em `omitidas`). A entrada no painel acontece
    quase toda nas primeiras semanas: entrada no painel não é cliente novo.
    """
    cfg = CFG["analises"]["coorte"]
    tam, minimo = cfg["bloco_semanas"], cfg["coorte_minima_households"]
    chave = cache.chave(cur, "coorte", cfg=cfg)

    def calcular():
        ultima = cur.execute("SELECT semana_fim_atual FROM vw_janela").fetchone()[0]
        d = cur.execute("SELECT household_key AS h, WEEK_NO AS s FROM vw_cliente_semana").df()
        d["bloco"] = (d["s"] - 1) // tam
        coorte = d.groupby("h")["s"].min().sub(1).floordiv(tam)
        ativos = d.groupby("h")["bloco"].agg(set)
        completos = ultima // tam            # blocos 0..completos-1 terminam em ou antes da última semana
        saida, omitidas = [], 0
        for c in sorted(coorte.unique()):
            membros = coorte[coorte == c].index
            if len(membros) < minimo or (c + 1) * tam > ultima:
                omitidas += len(membros)
                continue
            retencao = {lag: round(float(np.mean([(int(c) + lag) in ativos[h] for h in membros])) * 100, 1)
                        for lag in range(1, completos - int(c))}
            saida.append({"coorte": f"Sem. {c * tam + 1}–{(c + 1) * tam}", "households": int(len(membros)),
                          "retencao_pct": retencao})
        entrou_cedo = float((coorte.index.size - omitidas) / coorte.index.size * 100)
        return {"coortes": saida, "bloco_semanas": tam, "omitidas": {"households": int(omitidas), "motivo": f"coortes com menos de {minimo} households"},
                "limitacao": (f"Entrada = primeira compra no histórico. {_num(entrou_cedo, 1)}% dos households entram nas primeiras "
                              f"semanas (painel em formação), então a entrada não marca cliente novo e a retenção por coorte mostra, "
                              f"sobretudo, a constância do painel. {omitidas} households de entrada tardia ficam fora por serem "
                              f"poucos demais para uma coorte.")}

    return cache.obter(chave, calcular)
