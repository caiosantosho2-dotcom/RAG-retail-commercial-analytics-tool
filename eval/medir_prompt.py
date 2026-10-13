"""Mede de que é feito o prompt de cada chamada ao modelo, sem chamar o modelo e sem otimizar nada.

  python -m eval.medir_prompt [--saida relatorio.md]

Partes fixas (vão em toda chamada): instruções, catálogo compacto e esquema das 6 ferramentas.
Partes por pergunta: glossário injetado e a própria pergunta. Partes por rodada de ferramenta: o resultado devolvido.
Tokens são estimados por caracteres (a relação é calibrada com uma resposta real do modelo sem ferramenta, a m05).
"""

import argparse
import inspect
import json
import statistics
import sys
from pathlib import Path

from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from eval import rodar_avaliacao as ra
from src import agente, mcp_server
from src.config import CFG, RAIZ
from src.glossario_rag import buscar_termos_relevantes
from src.glossario_termos import GLOSSARIO
from src.nucleo import banco
from src.nucleo.consulta import executar_consulta
from src.nucleo.descrever import compactar_catalogo, descrever_dados

CARACTERES_POR_TOKEN_PADRAO = 3.6   # a estimativa registrada no CLAUDE.md (2026-10-06)


def _n(texto) -> int:
    return len(texto if isinstance(texto, str) else json.dumps(texto, ensure_ascii=False, separators=(",", ":")))


def calibrar(caminho_json: Path | None) -> tuple[float, str]:
    """Caracteres por token a partir de uma pergunta sem ferramenta (1 chamada), se o JSON existir."""
    if caminho_json is None or not caminho_json.exists():
        return CARACTERES_POR_TOKEN_PADRAO, "padrão do projeto (sem resposta real para calibrar)"
    for x in json.loads(caminho_json.read_text(encoding="utf-8"))["resultados"]:
        if x["id"] == "m05" and x.get("chamadas_llm") == 1 and x["tokens"]:
            return None, f"m05: {x['tokens']} tokens em 1 chamada sem ferramenta"
    return CARACTERES_POR_TOKEN_PADRAO, "padrão do projeto"


def medir() -> dict:
    banco.definir_banco(None)
    catalogo = compactar_catalogo(descrever_dados(detalhe="tudo"))
    instrucoes = agente.INSTRUCOES_SISTEMA.replace("{catalogo}", "")
    ferramentas = [convert_to_openai_tool(StructuredTool.from_function(func=f, name=nome))
                   for nome, f in mcp_server.FERRAMENTAS.items()]
    por_ferramenta = {t["function"]["name"]: _n(t) for t in ferramentas}

    perguntas = ra.carregar_perguntas()
    glossario = [len(agente.montar_pergunta(p["pergunta"])[1]) for p in perguntas]
    pergunta = [len(p["pergunta"]) for p in perguntas]

    resultados = {}
    for p in perguntas:
        sql = p.get("sql_esperado")
        if sql and p["categoria"] == "negocio":
            r = executar_consulta(sql)
            resultados[p["id"]] = _n(r)
    analises = {nome: _n(f()) for nome, f in mcp_server.FERRAMENTAS.items()
                if nome in ("segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos")}
    descrever = {"descrever_dados()": _n(descrever_dados()), "descrever_dados('vw_vendas_item')": _n(descrever_dados(detalhe="vw_vendas_item")),
                 "descrever_dados('tudo')": _n(descrever_dados(detalhe="tudo"))}
    tamanho_por_termo = sorted(((len(g["termo"]) + len(g["definicao"]), g["termo"].split(" (")[0]) for g in GLOSSARIO), reverse=True)
    return {"instrucoes": len(instrucoes), "catalogo": len(catalogo), "ferramentas": sum(por_ferramenta.values()),
            "por_ferramenta": por_ferramenta, "glossario_medio": statistics.mean(glossario), "glossario_max": max(glossario),
            "glossario_completo": sum(len(g["termo"]) + len(g["definicao"]) for g in GLOSSARIO), "pergunta_media": statistics.mean(pergunta),
            "consultas": resultados, "analises": analises, "descrever": descrever, "termos_maiores": tamanho_por_termo[:5],
            "top_k": CFG["agente"]["glossario_top_k"], "limiar": CFG["agente"]["glossario_limiar"]}


