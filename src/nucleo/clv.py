"""CLV por segmento RFM: "quanto vale cada grupo de clientes".

Decisão que a análise apoia: quanto investir em reter ou reativar cada grupo. Método (premissas no retorno):

  CLV por household = margem x gasto médio das últimas 26 semanas x razão
  razão = gasto nas 52 semanas seguintes / gasto nas 26 anteriores, observada para o MESMO segmento um ano antes.

A razão embute retenção, migração entre segmentos e regressão à média, sem assumir distribuição. Households sem
compra na janela formam um grupo próprio, estimado direto pelo gasto médio dos análogos do ano anterior (não há razão
com passado zero). O intervalo vem de bootstrap de households (coorte de calibração e coorte atual). O mesmo método,
em 26 semanas, é testado contra o que de fato aconteceu e contra a regra ingênua "repetir o último período".
A margem é premissa, não dado: o dataset não tem custo.
"""

import numpy as np
import pandas as pd

from src.config import CFG
from src.nucleo import banco, cache
from src.nucleo import rfm
from src.nucleo.log import registrar_chamada

NOME_SEM_COMPRA = "Sem compra na janela"


class ClvIndisponivel(Exception):
    def __init__(self, erro: str, sugestao: str):
        super().__init__(erro)
        self.erro, self.sugestao = erro, sugestao


def _usd(x: float) -> str:
    return "US$ " + f"{x:,.0f}".replace(",", ".")


def _num(x: float, casas: int = 2) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _pct(x: float, casas: int = 0) -> str:
    return _num(x, casas) + "%"


