"""Reavalia resultados do modo vivo já salvos com o avaliador de hoje, sem chamar o modelo.

  python -m eval.reavaliar eval/resultados/vivo_A.json eval/resultados/vivo_B.json --saida eval/resultados/linha_base_reavaliada.json

Vários arquivos se combinam por id: o último da lista vale (use para completar um run que bateu no limite de taxa).
Os arquivos de entrada nunca são alterados. Usa a resposta, as ferramentas chamadas e as consultas gravadas; os valores
esperados são recalculados pelo oráculo (mesmas funções do núcleo), com as tolerâncias do avaliador atual.
"""

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from eval import rodar_avaliacao as ra
from eval.avaliador import acertou, conferir
from src.config import CFG
from src.nucleo import banco


def combinar(arquivos: list[Path]) -> list[dict]:
    por_id: dict[str, dict] = {}
    for arq in arquivos:
        for x in json.loads(arq.read_text(encoding="utf-8"))["resultados"]:
            if x["categoria"] != "integridade":
                por_id[x["id"]] = {**x, "origem": arq.name}
    ordem = [p["id"] for p in ra.carregar_perguntas()]
    return [por_id[i] for i in ordem if i in por_id]


def reavaliar(antigo: dict, p: dict) -> dict:
    if p["categoria"] == "maliciosa":
        if p.get("tipo") != "dado_inexistente":
            return antigo   # o veredito depende dos erros de cada consulta, que o JSON não guarda: mantém o original
        r = SimpleNamespace(texto=antigo["resposta"], consultas=[], erro=antigo["erro"] if "falha do modelo" in str(antigo.get("erro")) else None)
        v = ra.avaliar_maliciosa_viva(p, r)
        return {**antigo, **v, "erro": "; ".join(v["motivos"]) or None}
    e = ra.resolver_esperado(p)
    todos, detalhe = conferir(antigo["resposta"], e["esperados"])
    erro_modelo = antigo.get("erro") if antigo.get("tokens", 0) == 0 or "Não consegui" in str(antigo.get("erro")) or "limite de uso" in str(antigo.get("erro")) else None
    certa = p["ferramenta_esperada"] in antigo["ferramentas"]
    return {**antigo, "acerto": acertou(p["categoria"], todos, e["ok"], erro_modelo, certa), "ferramenta_certa": certa,
            "esperados": [{k: v for k, v in d.items() if k in ("coluna", "tipo", "valor", "achou")} for d in detalhe]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("arquivos", nargs="+", type=Path)
    ap.add_argument("--saida", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.saida.exists():
        raise SystemExit(f"{a.saida} já existe; não sobrescrevo.")
    banco.definir_banco(None)
    perguntas = {p["id"]: p for p in ra.carregar_perguntas()}
    novos = [reavaliar(x, perguntas[x["id"]]) for x in combinar(a.arquivos)]
    n = [x for x in novos if x["categoria"] != "maliciosa"]
    m = [x for x in novos if x["categoria"] == "maliciosa"]
    resumo = {"modo": "vivo_reavaliado", "origem": [x.name for x in a.arquivos], "perguntas": len(n),
              "acertos": sum(x["acerto"] for x in n), "taxa_acerto": sum(x["acerto"] for x in n) / len(n),
              "maliciosas": len(m), "maliciosas_bloqueadas": sum(x["bloqueada"] for x in m),
              "tokens_medios": sum(x["tokens"] for x in novos if x["tokens"]) / max(1, sum(1 for x in novos if x["tokens"])),
              "modelo": CFG["agente"]["modelo"]}
    a.saida.write_text(json.dumps({"resumo": resumo, "resultados": novos}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    sys.stdout.buffer.write((json.dumps(resumo, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    for x in novos:
        marca = ("ok" if x.get("bloqueada" if x["categoria"] == "maliciosa" else "acerto") else "FALHA")
        sys.stdout.buffer.write(f"{x['id']:<4} {marca:<6} {x['tokens']:>6} tokens  {x['tempo_s']:>6.1f}s  ({x['origem']})\n".encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
