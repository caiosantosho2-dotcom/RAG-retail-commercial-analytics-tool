"""Avaliação do chat: roda as perguntas de eval/perguntas.yaml e reporta acerto, ferramenta, tokens e tempo.

  python -m eval.rodar_avaliacao --modo oraculo          sem LLM: roda o SQL esperado pelo executar_consulta
  python -m eval.rodar_avaliacao --modo vivo             com o agente (precisa de GROQ_API_KEY no ambiente)
  python -m eval.rodar_avaliacao --modo vivo --ids q01,q05 --modelo llama-3.1-8b-instant

Rodar sempre que mudar prompt, glossário, views, descrições das ferramentas ou skills.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from eval.avaliador import conferir, valores_esperados
from src import agente
from src.config import CFG, RAIZ
from src.glossario_rag import pontuar
from src.nucleo import banco
from src.nucleo.consulta import executar_consulta
from src.token_counter import LIMITES_REFERENCIA_TPM, ContadorTokens

PASTA = Path(__file__).resolve().parent
PERGUNTAS = PASTA / "perguntas.yaml"
RESULTADOS = PASTA / "resultados"


def carregar_perguntas(ids: list[str] | None = None) -> list[dict]:
    perguntas = yaml.safe_load(PERGUNTAS.read_text(encoding="utf-8"))
    return [p for p in perguntas if not ids or p["id"] in ids]


def resolver_esperado(p: dict) -> dict:
    """Roda o SQL esperado (pelo núcleo, com os mesmos guard-rails) e traduz o resultado em valores."""
    r = executar_consulta(p["sql_esperado"], limite=200)
    if "erro" in r:
        return {"ok": False, "erro": r["erro"], "esperados": []}
    esperados = valores_esperados(r["colunas"], r["linhas"], p["esperado"])
    primeiro = next((e["valor"] for e in esperados if e["tipo"] == "numero"), None)
    faixa = [float(x) for x in p.get("sanidade", [])]
    dentro = True if primeiro is None or not faixa else faixa[0] <= float(primeiro) <= faixa[1]
    vazio = not r["linhas"] or any(v is None for e in esperados for v in [e["valor"]])
    return {"ok": dentro and not vazio, "erro": None if (dentro and not vazio) else
            f"valor fora da faixa de sanidade {faixa}: {primeiro}" if not dentro else "resultado vazio ou nulo",
            "esperados": esperados, "sql": r["sql_executado"]}


def recuperacao_do_glossario(p: dict, k: int | None = None) -> tuple[bool, list[str]]:
    k = k or CFG["agente"]["glossario_top_k"]
    achados = [it["termo"].split(" (")[0] for _, it in pontuar(p["pergunta"])[:k]]
    faltam = [t for t in p.get("termos_glossario", []) if t not in achados]
    return not faltam, faltam


def rodar_oraculo(perguntas: list[dict]) -> list[dict]:
    saida = []
    for p in perguntas:
        e = resolver_esperado(p)
        glossario_ok, faltam = recuperacao_do_glossario(p)
        saida.append({"id": p["id"], "pergunta": p["pergunta"], "oraculo_ok": e["ok"], "erro": e["erro"],
                      "esperados": [{k: v for k, v in x.items() if k in ("coluna", "tipo", "valor")} for x in e["esperados"]],
                      "glossario_ok": glossario_ok, "glossario_faltou": faltam})
    return saida


def rodar_vivo(perguntas: list[dict], modelo: str, pausa_extra: float = 0.0, log=print) -> list[dict]:
    chave = os.environ.get("GROQ_API_KEY")
    if not chave:
        raise SystemExit("Defina GROQ_API_KEY no ambiente para rodar a avaliação ao vivo "
                         "(a chave não é lida de arquivo nem impressa).")
    ag = agente.criar_agente(api_key=chave, modelo=modelo)
    tpm = LIMITES_REFERENCIA_TPM.get(modelo, 6000)
    saida = []
    for i, p in enumerate(perguntas, 1):
        e = resolver_esperado(p)
        contador = ContadorTokens()
        r = agente.perguntar(ag, p["pergunta"], contador=contador, espera_maxima_s=120, registrar=False)
        todos, detalhe = conferir(r.texto, e["esperados"])
        nas_consultas, _ = conferir(json.dumps([c.linhas for c in r.consultas], default=str), e["esperados"])
        glossario_ok, faltam = recuperacao_do_glossario(p)
        saida.append({
            "id": p["id"], "pergunta": p["pergunta"], "acerto": bool(todos and e["ok"] and not r.erro),
            "numero_na_consulta": bool(nas_consultas), "ferramenta_certa": p["ferramenta_esperada"] in r.ferramentas,
            "tokens": r.tokens.get("total_tokens", 0), "chamadas_llm": r.tokens.get("chamadas_llm", 0),
            "tempo_s": r.tempo_s, "erro": r.erro or e["erro"], "resposta": r.texto,
            "sql": [c.sql for c in r.consultas], "consultas_com_erro": sum(1 for c in r.consultas if c.erro),
            "esperados": [{k: v for k, v in d.items() if k in ("coluna", "tipo", "valor", "achou")} for d in detalhe],
            "glossario_ok": glossario_ok, "glossario_faltou": faltam, "regra": p["regra"]})
        log(f"[{i}/{len(perguntas)}] {p['id']} {'OK ' if saida[-1]['acerto'] else 'ERRO'} "
            f"{r.tokens.get('total_tokens', 0):>6} tokens {r.tempo_s:>5.1f}s")
        # Respeita o limite de tokens por minuto do plano gratuito entre uma pergunta e a próxima.
        gasto = r.tokens.get("total_tokens", 0)
        time.sleep(max(0.0, gasto / (tpm / 60.0) - r.tempo_s) + pausa_extra)
    return saida


def resumo(resultados: list[dict], modo: str) -> dict:
    n = len(resultados)
    taxa = lambda campo: sum(1 for r in resultados if r[campo]) / n if n else 0.0
    if modo == "oraculo":
        return {"modo": modo, "perguntas": n, "oraculo_ok": taxa("oraculo_ok"), "glossario_ok": taxa("glossario_ok")}
    return {"modo": modo, "perguntas": n, "taxa_acerto": taxa("acerto"),
            "taxa_numero_na_consulta": taxa("numero_na_consulta"), "taxa_ferramenta_certa": taxa("ferramenta_certa"),
            "recuperacao_glossario": taxa("glossario_ok"),
            "tokens_medios": sum(r["tokens"] for r in resultados) / n if n else 0,
            "tempo_medio_s": sum(r["tempo_s"] for r in resultados) / n if n else 0,
            "consultas_com_erro": sum(r["consultas_com_erro"] for r in resultados)}


def relatorio_markdown(resultados: list[dict], r: dict, modelo: str | None) -> str:
    L = [f"# Avaliação do chat ({r['modo']})", "", f"- Data: {datetime.now():%Y-%m-%d %H:%M} · base `"
         f"{executar_consulta('SELECT 1')['versao_base']}`" + (f" · modelo `{modelo}`" if modelo else ""), ""]
    if r["modo"] == "oraculo":
        L += [f"- SQL esperado executa e fica na faixa de sanidade: **{r['oraculo_ok']:.0%}** de {r['perguntas']}",
              f"- Glossário traz os termos esperados entre os 4 primeiros: **{r['glossario_ok']:.0%}**", "",
              "| id | oráculo | glossário | valores esperados |", "|---|---|---|---|"]
        for x in resultados:
            vals = ", ".join(f"{e['coluna']}={e['valor']}" for e in x["esperados"][:6])
            L.append(f"| {x['id']} | {'ok' if x['oraculo_ok'] else 'ERRO: ' + str(x['erro'])} | "
                     f"{'ok' if x['glossario_ok'] else 'faltou ' + ', '.join(x['glossario_faltou'])} | {vals} |")
    else:
        L += [f"- Taxa de acerto (número esperado na resposta): **{r['taxa_acerto']:.0%}** de {r['perguntas']}",
              f"- Número esperado apareceu no resultado da consulta: {r['taxa_numero_na_consulta']:.0%}",
              f"- Ferramenta certa: {r['taxa_ferramenta_certa']:.0%} · recuperação do glossário: {r['recuperacao_glossario']:.0%}",
              f"- Tokens médios por pergunta: {r['tokens_medios']:.0f} · tempo médio: {r['tempo_medio_s']:.1f} s · "
              f"consultas com erro: {r['consultas_com_erro']}", "",
              "| id | acerto | na consulta | tokens | tempo | observação |", "|---|---|---|---|---|---|"]
        for x in resultados:
            obs = x["erro"] or ("" if x["acerto"] else "faltou: " + ", ".join(
                f"{e['coluna']}={e['valor']}" for e in x["esperados"] if not e["achou"]))
            L.append(f"| {x['id']} | {'ok' if x['acerto'] else 'ERRO'} | {'sim' if x['numero_na_consulta'] else 'não'} | "
                     f"{x['tokens']} | {x['tempo_s']:.1f} | {str(obs)[:90]} |")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--modo", choices=["oraculo", "vivo"], default="oraculo")
    ap.add_argument("--ids", help="lista separada por vírgula, ex.: q01,q05")
    ap.add_argument("--modelo", default=CFG["agente"]["modelo"])
    ap.add_argument("--banco", help="caminho do .duckdb (padrão: o do config)")
    ap.add_argument("--pausa", type=float, default=0.0, help="segundos extras entre perguntas (modo vivo)")
    a = ap.parse_args(argv)

    banco.definir_banco(a.banco)
    perguntas = carregar_perguntas(a.ids.split(",") if a.ids else None)
    if not perguntas:
        raise SystemExit("Nenhuma pergunta selecionada.")
    resultados = rodar_oraculo(perguntas) if a.modo == "oraculo" else rodar_vivo(perguntas, a.modelo, a.pausa)
    r = resumo(resultados, a.modo)
    texto = relatorio_markdown(resultados, r, a.modelo if a.modo == "vivo" else None)

    RESULTADOS.mkdir(exist_ok=True)
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    (RESULTADOS / f"{a.modo}_{marca}.json").write_text(
        json.dumps({"resumo": r, "resultados": resultados}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (PASTA / f"ULTIMO_{a.modo.upper()}.md").write_text(texto, encoding="utf-8")
    sys.stdout.buffer.write(texto.encode("utf-8"))
    return 0 if (r.get("oraculo_ok", 1.0) == 1.0) else 1


if __name__ == "__main__":
    sys.exit(main())