def _sem_acento(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower().strip()


# --------------------------------------------------------------------------- dados

def janelas(cur) -> dict:
    j = cur.execute("SELECT semana_ini_atual, semana_fim_atual, semana_ini_base, semana_fim_base, semanas, offset_semanas "
                    "FROM vw_janela").df().iloc[0]
    if j.isna().any():
        raise ClvIndisponivel("A janela de análise não pôde ser calculada.", "Confira se a base tem semanas completas.")
    return {"ini_atual": int(j.semana_ini_atual), "fim_atual": int(j.semana_fim_atual), "ini_base": int(j.semana_ini_base),
            "fim_base": int(j.semana_fim_base), "L": int(j.semanas), "offset": int(j.offset_semanas)}


def gasto_no_periodo(cur, ids: np.ndarray, semana_ini: int, semana_fim: int) -> np.ndarray:
    """Faturamento de cada household em [semana_ini, semana_fim], na ordem de `ids` (zero se não comprou)."""
    s = cur.execute("SELECT household_key, SUM(faturamento) AS v FROM vw_cliente_semana WHERE WEEK_NO BETWEEN ? AND ? "
                    "GROUP BY household_key", [semana_ini, semana_fim]).df()
    s["v"] = s["v"].astype(float)
    return s.set_index("household_key")["v"].reindex(ids).fillna(0.0).to_numpy()


def _todos_os_households(cur) -> np.ndarray:
    return cur.execute("SELECT household_key FROM dim_household ORDER BY household_key").df()["household_key"].to_numpy()


def _segmentar(df: pd.DataFrame, k: int, nomes_esperados: set[str], onde: str) -> np.ndarray:
    nomes, _ = rfm.ajustar_segmentos(df, k)
    if set(nomes) != nomes_esperados:
        raise ClvIndisponivel(
            f"Os segmentos da janela {onde} não têm os mesmos nomes dos atuais ({sorted(set(nomes))} contra {sorted(nomes_esperados)}).",
            "O CLV compara cada segmento com ele mesmo um ano antes; sem nomes iguais a comparação não é válida.")
    return nomes


# --------------------------------------------------------------------------- bootstrap

def bootstrap(grupos: dict[str, dict], n_boot: int, nivel: float, semente: int) -> dict:
    """Reamostra households (calibração e atual, por segmento). Devolve, por grupo, as sorteadas de razão e de receita
    por household, e a soma ponderada pelo tamanho atual (total)."""
    rng = np.random.default_rng(semente)
    razao, receita = {}, {}
    total = np.zeros(n_boot)
    for nome in sorted(grupos):
        g = grupos[nome]
        if g["tipo"] == "razao":
            nc, na = len(g["cal_valor"]), len(g["atual_valor"])
            ic, ia = rng.integers(0, nc, (n_boot, nc)), rng.integers(0, na, (n_boot, na))
            razao[nome] = g["cal_fut"][ic].sum(axis=1) / g["cal_valor"][ic].sum(axis=1)
            receita[nome] = g["atual_valor"][ia].mean(axis=1) * razao[nome]
        else:   # análogos: gasto médio futuro de quem também estava sem compra um ano antes
            na = len(g["cal_fut"])
            receita[nome] = g["cal_fut"][rng.integers(0, na, (n_boot, na))].mean(axis=1)
        total += g["n_atual"] * receita[nome]
    return {"razao": razao, "receita": receita, "total_receita": total}


def _ic(draws: np.ndarray, nivel: float) -> list[float]:
    lo, hi = np.percentile(draws, [(1 - nivel) / 2 * 100, (1 + nivel) / 2 * 100])
    return [float(lo), float(hi)]


# --------------------------------------------------------------------------- backtest

def backtest(cur, w: dict, k: int, nomes_atuais: set[str], tabela_cal: pd.DataFrame, analogos_cal: np.ndarray) -> dict | None:
    """Calibra em [base] -> [as L semanas seguintes]; segmenta essas L semanas; prevê as L semanas após elas e
    compara com o real e com a regra ingênua. Indisponível se não houver semanas observadas suficientes."""
    L, fim_b = w["L"], w["fim_base"]
    f1 = (fim_b + 1, fim_b + L)            # semanas seguintes à base (também a janela do segundo RFM)
    f2 = (fim_b + L + 1, fim_b + 2 * L)    # semanas a prever
    if f2[1] > w["fim_atual"]:
        return None
    # razão em L semanas, por segmento, a partir da coorte da base
    razao_l = {}
    for nome, g in tabela_cal.groupby("segmento"):
        razao_l[nome] = float(g["fut_l"].sum() / g["valor"].sum())
    media_sem_compra_l = float(analogos_cal.mean()) if len(analogos_cal) else 0.0

    df2, _ = rfm.base_rfm(cur, *f1)
    nomes2 = _segmentar(df2, k, nomes_atuais, f"{f1[0]}-{f1[1]}")
    ids2 = df2["household_key"].to_numpy()
    real2 = gasto_no_periodo(cur, ids2, *f2)
    linhas, previsto_i, ingenuo_i = [], np.zeros(len(df2)), df2["valor"].to_numpy()
    for nome in sorted(nomes_atuais, key=lambda n: -df2.loc[nomes2 == n, "valor"].mean()):
        m = nomes2 == nome
        passado, real = float(df2.loc[m, "valor"].sum()), float(real2[m].sum())
        prev = passado * razao_l[nome]
        previsto_i[m] = df2.loc[m, "valor"].to_numpy() * razao_l[nome]
        linhas.append({"nome": nome, "households": int(m.sum()), "previsto_metodo_usd": prev, "previsto_ingenuo_usd": passado,
                       "real_usd": real, "erro_metodo_pct": 100 * (prev / real - 1), "erro_ingenuo_pct": 100 * (passado / real - 1)})
    # grupo sem compra: o ingênuo prevê zero (passado zero)
    todos = _todos_os_households(cur)
    sem = np.setdiff1d(todos, ids2)
    if len(sem):
        real_sem = float(gasto_no_periodo(cur, sem, *f2).sum())
        prev_sem = media_sem_compra_l * len(sem)
        linhas.append({"nome": NOME_SEM_COMPRA, "households": int(len(sem)), "previsto_metodo_usd": prev_sem,
                       "previsto_ingenuo_usd": 0.0, "real_usd": real_sem,
                       "erro_metodo_pct": 100 * (prev_sem / real_sem - 1) if real_sem else float("nan"),
                       "erro_ingenuo_pct": -100.0 if real_sem else float("nan")})
    tot = {c: float(sum(l[c] for l in linhas)) for c in ("previsto_metodo_usd", "previsto_ingenuo_usd", "real_usd")}
    tot["erro_metodo_pct"] = 100 * (tot["previsto_metodo_usd"] / tot["real_usd"] - 1)
    tot["erro_ingenuo_pct"] = 100 * (tot["previsto_ingenuo_usd"] / tot["real_usd"] - 1)
    ganha = sum(1 for l in linhas if abs(l["erro_metodo_pct"]) < abs(l["erro_ingenuo_pct"]))
    return {
        "horizonte_semanas": L, "calibracao": f"semanas {w['ini_base']}-{fim_b} -> {f1[0]}-{f1[1]}",
        "teste": f"segmentos de {f1[0]}-{f1[1]} -> previsão de {f2[0]}-{f2[1]}",
        "segmentos": linhas, "total": tot,
        "mae_household_metodo_usd": float(np.abs(real2 - previsto_i).mean()),
        "mae_household_ingenuo_usd": float(np.abs(real2 - ingenuo_i).mean()),
        "segmentos_em_que_o_metodo_ganha": int(ganha), "segmentos_avaliados": len(linhas),
        "metodo_ganha_no_total": bool(abs(tot["erro_metodo_pct"]) < abs(tot["erro_ingenuo_pct"]))}


# --------------------------------------------------------------------------- e daí?

def montar_e_dai(segs: list[dict], total: dict, prem: dict, bt: dict | None, avisos: list[str]) -> dict:
    topo = max(segs, key=lambda s: s["clv_medio"])
    pct_topo = 100 * topo["clv_total_usd"] / total["clv_total_usd"]
    conclusao = (f"{topo['nome']} valem {_usd(topo['clv_medio'])} por household em {prem['horizonte_semanas']} semanas "
                 f"(IC 95%: {_usd(topo['ic_95'][0])} a {_usd(topo['ic_95'][1])}) e concentram {_pct(pct_topo)} do valor esperado "
                 f"({_usd(total['clv_total_usd'])} de margem).")
    if bt and not bt["metodo_ganha_no_total"] and bt["segmentos_em_que_o_metodo_ganha"] * 2 < bt["segmentos_avaliados"]:
        conclusao += " Atenção: no backtest o método não superou a regra ingênua; trate os valores como ordem de grandeza."
    retorno_pausa = [s for s in segs if s.get("ritmo_relativo") and s["ritmo_relativo"] > 1.3]
    acao = (f"Priorizar a retenção dos {topo['nome']}: cada 1% de gasto perdido neles pesa mais que em qualquer outro grupo.")
    if retorno_pausa:
        nomes = " e ".join(s["nome"] for s in retorno_pausa)
        menor, maior = (_num(f(s["ritmo_relativo"] for s in retorno_pausa), 1) for f in (min, max))
        faixa = f"{menor}x" if menor == maior else f"{menor}x a {maior}x"
        acao += (f" {nomes} tendem a gastar mais nas semanas seguintes do que no ritmo atual (ritmo de {faixa}): "
                 "prefira ofertas de reativação seletivas a descontos amplos.")
    impacto = (f"Valor esperado total em {prem['horizonte_semanas']} semanas: {_usd(total['clv_total_usd'])} de margem "
               f"(IC 95%: {_usd(total['ic_95'][0])} a {_usd(total['ic_95'][1])}) sobre {_usd(total['receita_esperada_total_usd'])} de "
               f"receita, com margem assumida de {_pct(100 * prem['margem'])}. Uma queda de 5% no gasto dos {topo['nome']} custa "
               f"cerca de {_usd(0.05 * topo['clv_total_usd'])}.")
    lim = [f"A margem de {_pct(100 * prem['margem'])} é premissa (o dataset não tem custo): o CLV escala linearmente com ela.",
           f"O horizonte de {prem['horizonte_semanas']} semanas não pode ser testado: só há uma transição de {prem['horizonte_semanas']} "
           "semanas observada, e ela pode não se repetir."]
    if bt:
        lim.append(f"No backtest de {bt['horizonte_semanas']} semanas o método errou {_pct(abs(bt['total']['erro_metodo_pct']), 1)} no total "
                   f"(regra ingênua: {_pct(abs(bt['total']['erro_ingenuo_pct']), 1)}) e ganhou em {bt['segmentos_em_que_o_metodo_ganha']} de "
                   f"{bt['segmentos_avaliados']} grupos; por household o erro absoluto médio foi {_usd(bt['mae_household_metodo_usd'])} "
                   f"contra {_usd(bt['mae_household_ingenuo_usd'])} da regra ingênua: o valor serve como média de grupo, não como previsão "
                   "individual.")
    else:
        lim.append("O backtest não pôde ser feito: não há semanas observadas suficientes.")
    lim.append("O intervalo cobre só a variação entre households; não inclui a incerteza da margem nem a escolha dos segmentos. "
               "Razões altas nos grupos de menor gasto refletem em parte regressão à média (parte do gasto baixo de uma janela é "
               "acaso de calendário), sem desconto financeiro em 12 meses.")
    lim += avisos
    return {"conclusao": conclusao, "acao_recomendada": acao, "impacto_estimado": impacto, "limitacoes": " ".join(lim)}


# --------------------------------------------------------------------------- análise

def _calcular(cur) -> dict:
    cfg = CFG["analises"]["clv"]
    w = janelas(cur)
    horizonte = cfg["horizonte_semanas"]
    if horizonte != w["offset"] or w["fim_atual"] - w["fim_base"] != horizonte:
        raise ClvIndisponivel(f"O horizonte de {horizonte} semanas precisa ser igual ao deslocamento do ano anterior ({w['offset']}).",
                              "Ajuste analises.clv.horizonte_semanas ou janela.offset_ano_anterior no config.yaml.")
    avisos: list[str] = []

    # coorte atual: segmentos da 5a e gasto das últimas L semanas
    r_atual, atrib = rfm._resultado(cur, None)
    k = r_atual["k_usado"]
    df_a, _ = rfm.carregar_base(cur, "atual")
    df_a = df_a.merge(atrib, on="household_key")
    nomes_atuais = set(df_a["segmento"])

    # coorte de calibração: janela base, mesmo K e mesmas regras de nome; gasto observado nas 52 semanas seguintes
    df_b, _ = rfm.carregar_base(cur, "base")
    nomes_b = _segmentar(df_b, k, nomes_atuais, "base")
    ids_b = df_b["household_key"].to_numpy()
    fut_b = gasto_no_periodo(cur, ids_b, w["fim_base"] + 1, w["fim_atual"])
    fut_l = gasto_no_periodo(cur, ids_b, w["fim_base"] + 1, w["fim_base"] + w["L"])
    cal = pd.DataFrame({"segmento": nomes_b, "valor": df_b["valor"].to_numpy(), "fut": fut_b, "fut_l": fut_l})

    todos = _todos_os_households(cur)
    sem_atual = np.setdiff1d(todos, df_a["household_key"].to_numpy())
    analogos_ids = np.setdiff1d(todos, ids_b)
    analogos_fut = gasto_no_periodo(cur, analogos_ids, w["fim_base"] + 1, w["fim_atual"])
    analogos_l = gasto_no_periodo(cur, analogos_ids, w["fim_base"] + 1, w["fim_base"] + w["L"])

    grupos = {}
    for nome in nomes_atuais:
        c, a = cal[cal["segmento"] == nome], df_a[df_a["segmento"] == nome]
        if len(c) < cfg["tamanho_minimo_grupo"]:
            avisos.append(f"O segmento {nome} tem só {len(c)} households na janela de calibração: a razão é pouco confiável.")
        grupos[nome] = {"tipo": "razao", "cal_valor": c["valor"].to_numpy(), "cal_fut": c["fut"].to_numpy(),
                        "atual_valor": a["valor"].to_numpy(), "n_atual": len(a)}
    if len(sem_atual):
        if len(analogos_fut) < cfg["tamanho_minimo_grupo"]:
            avisos.append(f"O grupo {NOME_SEM_COMPRA} tem só {len(analogos_fut)} análogos no ano anterior: o valor é pouco confiável.")
        grupos[NOME_SEM_COMPRA] = {"tipo": "analogos", "cal_fut": analogos_fut, "n_atual": int(len(sem_atual))}

    boot = bootstrap(grupos, cfg["n_bootstrap"], cfg["nivel_ic"], CFG["semente"])
    margem, nivel = cfg["margem"], cfg["nivel_ic"]
    segs = []
    for nome, g in grupos.items():
        receita_draws = boot["receita"][nome]
        if g["tipo"] == "razao":
            valor_medio = float(g["atual_valor"].mean())
            razao = float(g["cal_fut"].sum() / g["cal_valor"].sum())
            receita = valor_medio * razao
            extra = {"valor_medio_janela_usd": valor_medio, "razao_futuro_passado": razao,
                     "razao_ic_95": _ic(boot["razao"][nome], nivel), "ritmo_relativo": razao / (horizonte / w["L"])}
        else:
            receita = float(g["cal_fut"].mean())
            extra = {"valor_medio_janela_usd": 0.0, "razao_futuro_passado": None, "razao_ic_95": None, "ritmo_relativo": None}
        calibracao = ({"households": int(len(g["cal_valor"])), "gasto_passado_usd": float(g["cal_valor"].sum()),
                       "gasto_futuro_usd": float(g["cal_fut"].sum())} if g["tipo"] == "razao" else
                      {"households": int(len(g["cal_fut"])), "gasto_passado_usd": 0.0, "gasto_futuro_usd": float(g["cal_fut"].sum())})
        segs.append({"nome": nome, "n": int(g["n_atual"]), **extra, "calibracao": calibracao, "receita_esperada_usd": receita,
                     "clv_medio": margem * receita, "ic_95": [margem * x for x in _ic(receita_draws, nivel)],
                     "clv_total_usd": margem * receita * g["n_atual"]})
    ordem = {s["nome"]: i for i, s in enumerate(r_atual["segmentos"])}
    segs.sort(key=lambda s: ordem.get(s["nome"], 99))
    receita_total = float(sum(s["receita_esperada_usd"] * s["n"] for s in segs))
    total = {"households": int(sum(s["n"] for s in segs)), "receita_esperada_total_usd": receita_total,
             "clv_total_usd": margem * receita_total, "ic_95": [margem * x for x in _ic(boot["total_receita"], nivel)]}
    prem = {"horizonte_semanas": horizonte, "margem": margem, "margem_e_premissa": True,
            "metodo": "CLV por household = margem x gasto médio das últimas semanas da janela x razão (gasto nas 52 semanas seguintes "
                      "÷ gasto nas semanas da janela) observada para o mesmo segmento um ano antes",
            "janela_atual": f"semanas {w['ini_atual']}-{w['fim_atual']}", "janela_calibracao": f"semanas {w['ini_base']}-{w['fim_base']}",
            "semanas_futuras_observadas": f"{w['fim_base'] + 1}-{w['fim_atual']}", "desconto_financeiro": "não aplicado (horizonte de 12 meses)",
            "grupo_sem_compra": f"{NOME_SEM_COMPRA}: gasto médio dos households sem compra na janela base nas 52 semanas seguintes",
            "bootstrap": {"reamostras": cfg["n_bootstrap"], "nivel": nivel, "semente": CFG["semente"]}}
    bt = backtest(cur, w, k, nomes_atuais, cal, analogos_l)
    # O texto do "e daí?" sai dos números já arredondados: texto e tabelas nunca divergem na última casa.
    retorno = _arredondar({"segmentos": segs, "total": total, "premissas": prem, "backtest": bt, "avisos": avisos})
    retorno["e_dai"] = montar_e_dai(retorno["segmentos"], retorno["total"], retorno["premissas"], retorno["backtest"], avisos)
    return retorno


def _arredondar(o):
    if isinstance(o, dict):
        return {k: _arredondar(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_arredondar(v) for v in o]
    if isinstance(o, float):
        return None if np.isnan(o) else round(o, 3)
    return o


@registrar_chamada("calcular_clv")
def calcular_clv(segmento: str | None = None) -> dict:
    """Estima o valor do cliente (CLV) por segmento RFM, com intervalo de confiança.

    Use para "quanto vale cada grupo de clientes", "margem esperada", "valor esperado de um cliente" ou "quanto vale
    um cliente". Chame sem argumentos, com as premissas do projeto (margem de 25% e horizonte de 52 semanas), e
    declare-as na resposta; não peça a fórmula da margem ao usuário. Premissas (margem, horizonte, método) vêm sempre no retorno;
    o intervalo é bootstrap de households. Passe `segmento` para filtrar um grupo (os totais continuam os da base inteira).
    """
    try:
        cur = banco.cursor()
    except FileNotFoundError:
        return {"erro": "Nenhuma base carregada.", "sugestao": "Carregue os arquivos de dados antes de analisar."}
    rastro = banco.rastreabilidade(cur)
    try:
        chave = cache.chave(cur, "clv", cfg=CFG["analises"]["clv"], rfm=CFG["analises"]["rfm"], semente=CFG["semente"],
                            ativo=CFG["metricas"]["cliente_ativo_semanas"], janela=CFG["janela"])
        retorno = cache.obter(chave, lambda: _calcular(cur))
    except ClvIndisponivel as e:
        return {"erro": e.erro, "sugestao": e.sugestao, **rastro}
    except Exception as e:
        return {"erro": f"Não foi possível calcular o CLV ({type(e).__name__}).",
                "sugestao": "Confira se a base tem as semanas da janela atual e do ano anterior.", **rastro}
    if segmento:
        achados = [s for s in retorno["segmentos"] if _sem_acento(s["nome"]) == _sem_acento(segmento)]
        if not achados:
            return {"erro": f"Segmento '{segmento}' não encontrado.",
                    "sugestao": "Segmentos disponíveis: " + ", ".join(s["nome"] for s in retorno["segmentos"]) + ".", **rastro}
        retorno = {**retorno, "segmentos": achados}
    return {**retorno, **rastro}
