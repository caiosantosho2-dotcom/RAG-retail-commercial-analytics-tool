"""Confere se uma resposta em texto traz os valores esperados, com tolerância.

Funções puras (testadas em tests/test_eval.py). Três tipos de valor esperado:
- numero: algum número do texto cai dentro da tolerância (relativa ou absoluta, vale a maior), aceitando
  "31,21", "31.21", "65.930,76", "65,930.76", "3,4%", "65,9 mil", "2,1 milhões". O sinal é ignorado:
  "caiu 5,7%" e "-5,7%" valem o mesmo; quem confere a direção é a leitura humana da resposta;
- id: o inteiro aparece como número inteiro isolado (ex.: STORE_ID, PRODUCT_ID), sem tolerância;
- texto: o texto aparece, sem diferenciar maiúsculas nem acentos.
"""

import re
import unicodedata

_NUMERO = re.compile(r"(?<![\w.,])\d[\d.,]*")
_ESCALA = re.compile(r"\s*(mil|k|milh[õo]es|milh[ãa]o|mi)\b", re.I)


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()


def _valores_do_token(token: str) -> list[float]:
    t = token.strip(".,")
    if not t:
        return []
    if "." in t and "," in t:   # o último separador é o decimal
        decimal = "," if t.rfind(",") > t.rfind(".") else "."
        milhar = "." if decimal == "," else ","
        return [float(t.replace(milhar, "").replace(decimal, "."))]
    for sep in (",", "."):
        if sep in t:
            partes = t.split(sep)
            so_milhar = all(len(p) == 3 for p in partes[1:]) and 1 <= len(partes[0]) <= 3
            if len(partes) > 2:
                return [float(t.replace(sep, ""))] if so_milhar else []
            candidatos = [float(partes[0] + "." + partes[1])]
            if so_milhar:   # "1,645" pode ser mil seiscentos e quarenta e cinco
                candidatos.append(float(partes[0] + partes[1]))
            return candidatos
    return [float(t)]


def extrair_numeros(texto: str) -> list[float]:
    """Todos os valores que o texto pode estar dizendo (um token pode ter mais de uma leitura)."""
    saida: list[float] = []
    for m in _NUMERO.finditer(texto or ""):
        base = _valores_do_token(m.group())
        escala = _ESCALA.match(texto, m.end())
        if escala:
            fator = 1e6 if escala.group(1).lower().startswith(("milh", "mi")) and escala.group(1).lower() != "mil" else 1e3
            base = base + [v * fator for v in base]
        saida += base
    return saida


def inteiros_isolados(texto: str) -> set[int]:
    """Inteiros que o texto diz: "367", e também "1.082.185" ou "1,082,185" (separador de milhar)."""
    achados: set[int] = set()
    for m in _NUMERO.finditer(texto or ""):
        t = m.group().strip(".,")
        if re.fullmatch(r"\d+", t):
            achados.add(int(t))
        elif re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", t):
            achados.add(int(re.sub(r"[.,]", "", t)))
    return achados


def confere_numero(texto: str, esperado: float, rel: float = 0.02, abs_: float = 0.06) -> bool:
    tolerancia = max(rel * abs(esperado), abs_)
    return any(abs(abs(c) - abs(esperado)) <= tolerancia for c in extrair_numeros(texto))


def confere_id(texto: str, esperado) -> bool:
    return int(esperado) in inteiros_isolados(texto)


def confere_texto(texto: str, esperado: str) -> bool:
    return _sem_acento(esperado).strip() in _sem_acento(texto)


def valores_esperados(colunas: list[str], linhas: list[list], especificacao: list[dict]) -> list[dict]:
    """Traduz a especificação do YAML (coluna, tipo, linhas) nos valores que a resposta precisa trazer."""
    esperados = []
    for item in especificacao:
        posicao = colunas.index(item["coluna"])
        for linha in linhas[: int(item.get("linhas", 1))]:
            esperados.append({"coluna": item["coluna"], "tipo": item.get("tipo", "numero"), "valor": linha[posicao],
                              "rel": item.get("tolerancia_rel", 0.02), "abs": item.get("tolerancia_abs", 0.06)})
    return esperados


def conferir(texto: str, esperados: list[dict]) -> tuple[bool, list[dict]]:
    """Devolve (todos conferem, detalhe por valor esperado)."""
    detalhe = []
    for e in esperados:
        if e["tipo"] == "id":
            achou = confere_id(texto, e["valor"])
        elif e["tipo"] == "texto":
            achou = confere_texto(texto, e["valor"])
        else:
            achou = confere_numero(texto, float(e["valor"]), e["rel"], e["abs"])
        detalhe.append({**e, "achou": achou})
    return all(d["achou"] for d in detalhe), detalhe
