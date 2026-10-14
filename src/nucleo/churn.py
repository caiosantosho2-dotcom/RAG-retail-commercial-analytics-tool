"""Risco de pausa longa ("churn" de 8 semanas): "quem vai parar de comprar".

Decisão que a análise apoia: quem abordar com reativação e quem deixar em paz. Escolhas (cada uma com o motivo no
retorno e no README):
- definição: sem compra nas próximas `horizonte_semanas` (8), entre quem comprou nas últimas 8 e tem pelo menos 16 semanas
  de histórico; é pausa, não saída (72% a 84% de quem pausa volta em 18 semanas), e o retorno diz isso;
- validação temporal: treina em fotos antigas, escolhe o limiar numa foto seguinte e testa em duas fotos finais, com
  rótulos que não se sobrepõem; nunca sorteio de linhas, que vaza o futuro;
- regra simples ("sem compra há k semanas") sempre reportada ao lado do modelo; se o modelo não ganhar, o "e daí?" diz;
- logística padronizada com poucas variáveis, para o sinal de cada coeficiente fazer sentido de negócio.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score
from sklearn.preprocessing import StandardScaler

from src.config import CFG
from src.nucleo import banco, cache, rfm
from src.nucleo.log import registrar_chamada

VARIAVEIS = ["recencia_semanas", "log_compras_8s", "log_valor_26s", "semanas_com_compra_26s", "maior_pausa_26s"]
LEITURA = {
    "recencia_semanas": "semanas desde a última compra",
    "log_compras_8s": "compras nas últimas 8 semanas",
    "log_valor_26s": "gasto nas últimas 26 semanas",
    "semanas_com_compra_26s": "semanas com compra nas últimas 26 (constância)",
    "maior_pausa_26s": "maior pausa seguida nas últimas 26 semanas",
}


class ChurnIndisponivel(Exception):
    def __init__(self, erro: str, sugestao: str):
        super().__init__(erro)
        self.erro, self.sugestao = erro, sugestao


def _pct(x: float, casas: int = 0) -> str:
    """Número em português: vírgula decimal."""
    return f"{x:.{casas}f}".replace(".", ",")


def _milhar(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def _usd(x: float) -> str:
    return "US$ " + f"{x:,.0f}".replace(",", ".")


def _sem_acento(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower().strip()


# --------------------------------------------------------------------------- painel e fotos

@dataclass
class Painel:
    """Compras e gasto por household e semana (colunas 0..fim; a semana 0 não existe e fica zerada)."""
    ids: np.ndarray
    compras: np.ndarray
    valor: np.ndarray
    fim: int


def carregar_painel(cur, fim: int) -> Painel:
    ids = cur.execute("SELECT household_key FROM dim_household ORDER BY household_key").df()["household_key"].to_numpy()
    d = cur.execute("SELECT household_key AS h, WEEK_NO AS s, cestas, faturamento AS v FROM vw_cliente_semana WHERE WEEK_NO <= ?", [fim]).df()
    compras, valor = np.zeros((len(ids), fim + 1)), np.zeros((len(ids), fim + 1))
    linha = np.searchsorted(ids, d["h"].to_numpy())
    compras[linha, d["s"].to_numpy()] = d["cestas"].astype(float).to_numpy()
    valor[linha, d["s"].to_numpy()] = d["v"].astype(float).to_numpy()
    return Painel(ids, compras, valor, fim)


def _maior_pausa(ativo: np.ndarray) -> np.ndarray:
    """Maior sequência de semanas sem compra em cada linha."""
    seguido, maior = np.zeros(len(ativo)), np.zeros(len(ativo))
    for j in range(ativo.shape[1]):
        seguido = np.where(ativo[:, j], 0, seguido + 1)
        maior = np.maximum(maior, seguido)
    return maior


def fotografar(p: Painel, T: int, cfg: dict | None = None, com_rotulo: bool = True):
    """Foto na semana T: população, variáveis e (opcional) rótulo. Usa só semanas <= T nas variáveis e na população;
    o rótulo olha T+1..T+horizonte. Devolve (X, y, household_key, recência)."""
    cfg = cfg or CFG["analises"]["churn"]
    recente, h, base = CFG["metricas"]["cliente_ativo_semanas"], cfg["horizonte_semanas"], cfg["janela_comportamento_semanas"]
    ativo = p.compras[:, : T + 1] > 0
    existe = ativo.any(axis=1)
    ultima = np.where(existe, T - np.argmax(ativo[:, ::-1], axis=1), -1)
    primeira = np.where(existe, np.argmax(ativo, axis=1), 10_000)
    populacao = (ultima >= T - recente + 1) & (T - primeira >= cfg["historico_minimo_semanas"] - 1)
    ini = max(1, T - base + 1)
    janela = ativo[:, ini : T + 1]
    X = np.column_stack([
        T - ultima,
        np.log1p(p.compras[:, T - recente + 1 : T + 1].sum(axis=1)),
        np.log1p(p.valor[:, ini : T + 1].sum(axis=1)),
        janela.sum(axis=1),
        _maior_pausa(janela),
    ]).astype(float)
    y = None
    if com_rotulo:
        y = (p.compras[:, T + 1 : T + h + 1].sum(axis=1) == 0).astype(int)[populacao]
    return X[populacao], y, p.ids[populacao], (T - ultima)[populacao]


def fotos_do_plano(fim_atual: int, cfg: dict | None = None) -> dict:
    """Semanas T de treino, validação e teste, a partir do fim da janela atual. Falha com mensagem clara se o plano
    não cabe nos dados (poucas semanas, rótulo além do fim)."""
    cfg = cfg or CFG["analises"]["churn"]
    h, base = cfg["horizonte_semanas"], cfg["janela_comportamento_semanas"]
    treino = list(range(fim_atual - cfg["treino_inicio_antes_do_fim"], fim_atual - cfg["treino_fim_antes_do_fim"] + 1, cfg["treino_passo_semanas"]))
    validacao = fim_atual - cfg["validacao_antes_do_fim"]
    teste = [fim_atual - d for d in cfg["teste_antes_do_fim"]]
    todas = treino + [validacao] + teste
    if not treino or min(todas) < base:
        raise ChurnIndisponivel("A base não tem semanas suficientes de histórico para treinar o modelo de churn.",
                                f"São necessárias ao menos {base + cfg['historico_minimo_semanas']} semanas anteriores à primeira foto de treino.")
    if max(todas) + h > fim_atual:
        raise ChurnIndisponivel("O último rótulo de teste passa do fim dos dados.", "Ajuste o plano de fotos em analises.churn do config.yaml.")
    if max(treino) + h > validacao:
        raise ChurnIndisponivel("Os rótulos de treino invadem a foto de validação.", "Afaste a validação do treino em analises.churn.")
    if validacao + h > min(teste):
        raise ChurnIndisponivel("Os rótulos da validação invadem a primeira foto de teste.", "Afaste o teste da validação em analises.churn.")
    if sorted(teste)[0] + h > sorted(teste)[1]:
        raise ChurnIndisponivel("Os rótulos das fotos de teste se sobrepõem.", "Afaste as fotos de teste em analises.churn.")
    return {"treino": treino, "validacao": validacao, "teste": sorted(teste)}


# --------------------------------------------------------------------------- limiar, regra simples, métricas

def escolher_limiar(y: np.ndarray, prob: np.ndarray) -> float:
    """Limiar de maior F1 na validação (empate: o menor). Nunca olha o teste."""
    grade = np.round(np.arange(0.01, 0.80, 0.005), 3)
    f1 = [precision_recall_fscore_support(y, prob >= t, average="binary", zero_division=0)[2] for t in grade]
    return float(grade[int(np.argmax(f1))])


def escolher_k(recencia: np.ndarray, y: np.ndarray, k_max: int) -> int:
    """Regra simples "sem compra há k semanas ou mais": k de maior F1 no treino."""
    ks = list(range(1, k_max + 1))
    f1 = [precision_recall_fscore_support(y, recencia >= k, average="binary", zero_division=0)[2] for k in ks]
    return ks[int(np.argmax(f1))]


def metricas_binarias(y: np.ndarray, predito: np.ndarray) -> dict:
    p, r, f, _ = precision_recall_fscore_support(y, predito, average="binary", zero_division=0)
    tn, fp, fn, tp = confusion_matrix(y, predito, labels=[0, 1]).ravel()
    return {"precisao": float(p), "recall": float(r), "f1": float(f), "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
            "alertas": int(fp + tp)}


def bootstrap_auc(y: np.ndarray, prob: np.ndarray, base: np.ndarray, hh: np.ndarray, n_boot: int, nivel: float, semente: int) -> dict:
    """IC por household (as duas fotos de teste repetem households, então reamostrar linhas subestimaria a incerteza)."""
    rng = np.random.default_rng(semente)
    grupos = {h: np.flatnonzero(hh == h) for h in np.unique(hh)}
    ids = np.array(list(grupos))
    am, ab, dif = [], [], []
    for _ in range(n_boot):
        sorteados = rng.choice(ids, len(ids))
        ix = np.concatenate([grupos[h] for h in sorteados])
        if y[ix].min() == y[ix].max():
            continue
        a, b = roc_auc_score(y[ix], prob[ix]), roc_auc_score(y[ix], base[ix])
        am.append(a), ab.append(b), dif.append(a - b)
    q = [(1 - nivel) / 2 * 100, (1 + nivel) / 2 * 100]
    ic = lambda v: [float(x) for x in np.percentile(v, q)]
    return {"auc_modelo_ic": ic(am), "auc_baseline_ic": ic(ab), "diferenca_auc": float(np.mean(dif)), "diferenca_auc_ic": ic(dif)}


def calibracao_por_decil(y: np.ndarray, prob: np.ndarray) -> list[dict]:
    d = pd.DataFrame({"p": prob, "y": y})
    d["decil"] = pd.qcut(d["p"].rank(method="first"), 10, labels=False)
    g = d.groupby("decil").agg(households=("y", "size"), previsto=("p", "mean"), observado=("y", "mean")).reset_index()
    return [{"decil": int(r.decil) + 1, "households": int(r.households), "previsto_pct": 100 * float(r.previsto),
             "observado_pct": 100 * float(r.observado)} for r in g.itertuples()]


# --------------------------------------------------------------------------- texto

def _fatores(modelo: LogisticRegression, escala: StandardScaler) -> list[dict]:
    saida = []
    for nome, coef, dp in zip(VARIAVEIS, modelo.coef_[0], escala.scale_):
        saida.append({"variavel": nome, "descricao": LEITURA[nome], "coeficiente_padronizado": float(coef),
                      "odds_ratio_por_dp": float(np.exp(coef)),
                      "efeito": "reduz o risco" if coef < 0 else "aumenta o risco",
                      "leitura": f"{LEITURA[nome]}: {'quanto maior, menor' if coef < 0 else 'quanto maior, maior'} o risco de pausa "
                                 f"(odds x{_pct(float(np.exp(coef)), 2)} por desvio-padrão)"})
    return sorted(saida, key=lambda f: -abs(f["coeficiente_padronizado"]))


def montar_e_dai(r: dict) -> dict:
    h = r["horizonte_semanas"]
    segs = [s for s in r["risco_por_segmento"] if s["households"] > 0]
    topo = max(segs, key=lambda s: s["pausas_esperadas"])
    maior_valor = max(segs, key=lambda s: s["valor_em_risco_usd"])
    menor = min(segs, key=lambda s: s["risco_medio_pct"])
    total_esperado = sum(s["pausas_esperadas"] for s in segs)
    total_valor = sum(s["valor_em_risco_usd"] for s in segs)
    alertas_hoje = sum(s["alertas"] for s in segs)
    pop = sum(s["households"] for s in segs)
    m, b = r["modelo"], r["baseline"]
    ganha = r["diferenca_auc_ic"][0] > 0
    pct_topo = 100 * topo["pausas_esperadas"] / total_esperado
    conclusao = (f"Cerca de {round(total_esperado)} clientes ativos devem passar {h} semanas sem comprar; "
                 f"{_pct(pct_topo)}% são {topo['nome']}.")
    evidencia = (f"Dos {_milhar(pop)} households ativos avaliados, o risco médio é de {_pct(topo['risco_medio_pct'], 1)}% nos "
                 f"{topo['nome']}, contra {_pct(menor['risco_medio_pct'], 1)}% nos {menor['nome']}.")
    lo, hi = r["diferenca_auc_ic"]
    detalhes = [f"AUC do modelo {_pct(m['auc'], 2)} contra {_pct(b['auc'], 2)} da regra simples de recência; diferença com IC de 95% "
                f"de {_pct(lo, 3)} a {_pct(hi, 3)} (por household, no teste).",
                f"Limiar de alerta {_pct(r['limiar'], 2)}: precisão de {_pct(100 * m['precisao'])}% e recall de {_pct(100 * m['recall'])}% "
                "no teste."]
    if ganha:
        detalhes.insert(0, "O modelo ordena melhor que a regra de recência.")
    else:
        evidencia += (" Atenção: o modelo não superou a regra simples de recência (diferença dentro da margem de erro): "
                      "use a regra, que é mais simples.")
    onde = (f"as pausas se concentram nos {topo['nome']}, mas o dinheiro em risco está nos {maior_valor['nome']} "
            f"({_pct(100 * maior_valor['valor_em_risco_usd'] / total_valor)}% do valor em risco)"
            if maior_valor["nome"] != topo["nome"] else f"{topo['nome']} concentram as pausas e o valor em risco")
    acao = (f"Fazer reativação seletiva nos {_milhar(alertas_hoje)} households em alerta hoje (limiar {_pct(r['limiar'], 2)}): {onde}. "
            f"Cada alerta acerta {_pct(100 * m['precisao'])}% das vezes e o conjunto pega {_pct(100 * m['recall'])}% das pausas. "
            f"Não gastar com {menor['nome']} (risco de {_pct(menor['risco_medio_pct'], 1)}%).")
    ret = r["retorno_apos_pausa"]
    impacto = (f"Faturamento em risco nas próximas {h} semanas ≈ {_usd(r['valor_em_risco_usd'])}, calculado como risco x gasto semanal x {h}, "
               f"ou {_pct(r['valor_em_risco_pct_do_periodo'], 1)}% do faturamento esperado do período. Como {_pct(ret['taxa_pct'])}% de quem pausa "
               f"volta em até {ret['janela_semanas']} semanas, a perda efetiva tende a ser menor.")
    ja = r["ja_em_pausa"]["households"]
    limitacoes = (f"Pausa não é saída: {_pct(ret['taxa_pct'])}% voltam em {ret['janela_semanas']} semanas, então o nome \"churn\" vale como pausa longa de "
                  f"{h} semanas. A população é quem comprou nas últimas {CFG['metricas']['cliente_ativo_semanas']} semanas e tem ao menos "
                  f"{CFG['analises']['churn']['historico_minimo_semanas']} semanas de histórico; {ja} households já estão em pausa e ficam fora da previsão. "
                  f"Precisão modesta: de cada 100 alertas, {round(100 * m['precisao'])} se confirmam. O modelo usa só comportamento de compra e mostra "
                  "associação, não causa. O treino repete households em várias fotos (o intervalo é por household no teste). "
                  "Os segmentos mudam com a janela.")
    return {"conclusao": conclusao, "evidencia": evidencia, "acao_recomendada": acao, "impacto_estimado": impacto,
            "limitacoes": limitacoes, "detalhes_tecnicos": detalhes}


# --------------------------------------------------------------------------- análise

def _calcular(cur) -> dict:
    cfg = CFG["analises"]["churn"]
    semente = CFG["semente"]
    j = cur.execute("SELECT semana_fim_atual FROM vw_janela").fetchone()
    if j is None or j[0] is None:
        raise ChurnIndisponivel("A janela de análise não pôde ser calculada.", "Confira se a base tem semanas completas.")
    fim = int(j[0])
    plano = fotos_do_plano(fim, cfg)
    painel = carregar_painel(cur, fim)
    h = cfg["horizonte_semanas"]

    treino = [fotografar(painel, T, cfg) for T in plano["treino"]]
    X_tr = np.vstack([f[0] for f in treino])
    y_tr = np.concatenate([f[1] for f in treino])
    rec_tr = np.concatenate([f[3] for f in treino])
    escala = StandardScaler().fit(X_tr)
    modelo = LogisticRegression(C=cfg["l2_c"], max_iter=2000, random_state=semente).fit(escala.transform(X_tr), y_tr)

    X_v, y_v, _, rec_v = fotografar(painel, plano["validacao"], cfg)
    limiar = escolher_limiar(y_v, modelo.predict_proba(escala.transform(X_v))[:, 1])
    k = escolher_k(rec_tr, y_tr, CFG["metricas"]["cliente_ativo_semanas"] - 1)

    teste = [fotografar(painel, T, cfg) for T in plano["teste"]]
    X_t = np.vstack([f[0] for f in teste])
    y_t = np.concatenate([f[1] for f in teste])
    hh_t = np.concatenate([f[2] for f in teste])
    rec_t = np.concatenate([f[3] for f in teste])
    prob_t = modelo.predict_proba(escala.transform(X_t))[:, 1]

    boot = bootstrap_auc(y_t, prob_t, rec_t.astype(float), hh_t, cfg["n_bootstrap"], cfg["nivel_ic"], semente)
    m = {"auc": float(roc_auc_score(y_t, prob_t)), "auc_pr": float(average_precision_score(y_t, prob_t)),
         **metricas_binarias(y_t, prob_t >= limiar)}
    b = {"auc": float(roc_auc_score(y_t, rec_t)), "auc_pr": float(average_precision_score(y_t, rec_t)),
         **metricas_binarias(y_t, rec_t >= k)}

    grade = sorted({0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, limiar})
    curva = [{"limiar": t, **{c: v for c, v in metricas_binarias(y_t, prob_t >= t).items() if c in ("precisao", "recall", "alertas")},
              "escolhido": t == limiar} for t in grade]

    # retorno de quem pausou: fotos de treino em que as semanas seguintes à pausa foram observadas
    jan_ret = cfg["retorno_janela_semanas"]
    taxas, voltaram, pausas = [], 0, 0
    for T, (_, y, hh, _) in zip(plano["treino"], treino):
        linhas = np.searchsorted(painel.ids, hh[y == 1])
        if T + h + jan_ret > fim or not len(linhas):
            continue
        voltou = painel.compras[linhas, T + h + 1 : T + h + jan_ret + 1].sum(axis=1) > 0
        taxas.append(100 * float(voltou.mean()))
        voltaram += int(voltou.sum())
        pausas += len(voltou)
    retorno = {"janela_semanas": jan_ret, "taxa_pct": 100 * voltaram / pausas if pausas else 0.0, "pausas_observadas": int(pausas),
               "minimo_por_foto_pct": min(taxas) if taxas else 0.0, "maximo_por_foto_pct": max(taxas) if taxas else 0.0}

    # risco por segmento RFM na última semana (sem rótulo: é o futuro)
    X_f, _, hh_f, _ = fotografar(painel, fim, cfg, com_rotulo=False)
    prob_f = modelo.predict_proba(escala.transform(X_f))[:, 1]
    gasto_semanal = np.expm1(X_f[:, 2]) / cfg["janela_comportamento_semanas"]
    atrib = rfm.segmentos_por_household(cur).set_index("household_key")["segmento"]
    seg = atrib.reindex(hh_f).fillna("Fora do RFM").to_numpy()
    d = pd.DataFrame({"seg": seg, "p": prob_f, "alerta": prob_f >= limiar, "risco_usd": prob_f * gasto_semanal * h})
    ordem = [s["nome"] for s in rfm._resultado(cur, None)[0]["segmentos"]]
    risco = []
    for nome in [n for n in ordem if n in set(d["seg"])] + [n for n in d["seg"].unique() if n not in ordem]:
        g = d[d["seg"] == nome]
        risco.append({"nome": nome, "households": int(len(g)), "risco_medio_pct": 100 * float(g["p"].mean()),
                      "pausas_esperadas": float(g["p"].sum()), "alertas": int(g["alerta"].sum()), "valor_em_risco_usd": float(g["risco_usd"].sum())})
    fora = painel.ids[~np.isin(painel.ids, hh_f)]
    ja_por_seg = pd.Series(atrib.reindex(fora).fillna("Sem compra na janela")).value_counts().to_dict()
    gasto_periodo = float(painel.valor[:, fim - cfg["janela_comportamento_semanas"] + 1 : fim + 1].sum() / cfg["janela_comportamento_semanas"] * h)

    r = {
        "definicao_churn": (f"Sem compra nas próximas {h} semanas (pausa longa), entre quem comprou nas últimas "
                            f"{CFG['metricas']['cliente_ativo_semanas']} semanas e tem ao menos {cfg['historico_minimo_semanas']} semanas de histórico. "
                            f"{h} semanas = 56 dias, o mesmo limite de \"cliente ativo\" e de \"Em pausa\"."),
        "horizonte_semanas": h,
        "periodo_treino": f"fotos nas semanas {plano['treino'][0]} a {plano['treino'][-1]} (a cada {cfg['treino_passo_semanas']}); rótulos até a semana {plano['treino'][-1] + h}",
        "periodo_validacao": f"foto na semana {plano['validacao']} (rótulos {plano['validacao'] + 1} a {plano['validacao'] + h}); define o limiar",
        "periodo_teste": f"fotos nas semanas {plano['teste'][0]} e {plano['teste'][1]} (rótulos {plano['teste'][0] + 1}-{plano['teste'][0] + h} e "
                         f"{plano['teste'][1] + 1}-{plano['teste'][1] + h})",
        "linhas": {"treino": int(len(y_tr)), "teste": int(len(y_t))},
        "prevalencia_pct": {"treino": 100 * float(y_tr.mean()), "teste": 100 * float(y_t.mean())},
        "modelo": m, "baseline": b, **boot, "limiar": limiar, "k_baseline": k,
        "baseline_descricao": f"Regra simples: sem compra há {k} semanas ou mais = vai pausar (k escolhido no treino)",
        "auc_modelo": m["auc"], "auc_baseline": b["auc"],
        "precisao_recall_classe_churn": {"modelo": {"precisao": m["precisao"], "recall": m["recall"]},
                                         "baseline": {"precisao": b["precisao"], "recall": b["recall"]}},
        "matriz_confusao": {"modelo": {k_: m[k_] for k_ in ("tn", "fp", "fn", "tp")}, "baseline": {k_: b[k_] for k_ in ("tn", "fp", "fn", "tp")}},
        "curva_limiar": curva, "calibracao": calibracao_por_decil(y_t, prob_t), "principais_fatores": _fatores(modelo, escala),
        "risco_por_segmento": risco, "ja_em_pausa": {"households": int(len(fora)), "por_segmento": {k_: int(v) for k_, v in ja_por_seg.items()}},
        "retorno_apos_pausa": retorno, "valor_em_risco_usd": float(d["risco_usd"].sum()),
        "valor_em_risco_pct_do_periodo": 100 * float(d["risco_usd"].sum()) / gasto_periodo if gasto_periodo else 0.0,
        "populacao_prevista": int(len(hh_f)), "variaveis": VARIAVEIS,
    }
    return _arredondar(r) | {"e_dai": montar_e_dai(_arredondar(r))}


def _arredondar(o):
    if isinstance(o, dict):
        return {k: _arredondar(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_arredondar(v) for v in o]
    if isinstance(o, float):
        return None if np.isnan(o) else round(o, 4)
    return o


@registrar_chamada("prever_churn")
def prever_churn(segmento: str | None = None) -> dict:
    """Mostra o risco de churn por segmento e o desempenho do modelo contra uma regra simples.

    Use para "quem vai parar de comprar" ou "qual segmento está em risco". Churn aqui é pausa longa (8 semanas sem comprar),
    não saída definitiva. Passe `segmento` para filtrar um grupo (os totais continuam os da base inteira).
    """
    try:
        cur = banco.cursor()
    except FileNotFoundError:
        return {"erro": "Nenhuma base carregada.", "sugestao": "Carregue os arquivos de dados antes de analisar."}
    rastro = banco.rastreabilidade(cur)
    try:
        chave = cache.chave(cur, "churn", cfg=CFG["analises"]["churn"], rfm=CFG["analises"]["rfm"], semente=CFG["semente"],
                            ativo=CFG["metricas"]["cliente_ativo_semanas"], janela=CFG["janela"])
        retorno = cache.obter(chave, lambda: _calcular(cur))
    except ChurnIndisponivel as e:
        return {"erro": e.erro, "sugestao": e.sugestao, **rastro}
    except Exception as e:
        return {"erro": f"Não foi possível calcular o risco de churn ({type(e).__name__}).",
                "sugestao": "Confira se a base tem semanas suficientes de histórico.", **rastro}
    if segmento:
        achados = [s for s in retorno["risco_por_segmento"] if _sem_acento(s["nome"]) == _sem_acento(segmento)]
        if not achados:
            return {"erro": f"Segmento '{segmento}' não encontrado entre os households ativos.",
                    "sugestao": "Segmentos disponíveis: " + ", ".join(s["nome"] for s in retorno["risco_por_segmento"]) + ".", **rastro}
        retorno = {**retorno, "risco_por_segmento": achados}
    return {**retorno, **rastro}