def relatorio(m: dict, cpt: float, nota_calibracao: str) -> str:
    def t(c) -> int:
        return round(c / cpt)

    fixo = m["instrucoes"] + m["catalogo"] + m["ferramentas"]
    por_pergunta = m["glossario_medio"] + m["pergunta_media"]
    consultas = list(m["consultas"].values())
    linhas = [
        "# Composição do prompt (medição, sem otimização)", "",
        f"Estimativa: {cpt:.2f} caracteres por token ({nota_calibracao}).", "",
        "## Parte fixa: vai em toda chamada ao modelo", "",
        "| Parte | Caracteres | Tokens (est.) | % do fixo |", "|---|---:|---:|---:|",
        f"| Instruções (15 regras) | {m['instrucoes']:,} | {t(m['instrucoes']):,} | {100 * m['instrucoes'] / fixo:.0f}% |",
        f"| Catálogo compacto (views e colunas) | {m['catalogo']:,} | {t(m['catalogo']):,} | {100 * m['catalogo'] / fixo:.0f}% |",
        f"| Esquema das 6 ferramentas | {m['ferramentas']:,} | {t(m['ferramentas']):,} | {100 * m['ferramentas'] / fixo:.0f}% |",
        f"| **Total fixo** | **{fixo:,}** | **{t(fixo):,}** | 100% |", "",
        "Esquema por ferramenta (caracteres): " + ", ".join(f"{k} {v:,}" for k, v in m["por_ferramenta"].items()) + ".", "",
        "## Por pergunta", "",
        "| Parte | Média (caract.) | Máximo | Tokens médios (est.) |", "|---|---:|---:|---:|",
        f"| Glossário injetado (top {m['top_k']}, limiar {m['limiar']}) | {m['glossario_medio']:,.0f} | {m['glossario_max']:,} | {t(m['glossario_medio']):,} |",
        f"| Pergunta | {m['pergunta_media']:,.0f} | | {t(m['pergunta_media']):,} |", "",
        f"Glossário inteiro: {m['glossario_completo']:,} caracteres ({t(m['glossario_completo']):,} tokens). Maiores termos: "
        + "; ".join(f"{nome} ({c:,})" for c, nome in m["termos_maiores"]) + ".", "",
        "## Resultados de ferramenta (voltam ao modelo em cada rodada seguinte)", "",
        "| Resultado | Caracteres | Tokens (est.) |", "|---|---:|---:|",
        f"| executar_consulta, 20 consultas de avaliação (mediana) | {statistics.median(consultas):,.0f} | {t(statistics.median(consultas)):,} |",
        f"| executar_consulta, maior | {max(consultas):,} | {t(max(consultas)):,} |",
    ]
    for nome, c in {**m["analises"], **m["descrever"]}.items():
        linhas.append(f"| {nome} | {c:,} | {t(c):,} |")
    linhas += ["", "## Custo de uma pergunta típica", "",
               "Cada chamada ao modelo reenvia a parte fixa e o histórico da própria pergunta (glossário, resultados anteriores).", "",
               "| Cenário | Chamadas | Tokens (est.) |", "|---|---:|---:|"]
    consulta_t = t(statistics.median(consultas)) if consultas else 0
    for nome, rodadas in (("1 consulta (2 chamadas)", 1), ("2 consultas (3 chamadas)", 2), ("4 consultas (5 chamadas)", 4)):
        chamadas = rodadas + 1
        total = chamadas * t(fixo + por_pergunta) + sum(consulta_t * (chamadas - 1 - i) for i in range(rodadas))
        linhas.append(f"| {nome} | {chamadas} | {total:,} |")
    return "\n".join(linhas) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--saida", type=Path)
    ap.add_argument("--calibrar-com", type=Path, default=None, help="JSON do modo vivo com a m05 (1 chamada, sem ferramenta)")
    a = ap.parse_args(argv)
    m = medir()
    cpt, nota = calibrar(a.calibrar_com)
    if cpt is None:   # calibra: a m05 não chama ferramenta; o prompt dela = fixo + glossário da m05 + pergunta
        x = next(r for r in json.loads(a.calibrar_com.read_text(encoding="utf-8"))["resultados"] if r["id"] == "m05")
        p = next(q for q in ra.carregar_perguntas() if q["id"] == "m05")
        texto, gloss = agente.montar_pergunta(p["pergunta"])
        caracteres = m["instrucoes"] + m["catalogo"] + m["ferramentas"] + len(texto) + len(x["resposta"])
        cpt = caracteres / x["tokens"]
        nota += f"; {caracteres:,} caracteres enviados e recebidos"
    texto = relatorio(m, cpt, nota)
    sys.stdout.buffer.write(texto.encode("utf-8"))
    if a.saida:
        a.saida.write_text(texto, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
