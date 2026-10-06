"""Teste de desconto entre segmentos RFM: "os segmentos recebem desconto diferente?".

Hipótese escrita antes de rodar: os segmentos recebem desconto parecido (ele vem sobretudo do cartão de fidelidade).
Escolhas (cada uma com o motivo no config e no retorno):
- Kruskal-Wallis, não ANOVA: o % de desconto por household é assimétrico e não normal (Shapiro, reportado);
- post-hoc de Mann-Whitney com Holm, só se o teste geral for significativo (regra da spec);
- com ~2.400 households quase qualquer diferença vira "significativa", então o veredito exige também tamanho de efeito
  (eta² e diferença de medianas com IC bootstrap) e é repetido só com households de 5 ou mais compras, porque o % de
  desconto de quem comprou pouco é ruído (poucas cestas);
- mostra diferença entre grupos, nunca efeito causal do desconto.
As três funções estatísticas vêm de `src/teste_hipotese.py`, cópia fiel da referência.
"""

from itertools import combinations

import numpy as np
import pandas as pd

from src import teste_hipotese as th
from src.config import CFG
from src.nucleo import banco, cache, rfm
from src.nucleo.log import registrar_chamada

HIPOTESE = "Os segmentos recebem desconto parecido (o % de desconto não depende do segmento)."
METRICA = "% de desconto do household na janela atual = 100 x soma do desconto / soma do valor bruto (mesma definição das views)"


class TesteIndisponivel(Exception):
    def __init__(self, erro: str, sugestao: str):
        super().__init__(erro)
        self.erro, self.sugestao = erro, sugestao


