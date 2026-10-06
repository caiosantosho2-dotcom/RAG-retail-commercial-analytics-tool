"""Segmentação RFM + K-Means: "quem são os clientes".

Decisão que a análise apoia: onde concentrar retenção e reativação. Base: vw_metricas_cliente (janela
atual). Escolhas estatísticas (cada uma com o motivo no retorno e no README):
- R em dias; F e V em log1p (valor tem cauda longa: p99 = 7x a mediana), tudo padronizado;
- K pela regra combinada de config.yaml (silhueta + estabilidade + tamanho), escrita antes de rodar;
- nomes dos segmentos derivados do perfil real, nunca de uma lista fixa por ordem;
- households sem compra na janela ficam fora e são contados (já são perdas, e ignorá-los enviesaria).
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
ACAO = {
    "Fiéis": "proteger com benefícios de fidelidade e acompanhar qualquer queda de frequência",
    "Regulares": "aumentar frequência e gasto por ida (ofertas cruzadas entre categorias)",
    "Ocasionais": "estimular a segunda compra do mês com ofertas de retorno",
    "Esporádicos": "reativar com ofertas de retorno antes que se tornem inativos",
    "Raros": "ações de baixo custo (mailer), sem investimento pesado",
    "Inativos": "tentar recuperação de baixo custo; o valor que ainda geram é pequeno",
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

def carregar_base(cur) -> tuple[pd.DataFrame, list[dict]]:
    """Households da janela atual e as exclusões, cada uma com a contagem e o motivo."""
    df = cur.execute("SELECT household_key, recencia_dias, frequencia, valor, ticket_medio, pct_desconto, "
                     "tem_demografia FROM vw_metricas_cliente WHERE periodo = 'atual' ORDER BY household_key").df()
    for coluna in ("recencia_dias", "frequencia", "valor", "ticket_medio", "pct_desconto"):
        df[coluna] = df[coluna].astype(float)
    total = cur.execute("SELECT COUNT(*) FROM dim_household").fetchone()[0]
    sem_compra = total - len(df)
    nao_positivo = int((df["valor"] <= 0).sum())
    df = df[df["valor"] > 0].reset_index(drop=True)
    excluidos = [
        {"motivo": "sem compra na janela atual (já são perdas; ignorá-los enviesaria o quadro)", "households": int(sem_compra)},
        {"motivo": "valor líquido <= 0 na janela (devolução maior que a compra)", "households": nao_positivo},
    ]
    return df, excluidos


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
        extra = (f" A silhueta pura escolheria K={melhor_silhueta}, que só separa ativos de inativos."
                 if melhor_silhueta != k else "")
        return k, f"Regra combinada ({regra}). Passaram: K={passaram}. Escolhido K={k}.{extra}", True
    elegiveis = tabela[tabela["k"] >= cfg["k_min"]]
    k = int(elegiveis.loc[elegiveis["silhueta"].idxmax(), "k"])
    return k, (f"Nenhum K atendeu a regra combinada ({regra}); usada a maior silhueta entre K >= {cfg['k_min']}: "
               f"K={k}. Os segmentos podem não ser estáveis."), False


# --------------------------------------------------------------------------- nomes e perfil

def nomear(perfil: pd.DataFrame, limite_inativo_dias: float) -> dict[int, str]:
    """Nomes derivados do perfil: recência alta = Inativos; os demais, por valor médio decrescente."""
    nomes: dict[int, str] = {}
    inativos = perfil[perfil["recencia_media_dias"] >= limite_inativo_dias].sort_values("recencia_media_dias", ascending=False)
    for i, seg in enumerate(inativos.index):
        nomes[seg] = "Inativos" if i == 0 else f"Inativos ({i + 1})"
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
    desconto = df.assign(seg=rotulos).groupby("seg").apply(
        lambda t: float((t["pct_desconto"] * t["valor"]).sum() / t["valor"].sum()), include_groups=False)
    perfil["desconto_medio_pct"] = desconto
    return perfil


# --------------------------------------------------------------------------- bloco "e daí?"

def montar_e_dai(segmentos: list[dict], k: int, silhueta: float, estab: dict, regra_cumprida: bool,
                 melhor_silhueta_k: int, n_excluidos: int, total_households: int) -> dict:
    topo = max(segmentos, key=lambda s: s["valor_medio_usd"])
    inativos = next((s for s in segmentos if s["nome"] == "Inativos"), None)
    ari = min(estab["ari_sementes_min"], estab["ari_subamostras_min"])
    conclusao = (f"{topo['nome']} são {_pct(topo['pct_households'])} dos households e fazem {_pct(topo['pct_faturamento'])} "
                 f"do faturamento da janela; {k} segmentos, com estabilidade mínima de {_num(ari)} (ARI).")
    if not regra_cumprida:
        conclusao += " Atenção: a regra de estabilidade não foi atendida, trate os segmentos como indicativos."
    ordem = [s for s in sorted(segmentos, key=lambda s: -s["valor_medio_usd"]) if s["nome"] in ACAO][:3]
    acao = "; ".join(f"{s['nome']}: {ACAO[s['nome']]}" for s in ordem) + "."
    perda_5pct = topo["valor_total_usd"] * 0.05
    impacto = (f"{topo['nome']} geram {_usd(topo['valor_total_usd'])} por janela de 26 semanas; perder 5% deles custa "
               f"cerca de {_usd(perda_5pct)}.")
    if inativos:
        impacto += (f" Os Inativos ({inativos['households']} households) ainda geram {_usd(inativos['valor_total_usd'])} "
                    f"({_pct(inativos['pct_faturamento'], 1)}): recuperá-los move pouco o faturamento.")
    n_hh = _milhar(total_households)
    limitacoes = (
        f"Painel de {n_hh} households frequentes, não o cliente médio do varejista; os segmentos descrevem as últimas "
        f"26 semanas e mudam com a janela. {n_excluidos} households sem compra na janela ficam fora (já são perdas) e "
        f"não aparecem como segmento. Silhueta de {_num(silhueta)}: estrutura moderada, as fronteiras entre segmentos são "
        "graduais. O K vem da regra combinada (silhueta, estabilidade, tamanho)"
        + (f", não só da silhueta, que sozinha escolheria K={melhor_silhueta_k}" if melhor_silhueta_k != k else "")
        + ". Segmento descreve comportamento, não causa.")
    return {"conclusao": conclusao, "acao_recomendada": acao, "impacto_estimado": impacto, "limitacoes": limitacoes}


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
    rotulos = KMeans(k, n_init=cfg["n_init"], random_state=semente).fit_predict(x)
    perfil = montar_perfil(df, rotulos)
    limite_inativo = CFG["metricas"]["cliente_ativo_semanas"] * 7
    nomes = nomear(perfil, limite_inativo)
    validar_nomes(nomes, k)
    perfil["nome"] = pd.Series(nomes)
    perfil = perfil.sort_values("valor_medio_usd", ascending=False)

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
    atribuicao = df[["household_key"]].assign(segmento=pd.Series(rotulos).map(nomes).to_numpy())
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
    """Segmenta os households por RFM com K-Means e devolve o perfil e o tamanho de cada segmento.

    Use para "quem são os clientes", "quais segmentos existem" ou antes de comparar segmentos.
    Se n_clusters não for informado, o K é escolhido pela regra combinada (silhueta, estabilidade e
    tamanho dos segmentos). Nunca devolve a lista de households.
    """
    k, erro = _valido(n_clusters)
    if erro:
        return erro
    try:
        cur = banco.cursor()
    except FileNotFoundError:
        return {"erro": "Nenhuma base carregada.", "sugestao": "Carregue os arquivos de dados antes de analisar."}
    rastro = banco.rastreabilidade(cur)
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
