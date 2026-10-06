"""
glossario_rag.py
Busca no glossário de negócio e devolve as definições relevantes à pergunta, para o prompt.

Mesmo contrato do mecanismo original (`buscar_termos_relevantes(pergunta, top_k, limiar) -> str`,
uma linha "- termo: definição" por resultado), com a busca por TF-IDF de n-gramas de caracteres em
vez de embeddings: sem torch e sem baixar modelo, cabe no Streamlit Community Cloud e tolera plural
e erro de digitação ("filiais" acha "filial"). O índice pesa o termo e os sinônimos mais que o texto
da definição, porque é pelo vocabulário do usuário que a pergunta chega.
"""

import re
import unicodedata
from functools import lru_cache

from sklearn.feature_extraction.text import TfidfVectorizer

from src.config import CFG
from src.glossario_termos import GLOSSARIO

TOP_K_PADRAO = CFG["agente"]["glossario_top_k"]
LIMIAR_SIMILARIDADE = CFG["agente"]["glossario_limiar"]
PESO_DO_TERMO = 3        # quantas vezes o termo (com sinônimos) é repetido no texto indexado
BONUS_DE_SINONIMO = 0.30  # somado quando o termo ou um sinônimo aparece na pergunta como palavra inteira


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


@lru_cache(maxsize=1)
def _gatilhos() -> list[list[re.Pattern]]:
    """Para cada termo, os padrões (termo principal e sinônimos) que valem como menção explícita."""
    padroes = []
    for item in GLOSSARIO:
        achado = re.match(r"^(.*?) \(também: (.*)\)$", item["termo"])
        frases = [achado.group(1)] + achado.group(2).split(",") if achado else [item["termo"]]
        padroes.append([re.compile(r"(?<![a-z0-9])" + re.escape(_sem_acento(f.strip())) + r"s?(?![a-z0-9])")
                        for f in frases if len(f.strip()) >= 3])
    return padroes


def _texto_indexado(item: dict) -> str:
    return " ".join([item["termo"]] * PESO_DO_TERMO + [item["definicao"]])


@lru_cache(maxsize=1)
def _construir_indice():
    vetorizador = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), strip_accents="unicode",
                                  lowercase=True, sublinear_tf=True)
    matriz = vetorizador.fit_transform([_texto_indexado(i) for i in GLOSSARIO])
    return vetorizador, matriz


def pontuar(pergunta: str) -> list[tuple[float, dict]]:
    """Todos os termos com a pontuação (cosseno + bônus de menção explícita), do maior ao menor."""
    if not pergunta or not pergunta.strip():
        return []
    vetorizador, matriz = _construir_indice()
    pontos = (matriz @ vetorizador.transform([pergunta]).T).toarray().ravel()
    texto = _sem_acento(pergunta)
    for i, padroes in enumerate(_gatilhos()):
        if any(p.search(texto) for p in padroes):
            pontos[i] += BONUS_DE_SINONIMO
    ordem = pontos.argsort()[::-1]
    return [(float(pontos[i]), GLOSSARIO[i]) for i in ordem]


def buscar_termos_relevantes(
    pergunta: str, top_k: int = TOP_K_PADRAO, limiar: float = LIMIAR_SIMILARIDADE
) -> str:
    blocos = []
    for score, item in pontuar(pergunta)[:top_k]:
        if score < limiar:
            continue
        blocos.append(f"- {item['termo']}: {item['definicao']}")
    return "\n".join(blocos)
