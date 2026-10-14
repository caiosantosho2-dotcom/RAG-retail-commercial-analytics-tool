"""descrever_dados: o catálogo para quem vai consultar (views, métricas, janela, limitações).

Devolve só metadados, nunca linhas de dados. `catalogo_compacto` é a versão curta que entra
no prompt do agente.
"""

import fnmatch
import unicodedata

import duckdb

from src.config import CFG
from src.nucleo import banco
from src.nucleo.consulta import TABELAS_PERMITIDAS
from src.nucleo.log import registrar_chamada

DESCRICAO_TABELAS = {
    "dim_data": "Calendário: data_id (DAY), data real arbitrária, WEEK_NO, dias na semana, semana_completa.",
    "dim_produto": "Produtos: PRODUCT_ID, DEPARTMENT, COMMODITY_DESC, SUB_COMMODITY_DESC, MANUFACTURER, BRAND (Private/National).",
    "dim_loja": "Lojas: STORE_ID.",
    "dim_household": "Households (clientes): household_key, demografia (quando existe) e tem_demografia.",
    "fato_transacoes": "Itens vendidos (mercadoria, QUANTITY > 0). Prefira vw_vendas_item, que já traz desconto e período.",
    "campaign_desc": "Campanhas: CAMPAIGN, DESCRIPTION (TypeA/B/C), START_DAY, END_DAY.",
    "campaign_table": "Households que receberam cada campanha.",
    "coupon": "Cupons de cada campanha e os produtos a que se aplicam.",
    "coupon_redempt": "Resgates de cupom: household_key, DAY, COUPON_UPC, CAMPAIGN.",
    "causal_semana_loja": "Produtos em display e mailer por semana e loja (linhas, linhas_display, linhas_mailer).",
    "metricas_definicao": "Definição de negócio, fórmula e view de origem de cada métrica.",
}


def _permitida(nome: str) -> bool:
    return any(fnmatch.fnmatchcase(nome.lower(), p) for p in TABELAS_PERMITIDAS)


def _colunas(cur) -> dict[str, list[dict]]:
    linhas = cur.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                         "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position").fetchall()
    saida: dict[str, list[dict]] = {}
    for tabela, coluna, tipo in linhas:
        if _permitida(tabela):
            saida.setdefault(tabela, []).append({"nome": coluna, "tipo": tipo})
    return saida


def _limitacoes(cur) -> list[str]:
    def um(sql):
        try:
            return cur.execute(sql).fetchone()[0]
        except duckdb.Error:
            return None

    n_hh = um("SELECT COUNT(*) FROM dim_household")
    com_demo = um("SELECT COUNT(*) FROM dim_household WHERE tem_demografia")
    lojas = um("SELECT COUNT(DISTINCT STORE_ID) FROM vw_metricas_loja_semana WHERE periodo = 'atual'")
    pequenas = um("SELECT COUNT(DISTINCT STORE_ID) FROM vw_metricas_loja_semana "
                  "WHERE periodo = 'atual' AND amostra_pequena")
    minimo = CFG["metricas"]["loja_amostra_minima_cestas"]
    texto = [
        f"Painel de {n_hh:,} households, não o cliente médio do varejista: resultados por loja ou categoria "
        f"pequena são instáveis. Lojas com menos de {minimo} cestas na janela vêm marcadas como "
        f"amostra_pequena ({pequenas} de {lojas} lojas)." if n_hh else
        "Painel de households, não o cliente médio do varejista.",
        "Valores em dólares (US$). Não existe vendedor individual: a menor unidade de equipe é a loja.",
        "As datas reais são arbitrárias (DAY convertido a partir de uma data-base): feriados e sazonalidade "
        "por data não são confiáveis; compare por semana alinhada.",
        "A comparação com o ano anterior usa as mesmas semanas (WEEK_NO - 52) e só lojas presentes nos dois "
        "períodos; o crescimento de todas as lojas inclui lojas que não existem nos dois períodos.",
        "Combustível, transações diversas e pseudo-itens de cupom ficam fora das vendas.",
        "Diferença entre grupos de clientes não é efeito causal.",
    ]
    if n_hh and com_demo is not None:
        texto.append(f"Demografia existe para {com_demo / n_hh:.0%} dos households; use LEFT JOIN.")
    if um("SELECT COUNT(*) FROM campaign_desc") == 0:
        texto.append("As tabelas de campanha e cupom não foram carregadas: o contexto de ações não está disponível.")
    return texto


def _primeira_frase(texto: str | None) -> str:
    return (texto or "").split(". ")[0].rstrip(".")


def _sem_acento(t: str) -> str:
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower().strip()


