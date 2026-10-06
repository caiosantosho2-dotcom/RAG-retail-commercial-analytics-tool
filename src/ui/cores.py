"""Cores dos gráficos: tokens da paleta de referência da skill de visualização e o validador em Python.

O validador é o porte fiel de `validate_palette.js` (OKLab, simulação de daltonismo de Machado 2009,
contraste WCAG, faixa de luminosidade e piso de croma), porque a cor é computável e não se confere a olho.
Cada paleta usada nos gráficos é validada nos dois modos em tests/test_cores.py.
"""

import math

# --- tokens (palette.md) -------------------------------------------------------------------------

# Superfícies reais do Streamlit (fundo da página), contra as quais o contraste é medido.
SUPERFICIE = {"claro": "#ffffff", "escuro": "#0e1117"}
TINTA = {
    "claro": {"primaria": "#0b0b0b", "secundaria": "#52514e", "muda": "#898781", "grade": "#e1e0d9", "base": "#c3c2b7"},
    "escuro": {"primaria": "#ffffff", "secundaria": "#c3c2b7", "muda": "#898781", "grade": "#2c2c2a", "base": "#383835"},
}
# Categórica: 8 slots em ordem fixa (nunca ciclados). Dark = os mesmos matizes, com passos próprios.
CATEGORICA = {
    "claro": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"],
    "escuro": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
}
# Sequencial: um matiz (azul), passos 100 a 700; em modo escuro a âncora inverte (baixo = escuro).
SEQ_AZUL = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6",
            "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
# Emphasis: a série que importa leva o matiz de destaque; o resto, o cinza de menor ênfase.
DESTAQUE = {"claro": CATEGORICA["claro"][0], "escuro": CATEGORICA["escuro"][0]}
CINZA = {"claro": "#898781", "escuro": "#898781"}


def rampa_sequencial(modo: str) -> list[str]:
    """Do menor ao maior valor. No escuro o menor valor se aproxima da superfície (escuro)."""
    return SEQ_AZUL if modo == "claro" else SEQ_AZUL[::-1]


# --- validador (porte de validate_palette.js) -------------------------------------------------------

FAIXA_L = {"claro": (0.43, 0.77), "escuro": (0.48, 0.67)}
PISO_CROMA = 0.10
CVD_ALVO, CVD_PISO = 8.0, 6.0
PISO_VISAO_NORMAL = 15.0
CONTRASTE_MIN = 3.0
MACHADO = {
    "protan": [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
    "deutan": [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]],
    "tritan": [[1.255528, -0.076749, -0.178779], [-0.078411, 0.930809, 0.147602], [0.004733, 0.691367, 0.303900]],
}


def _srgb(hex_: str) -> list[float]:
    h = hex_.strip().lstrip("#")
    return [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]


def _linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lin(hex_: str) -> list[float]:
    return [_linear(c) for c in _srgb(hex_)]


def contraste(a: str, b: str) -> float:
    def lum(h):
        r, g, bl = _lin(h)
        return 0.2126 * r + 0.7152 * g + 0.0722 * bl
    alto, baixo = sorted((lum(a), lum(b)), reverse=True)
    return (alto + 0.05) / (baixo + 0.05)


def _oklab(lin: list[float]) -> list[float]:
    r, g, b = lin
    l = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s]


def oklch(hex_: str) -> tuple[float, float]:
    L, a, b = _oklab(_lin(hex_))
    return L, math.hypot(a, b)


def _simular(hex_: str, tipo: str) -> list[float]:
    r, g, b = _lin(hex_)
    m = MACHADO[tipo]
    return [min(1.0, max(0.0, m[i][0] * r + m[i][1] * g + m[i][2] * b)) for i in range(3)]


def delta_e(h1: str, h2: str, tipo: str | None = None) -> float:
    """Distância euclidiana em OKLab x100; sem `tipo`, visão normal."""
    a = _oklab(_simular(h1, tipo) if tipo else _lin(h1))
    b = _oklab(_simular(h2, tipo) if tipo else _lin(h2))
    return 100 * math.dist(a, b)


def validar(paleta: list[str], modo: str, superficie: str | None = None, pares: str = "adjacentes") -> dict:
    """As verificações calculáveis de uma paleta categórica. `ok` é falso em qualquer FALHA; AVISO exige
    codificação secundária (rótulos diretos, gaps ou tabela)."""
    superficie = superficie or SUPERFICIE[modo]
    lo, hi = FAIXA_L[modo]
    n = len(paleta)
    fora = [(c, round(oklch(c)[0], 3)) for c in paleta if not lo <= oklch(c)[0] <= hi]
    croma = [(c, round(oklch(c)[1], 3)) for c in paleta if oklch(c)[1] < PISO_CROMA]
    lista = [(i, j) for i in range(n) for j in range(i + 1, n)] if pares == "todos" else [(i, i + 1) for i in range(n - 1)]
    pior_cvd = min((delta_e(paleta[i], paleta[j], t), t, paleta[i], paleta[j]) for t in ("protan", "deutan") for i, j in lista) if lista else (99, "", "", "")
    pior_normal = min((delta_e(paleta[i], paleta[j]), paleta[i], paleta[j]) for i, j in lista) if lista else (99, "", "")
    baixo_contraste = [(c, round(contraste(c, superficie), 2)) for c in paleta if contraste(c, superficie) < CONTRASTE_MIN]
    estado_cvd = "ok" if pior_cvd[0] >= CVD_ALVO else "aviso" if pior_cvd[0] >= CVD_PISO else "falha"
    verificacoes = {
        "faixa_de_luminosidade": ("ok" if not fora else "falha", fora),
        "piso_de_croma": ("ok" if not croma else "falha", croma),
        "separacao_daltonismo": (estado_cvd, {"pior_delta_e": round(pior_cvd[0], 1), "tipo": pior_cvd[1], "par": pior_cvd[2:]}),
        "visao_normal": ("ok" if pior_normal[0] >= PISO_VISAO_NORMAL else "falha", {"pior_delta_e": round(pior_normal[0], 1), "par": pior_normal[1:]}),
        "contraste_com_a_superficie": ("ok" if not baixo_contraste else "aviso", baixo_contraste),
    }
    return {"ok": all(v[0] != "falha" for v in verificacoes.values()), "verificacoes": verificacoes}


def validar_rampa_sequencial(passos: list[str], modo: str, superficie: str | None = None) -> dict:
    """Rampa de um só matiz: luminosidade monótona e extremo claro ainda legível (a categórica falha por desenho)."""
    superficie = superficie or SUPERFICIE[modo]
    luz = [oklch(c)[0] for c in passos]
    decrescente = all(a > b for a, b in zip(luz, luz[1:]))
    crescente = all(a < b for a, b in zip(luz, luz[1:]))
    return {"monotona": decrescente or crescente, "luminosidade": [round(x, 3) for x in luz],
            "contraste_do_extremo_mais_visivel": round(max(contraste(c, superficie) for c in passos), 2)}


# --- tema do Streamlit -----------------------------------------------------------------------------------

def modo_atual() -> str:
    """'claro' ou 'escuro', conforme o tema do navegador; sem contexto (testes), claro."""
    try:
        import streamlit as st
        return "escuro" if st.context.theme.type == "dark" else "claro"
    except Exception:
        return "claro"
