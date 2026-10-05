"""
glossario_rag.py
MECANISMO reaproveitável 100% (funções _carregar_modelo, _construir_indice,
buscar_termos_relevantes — nenhuma depende do schema).

CONTEÚDO a reescrever: a lista GLOSSARIO abaixo é 100% específica da One Up
(PA, ticket médio, filial/loja/equipe, SKU vs produto_key). Para o Dunnhumby,
reescrever com termos como: household, cesta (BASKET_ID), ticket médio por cesta,
itens por cesta, loja (STORE_ID), departamento/commodity, desconto de loja vs.
cupom, marca própria vs. nacional, campanha, mesmo período do ano anterior —
gerar a lista nova com base no dicionário de dados do Dunnhumby e nas views de
métricas do projeto, sem adaptar os termos antigos. Não existe vendedora.
"""

import numpy as np
import streamlit as st
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
TOP_K_PADRAO = 4
LIMIAR_SIMILARIDADE = 0.30

# ==========================================
# REESCREVER DO ZERO para os termos do Dunnhumby — isto é só um placeholder
# ==========================================
GLOSSARIO = [
    {
        "termo": "EXEMPLO — SUBSTITUIR",
        "definicao": (
            "Placeholder. Reescrever com os termos de negócio do Dunnhumby, "
            "apontando para as views de métricas do projeto."
        ),
    },
]


@st.cache_resource(show_spinner=False)
def _carregar_modelo():
    return SentenceTransformer(EMBEDDING_MODEL)


@st.cache_resource(show_spinner=False)
def _construir_indice():
    modelo = _carregar_modelo()
    textos_busca = [f"{item['termo']}: {item['definicao']}" for item in GLOSSARIO]
    embeddings = modelo.encode(textos_busca, normalize_embeddings=True)
    return np.array(embeddings)


def buscar_termos_relevantes(
    pergunta: str, top_k: int = TOP_K_PADRAO, limiar: float = LIMIAR_SIMILARIDADE
) -> str:
    if not pergunta or not pergunta.strip():
        return ""

    modelo = _carregar_modelo()
    matriz_embeddings = _construir_indice()
    embedding_pergunta = modelo.encode([pergunta], normalize_embeddings=True)[0]
    similaridades = matriz_embeddings @ embedding_pergunta
    indices_ordenados = np.argsort(-similaridades)[:top_k]

    blocos = []
    for idx in indices_ordenados:
        score = similaridades[idx]
        if score < limiar:
            continue
        item = GLOSSARIO[idx]
        blocos.append(f"- {item['termo']}: {item['definicao']}")

    return "\n".join(blocos)