@registrar_chamada("descrever_dados")
def descrever_dados(detalhe: str | None = None) -> dict:
    """Mostra as tabelas e views disponíveis, as métricas, a janela de análise, a base de comparação do
    ano anterior e as limitações da base. Use antes de escrever uma consulta ou quando não souber qual
    coluna ou métrica usar. Sem argumento devolve a lista curta; passe em `detalhe` o nome de uma view,
    tabela ou métrica para ver as colunas (com tipo) ou a definição e a fórmula. `detalhe="tudo"` devolve o
    catálogo completo (cerca de 20 KB): é o que o app usa para montar o prompt, evite no meio de uma conversa.
    """
    try:
        cur = banco.cursor()
    except FileNotFoundError:
        return {"erro": "Nenhuma base carregada.", "sugestao": "Rode `python baixar_dados.py` e `python -m src.etl` (ou carregue os arquivos exportados do BI no app)."}
    rastro = banco.rastreabilidade(cur)
    colunas = _colunas(cur)
    comentarios = dict(cur.execute("SELECT view_name, comment FROM duckdb_views() WHERE NOT internal").fetchall())
    views = [{"nome": t, "descricao": comentarios.get(t), "colunas": c}
             for t, c in colunas.items() if t.startswith("vw_")]
    tabelas = [{"nome": t, "descricao": DESCRICAO_TABELAS.get(t, ""), "colunas": c}
               for t, c in colunas.items() if not t.startswith("vw_")]
    metricas = [{"nome": m, "definicao": d, "formula": f, "view_origem": v}
                for m, d, f, v in cur.execute("SELECT metrica, definicao, formula, view_origem "
                                              "FROM metricas_definicao").fetchall()]
    janela = rastro["janela"] or {}
    completo = {"views": views, "tabelas": tabelas, "metricas": metricas,
                "janela_atual": janela.get("atual"), "janela_ano_anterior": janela.get("base"),
                "limitacoes": _limitacoes(cur), **rastro}
    if detalhe is None:
        return {**completo,
                "views": [{"nome": v["nome"], "descricao": _primeira_frase(v["descricao"])} for v in views],
                "tabelas": [{"nome": t["nome"], "descricao": t["descricao"]} for t in tabelas],
                "metricas": [{"nome": m["nome"], "view_origem": m["view_origem"]} for m in metricas],
                "como_ver_mais": "Chame descrever_dados(detalhe='<view, tabela ou métrica>') para ver as colunas ou a definição."}
    pedido = _sem_acento(str(detalhe))
    if pedido == "tudo":
        return completo
    base = {"janela_atual": completo["janela_atual"], "janela_ano_anterior": completo["janela_ano_anterior"], **rastro}
    for item in views + tabelas:
        if _sem_acento(item["nome"]) == pedido:
            relacionadas = [m for m in metricas if m["view_origem"] == item["nome"]]
            return {"tipo": "view" if item["nome"].startswith("vw_") else "tabela", **item, "metricas": relacionadas, **base}
    for m in metricas:
        if _sem_acento(m["nome"]) == pedido:
            return {"tipo": "metrica", **m, **base}
    nomes = [x["nome"] for x in views + tabelas] + [m["nome"] for m in metricas]
    return {"erro": f"'{detalhe}' não é uma view, tabela ou métrica disponível.",
            "sugestao": "Opções: " + ", ".join(nomes) + ".", **rastro}


def catalogo_compacto() -> str:
    """Texto curto (views, colunas e janela) para o prompt do agente; economiza chamadas a descrever_dados."""
    return compactar_catalogo(descrever_dados(detalhe="tudo"))


def compactar_catalogo(d: dict) -> str:
    """O mesmo texto a partir do retorno de descrever_dados (que o agente obtém pelo servidor MCP)."""
    if "erro" in d:
        return ""
    linhas = ["Views disponíveis (use sempre estas para métricas; colunas entre parênteses):"]
    for v in d["views"]:
        resumo = (v["descricao"] or "").split(". ")[0].rstrip(".")
        linhas.append(f"- {v['nome']}: {resumo}. ({', '.join(c['nome'] for c in v['colunas'])})")
    linhas.append("Dimensões: " + "; ".join(
        f"{t['nome']}({', '.join(c['nome'] for c in t['colunas'])})" for t in d["tabelas"]
        if t["nome"].startswith("dim_")))
    j = d["janela_atual"], d["janela_ano_anterior"]
    if all(j):
        linhas.append(f"Janela atual: semanas {j[0]['semanas'][0]}-{j[0]['semanas'][1]} "
                      f"({j[0]['datas'][0]} a {j[0]['datas'][1]}); base do ano anterior: semanas "
                      f"{j[1]['semanas'][0]}-{j[1]['semanas'][1]}.")
    return "\n".join(linhas)