def _pt(x: float, casas: int = 1) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _milhar(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def _usd(x: float) -> str:
    return "US$ " + _milhar(x)


def _p(p: float) -> str:
    return "< 0,001" if p < 0.001 else "= " + _pt(p, 3)


# --------------------------------------------------------------------------- estatística

def ic_diferencas_mediana(dados: dict[str, np.ndarray], ordem: list[str], n_boot: int, nivel: float, semente: int) -> list[dict]:
    """IC bootstrap (percentil) da diferença de medianas entre cada par de grupos, em pontos percentuais.

    Cada grupo é reamostrado à parte (n_boot medianas por grupo); a diferença de um par usa as mesmas posições de reamostra.
    Os IC não são ajustados por Holm (descritivos)."""
    rng = np.random.default_rng(semente)
    medianas = {g: np.median(dados[g][rng.integers(0, len(dados[g]), size=(n_boot, len(dados[g])))], axis=1) for g in ordem}
    cauda = (1 - nivel) / 2 * 100
    saida = []
    for a, b in combinations(ordem, 2):
        dif = medianas[a] - medianas[b]
        inf, sup = np.percentile(dif, [cauda, 100 - cauda])
        saida.append({"grupo_1": a, "grupo_2": b, "diferenca_mediana_pp": float(np.median(dados[a]) - np.median(dados[b])),
                      "ic_inferior": float(inf), "ic_superior": float(sup), "exclui_zero": bool(inf > 0 or sup < 0)})
    return saida


def veredito(kw: dict, ics: list[dict], cfg: dict | None = None) -> str:
    """'sem_diferenca_detectavel' (p >= alfa), 'diferenca_desprezivel' (significativa, efeito pequeno) ou 'diferenca_relevante'."""
    cfg = cfg or CFG["analises"]["teste_desconto"]
    if not kw["p_valor"] < cfg["alfa"]:
        return "sem_diferenca_detectavel"
    pares_relevantes = [i for i in ics if i["exclui_zero"] and abs(i["diferenca_mediana_pp"]) >= cfg["diferenca_relevante_pp"]]
    if kw["eta_quadrado_aprox"] >= cfg["eta2_relevante"] or pares_relevantes:
        return "diferenca_relevante"
    return "diferenca_desprezivel"


def _grupos(d: pd.DataFrame, ordem: list[str]) -> list[dict]:
    saida = []
    for g in ordem:
        t = d[d["segmento"] == g]
        x = t["pct_desconto"]
        q1, med, q3 = x.quantile([0.25, 0.5, 0.75])
        iqr = q3 - q1
        saida.append({"segmento": g, "households": int(len(t)), "mediana_pct": float(med), "media_pct": float(x.mean()),
                      "desvio_padrao_pp": float(x.std()), "q25_pct": float(q1), "q75_pct": float(q3),
                      "bigode_inf_pct": float(x[x >= q1 - 1.5 * iqr].min()), "bigode_sup_pct": float(x[x <= q3 + 1.5 * iqr].max()),
                      "fora_do_bigode": int(((x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)).sum()),
                      "taxa_ponderada_pct": float(100 * t["desconto_total"].sum() / t["valor_bruto"].sum()),
                      "desconto_total_usd": float(t["desconto_total"].sum()), "valor_bruto_usd": float(t["valor_bruto"].sum())})
    return saida


def _kw(d: pd.DataFrame) -> dict:
    kw = th.teste_kruskal_wallis(d, "pct_desconto", "segmento")
    return {"estatistica_H": float(kw["estatistica_H"]), "p_valor": float(kw["p_valor"]), "significativo_5pct": bool(kw["significativo_5pct"]),
            "n_grupos_testados": int(kw["n_grupos_testados"]), "n_total_observacoes": int(kw["n_total_observacoes"]),
            "eta_quadrado_aprox": float(kw["eta_quadrado_aprox"])}


def _dados(d: pd.DataFrame, ordem: list[str]) -> tuple[dict[str, np.ndarray], list[str]]:
    dados = {g: d.loc[d["segmento"] == g, "pct_desconto"].to_numpy() for g in ordem}
    return dados, [g for g in ordem if len(dados[g]) >= 3]


def _impacto(grupos: list[dict]) -> dict:
    total_desc = sum(g["desconto_total_usd"] for g in grupos)
    total_bruto = sum(g["valor_bruto_usd"] for g in grupos)
    menor = min(grupos, key=lambda g: g["taxa_ponderada_pct"])
    # Quanto de desconto a menos se todos recebessem a menor taxa ponderada (se a demanda não mudasse: sem causalidade).
    folga = sum(g["valor_bruto_usd"] * (g["taxa_ponderada_pct"] - menor["taxa_ponderada_pct"]) / 100 for g in grupos)
    return {"desconto_total_usd": total_desc, "taxa_geral_pct": 100 * total_desc / total_bruto, "menor_taxa_segmento": menor["segmento"],
            "menor_taxa_pct": menor["taxa_ponderada_pct"], "desconto_a_menos_se_igualar_usd": folga,
            "desconto_a_menos_pct_do_total": 100 * folga / total_desc}


def montar_e_dai(r: dict) -> dict:
    cfg = r["parametros"]
    v, vs = r["veredito"], r["sensibilidade"]["veredito"]
    kw, ks = r["kruskal_wallis"], r["sensibilidade"]["kruskal_wallis"]
    gr = r["grupos"]
    med_min, med_max = min(gr, key=lambda g: g["mediana_pct"]), max(gr, key=lambda g: g["mediana_pct"])
    amplitude = med_max["mediana_pct"] - med_min["mediana_pct"]
    imp = r["impacto"]
    minimo = cfg["compras_minimas_sensibilidade"]
    robusto = v == vs
    base_sens = f"Só com households de {minimo} ou mais compras ({_milhar(r['sensibilidade']['households'])})"
    eta_s = _pt(max(0.0, ks["eta_quadrado_aprox"]), 4)
    if robusto:
        sens = f"{base_sens} o resultado se mantém: p {_p(ks['p_valor'])}, eta² = {eta_s}."
    elif v == "diferenca_desprezivel" and vs == "sem_diferenca_detectavel":
        sens = (f"{base_sens} a significância desaparece (p {_p(ks['p_valor'])}, eta² = {eta_s}): a diferença do teste completo vem do "
                "ruído de medir desconto em poucas compras.")
    else:
        sens = f"{base_sens} o veredito muda ({vs.replace('_', ' ')}): p {_p(ks['p_valor'])}, eta² = {eta_s}; o resultado depende de quem entra no teste."
    if v == "sem_diferenca_detectavel":
        conclusao = (f"Não há diferença detectável de desconto entre os segmentos (Kruskal-Wallis p {_p(kw['p_valor'])}, eta² = "
                     f"{_pt(kw['eta_quadrado_aprox'], 4)}): as medianas vão de {_pt(med_min['mediana_pct'])}% a {_pt(med_max['mediana_pct'])}%. {sens}")
        acao = "Tratar o desconto como política geral: não há base nos dados para diferenciar a taxa por segmento."
    elif v == "diferenca_desprezivel":
        conclusao = (f"Os segmentos recebem desconto praticamente igual: as medianas vão de {_pt(med_min['mediana_pct'])}% ({med_min['segmento']}) a "
                     f"{_pt(med_max['mediana_pct'])}% ({med_max['segmento']}), {_pt(amplitude)} ponto percentual de amplitude. O teste geral acusa "
                     f"diferença (p {_p(kw['p_valor'])}), mas o efeito é desprezível: eta² = {_pt(kw['eta_quadrado_aprox'], 4)}, ou "
                     f"{_pt(100 * kw['eta_quadrado_aprox'])}% da variação, e todos os intervalos das diferenças de mediana ficam abaixo de "
                     f"{_pt(cfg['diferenca_relevante_pp'], 0)} ponto ou incluem zero. {sens}")
        acao = ("Tratar o desconto como política geral, não por segmento: a diferença estatística existe só no papel e não justifica "
                "ajustar taxa para nenhum grupo. Para mexer na margem, olhar o desconto como um todo ou por categoria (não testado aqui).")
    else:
        pares = sorted((i for i in r["ic_diferencas"] if i["exclui_zero"] and abs(i["diferenca_mediana_pp"]) >= cfg["diferenca_relevante_pp"]),
                       key=lambda i: -abs(i["diferenca_mediana_pp"]))
        destaque = (f" A maior: {pares[0]['grupo_1']} contra {pares[0]['grupo_2']}, {_pt(pares[0]['diferenca_mediana_pp'])} pp de diferença de "
                    f"medianas (IC de {_pt(100 * cfg['nivel_ic'], 0)}%: {_pt(pares[0]['ic_inferior'])} a {_pt(pares[0]['ic_superior'])})." if pares else "")
        conclusao = (f"Os segmentos recebem desconto diferente de forma relevante (p {_p(kw['p_valor'])}, eta² = {_pt(kw['eta_quadrado_aprox'], 4)}); "
                     f"as medianas vão de {_pt(med_min['mediana_pct'])}% a {_pt(med_max['mediana_pct'])}%.{destaque} {sens}")
        acao = (f"Rever a regra de desconto dos segmentos com taxa mais alta ({med_max['segmento']}) e checar se a diferença é intencional; "
                "o teste mostra a diferença, não o motivo.")
    impacto = (f"Desconto total da janela: {_usd(imp['desconto_total_usd'])} ({_pt(imp['taxa_geral_pct'])}% do valor bruto). Se todos os segmentos "
               f"tivessem a menor taxa ponderada ({imp['menor_taxa_segmento']}, {_pt(imp['menor_taxa_pct'], 2)}%), o desconto cairia {_usd(imp['desconto_a_menos_se_igualar_usd'])} "
               f"({_pt(imp['desconto_a_menos_pct_do_total'])}% do total), supondo que a demanda não mudasse.")
    limitacoes = ("Diferença entre grupos, não efeito causal do desconto: o teste não diz que desconto traz mais compra. Os segmentos são definidos por "
                  "recência, frequência e valor, e o % de desconto de quem comprou pouco é instável (poucas cestas), o que aumenta a dispersão dos grupos "
                  f"Esporádicos e Em pausa; por isso a repetição com {minimo} ou mais compras (nela os Em pausa ficam com "
                  f"{_milhar(next((g['households'] for g in r['sensibilidade']['grupos'] if g['segmento'] == 'Em pausa'), 0))} households). "
                  "Uma só janela de 26 semanas. Desconto de loja (cartão) e de cupom estão somados. Os p-valores dos pares são ajustados por Holm; "
                  "os intervalos de confiança das diferenças não. Household não é pessoa. Households sem compra na janela ficam fora.")
    return {"conclusao": conclusao, "acao_recomendada": acao, "impacto_estimado": impacto, "limitacoes": limitacoes}


def _analisar(d: pd.DataFrame, ordem: list[str], cfg: dict, semente: int) -> dict:
    dados, validos = _dados(d, ordem)
    if len(validos) < 2:
        raise TesteIndisponivel("Poucos segmentos com dados suficientes (mínimo 3 households) para comparar.",
                                "Carregue uma base com mais households na janela atual.")
    kw = _kw(d)
    ics = ic_diferencas_mediana(dados, validos, cfg["n_bootstrap"], cfg["nivel_ic"], semente)
    return {"kw": kw, "ics": ics, "validos": validos, "veredito": veredito(kw, ics, cfg)}


def _calcular(cur) -> dict:
    cfg = CFG["analises"]["teste_desconto"]
    semente = CFG["semente"]
    df, _ = rfm.carregar_base(cur)
    seg = rfm.segmentos_por_household(cur)
    d = df.merge(seg, on="household_key", how="inner")
    if len(d) != len(df):
        raise RuntimeError(f"junção perdeu households: {len(df)} -> {len(d)}")
    ordem = list(d.groupby("segmento")["valor"].mean().sort_values(ascending=False).index)
    principal = _analisar(d, ordem, cfg, semente)
    grupos = _grupos(d, ordem)
    normalidade = th.testar_normalidade_por_grupo(d, "pct_desconto", "segmento")
    normalidade["shapiro_p_valor"] = normalidade["shapiro_p_valor"].astype(float)
    if principal["kw"]["significativo_5pct"]:
        ph = th.post_hoc_pairwise_mannwhitney(d, "pct_desconto", "segmento")
        post_hoc, motivo = [{k: (bool(v) if k == "significativo_5pct" else v) for k, v in l.items()} for l in ph.to_dict("records")], None
    else:
        post_hoc, motivo = None, "o teste geral não foi significativo, então as comparações par a par não são feitas"
    minimo = cfg["compras_minimas_sensibilidade"]
    d5 = d[d["frequencia"] >= minimo]
    sens = _analisar(d5, [g for g in ordem if g in set(d5["segmento"])], cfg, semente)
    r = {"hipotese": HIPOTESE, "metrica": METRICA, "parametros": cfg,
         "households": int(len(d)), "grupos": grupos,
         "normalidade_por_grupo": normalidade.rename(columns={"segmento": "segmento"}).to_dict("records"),
         "kruskal_wallis": principal["kw"], "post_hoc_executado": post_hoc is not None, "post_hoc": post_hoc, "post_hoc_motivo": motivo,
         "ic_diferencas": principal["ics"], "veredito": principal["veredito"],
         "sensibilidade": {"minimo_compras": minimo, "households": int(len(d5)), "grupos": _grupos(d5, sens["validos"]),
                           "kruskal_wallis": sens["kw"], "ic_diferencas": sens["ics"], "veredito": sens["veredito"]},
         "impacto": _impacto(grupos)}
    r["e_dai"] = montar_e_dai(r)
    return _arredondar(r)


def _arredondar(o):
    if isinstance(o, dict):
        return {k: _arredondar(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_arredondar(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if np.isnan(o) else (float(o) if abs(o) < 1e-3 and o != 0 else round(float(o), 4))
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


@registrar_chamada("testar_desconto_entre_segmentos")
def testar_desconto_entre_segmentos() -> dict:
    """Testa se o percentual de desconto difere entre os segmentos RFM (Kruskal-Wallis e comparações par a par com Holm).

    Use para "os segmentos recebem desconto diferente?". Mostra diferença entre grupos, não efeito causal do desconto.
    """
    try:
        cur = banco.cursor()
    except FileNotFoundError:
        return {"erro": "Nenhuma base carregada.", "sugestao": "Carregue os arquivos de dados antes de analisar."}
    rastro = banco.rastreabilidade(cur)
    try:
        chave = cache.chave(cur, "teste_desconto", cfg=CFG["analises"]["teste_desconto"], rfm=CFG["analises"]["rfm"], semente=CFG["semente"],
                            ativo=CFG["metricas"]["cliente_ativo_semanas"], janela=CFG["janela"])
        retorno = cache.obter(chave, lambda: _calcular(cur))
    except TesteIndisponivel as e:
        return {"erro": e.erro, "sugestao": e.sugestao, **rastro}
    except Exception as e:
        return {"erro": f"Não foi possível testar o desconto entre segmentos ({type(e).__name__}).",
                "sugestao": "Confira se a base tem households com compra na janela atual.", **rastro}
    return {**retorno, **rastro}
