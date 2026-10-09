"""Confere se uma resposta em texto traz os valores esperados, com tolerância.

Funções puras (testadas em tests/test_eval.py). Três tipos de valor esperado:
- numero: algum número do texto cai dentro da tolerância, aceitando "31,21", "31.21", "65.930,76", "65,930.76",
  "US $ 2 151 812" (espaço, espaço fino ou ";" como milhar), "3,4%", "65,9 mil", "2,1 milhões". Tolerância: 1% por padrão;
  se o YAML define só `tolerancia_abs`, vale só ela; se define as duas, vale a maior. O sinal é ignorado:
  "caiu 5,7%" e "-5,7%" valem o mesmo; quem confere a direção é a leitura humana da resposta;
- id: o inteiro aparece como número inteiro isolado (ex.: STORE_ID, PRODUCT_ID), com ou sem separador de milhar, sem tolerância;
- texto: o texto aparece, sem diferenciar maiúsculas nem acentos.
"""

import re
import unicodedata

REL_PADRAO = 0.01
ABS_PADRAO = 0.06
# Espaços que a resposta usa como separador de milhar: comum, sem quebra, fino, estreito sem quebra, de figura.
_ESPACOS = "\u00a0\u2009\u202f\u2007"
_MILHAR_COM_ESPACO = re.compile(r"(?<![\d.,])\d{1,3}(?:[ ;]\d{3})+(?![\d])")
_NUMERO = re.compile(r"(?<![\w.,])\d[\d.,]*")
_ESCALA = re.compile(r"\s*(mil|k|milh[õo]es|milh[ãa]o|mi)\b", re.I)


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()


def _normalizar(texto: str) -> str:
    """Junta "5 569 230" e "2;151;812" em um só número (grupos de 3 dígitos depois de 1 a 3). O prefixo "US $" não atrapalha."""
    texto = re.sub(f"[{_ESPACOS}]", " ", texto or "")
    return _MILHAR_COM_ESPACO.sub(lambda m: re.sub(r"[ ;]", "", m.group()), texto)


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
    texto = _normalizar(texto)
    for m in _NUMERO.finditer(texto):
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
    for m in _NUMERO.finditer(_normalizar(texto)):
        t = m.group().strip(".,")
        if re.fullmatch(r"\d+", t):
            achados.add(int(t))
        elif re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", t):
            achados.add(int(re.sub(r"[.,]", "", t)))
    return achados


def confere_numero(texto: str, esperado: float, rel: float = REL_PADRAO, abs_: float = ABS_PADRAO) -> bool:
    tolerancia = max(rel * abs(esperado), abs_)
    return any(abs(abs(c) - abs(esperado)) <= tolerancia for c in extrair_numeros(texto))


def confere_id(texto: str, esperado) -> bool:
    return int(esperado) in inteiros_isolados(texto)


def confere_texto(texto: str, esperado: str) -> bool:
    return _sem_acento(esperado).strip() in _sem_acento(texto)


def tolerancias(item: dict) -> tuple[float, float]:
    """(rel, abs) de um valor esperado. Só `tolerancia_abs` no YAML: vale só ela (a relativa não a alarga)."""
    rel, abs_ = item.get("tolerancia_rel"), item.get("tolerancia_abs")
    if rel is None and abs_ is not None:
        return 0.0, float(abs_)
    return (REL_PADRAO if rel is None else float(rel)), (ABS_PADRAO if abs_ is None else float(abs_))


def valores_esperados(colunas: list[str], linhas: list[list], especificacao: list[dict]) -> list[dict]:
    """Traduz a especificação do YAML (coluna, tipo, linhas) nos valores que a resposta precisa trazer."""
    esperados = []
    for item in especificacao:
        posicao = colunas.index(item["coluna"])
        for linha in linhas[: int(item.get("linhas", 1))]:
            rel, abs_ = tolerancias(item)
            esperados.append({"coluna": item["coluna"], "tipo": item.get("tipo", "numero"), "valor": linha[posicao],
                              "rel": rel, "abs": abs_})
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


def acertou(categoria: str, todos_conferem: bool, oraculo_ok: bool, erro: str | None, ferramenta_certa: bool) -> bool:
    """Pergunta de análise só conta como acerto se o agente chamou a ferramenta esperada (o número certo por outro
    caminho, como a definição errada de "Fiéis", é coincidência)."""
    return bool(todos_conferem and oraculo_ok and not erro and (categoria != "analise" or ferramenta_certa))


_NEGACAO = re.compile(r"\b(nao|nem|sem|nenhum|nenhuma|inexistente|inexistentes|ausente)\b")
_CONTRASTE = re.compile(r"\b(mas|porem|contudo|entretanto|no entanto)\b")
_RANKING = re.compile(r"\b(maior|melhor|melhores|lider|top|primeiro|vendeu mais|mais vendeu|ranking)\b")
_OUTRA_ENTIDADE = re.compile(r"\b(loja|lojas|store|produto|produtos|categoria|departamento|cliente|household)\b")


def termo_inexistente(payload_sql: str) -> str:
    """O dado que não existe é a primeira coluna pedida no payload da pergunta (ex.: `vendedor`)."""
    achado = re.search(r"select\s+([a-z_][a-z0-9_]*)", payload_sql or "", re.I)
    return achado.group(1).lower() if achado else ""


def disse_que_nao_existe(texto: str, termo: str) -> bool:
    """A resposta cita o termo pedido e nega que ele exista, sem inventar valor para ele.
    Falha se alguma frase com o termo não tem negação, ou se, depois de "mas", ela afirma um ranking do termo
    (sem trocar por outra entidade como loja ou produto). Frases que terminam em "?" não contam."""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^.!\n;?]*\?", " ", t)   # perguntas ao usuário não afirmam valor
    frases = [f for f in re.split(r"[.!?\n;]+", t) if termo in f]
    if not frases:
        return False
    for f in frases:
        if not _NEGACAO.search(f):
            return False
        partes = _CONTRASTE.split(f, maxsplit=1)
        if len(partes) == 3 and _RANKING.search(partes[2]) and not _OUTRA_ENTIDADE.search(partes[2]):
            return False
    return True
