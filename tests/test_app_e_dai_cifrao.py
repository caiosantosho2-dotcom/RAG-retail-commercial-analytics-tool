"""Bloco "E daí?" das 4 abas de análise: título curto sem estatística, estatística em "Detalhes técnicos", e nenhum "$" sem escape.

Dois "US$" no mesmo texto viram fórmula no markdown do Streamlit (o trecho entre eles sai como bloco matemático)."""

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import carga
from src.config import CFG, RAIZ
from src.nucleo import banco, cache
from src.ui.componentes import md

APP = str(Path(__file__).resolve().parent.parent / "app" / "app.py")
BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")
ABAS_DE_ANALISE = {2: "Segmentos (RFM)", 3: "Valor do cliente (CLV)", 4: "Risco de pausa (churn)", 5: "Desconto por segmento"}
ESTATISTICA = re.compile(r"\bAUC\b|\bIC\b|\beta\b|eta²|\bp\s*[=<]|Kruskal|\bARI\b|silhueta|limiar|precisão|recall|bootstrap|Holm", re.I)
CIFRAO_SEM_ESCAPE = re.compile(r"(?<!\\)\$")


def resultado_real():
    rel = carga.relatorio(BANCO)
    return carga.ResultadoCarga(BANCO, rel["versao_base"], "pasta", True, carga.resumir(BANCO), [])


@pytest.fixture(scope="module")
def tela_real():
    mp = pytest.MonkeyPatch()
    mp.setattr(carga, "carregar", lambda **kw: resultado_real())
    cache.limpar()
    at = AppTest.from_file(APP, default_timeout=600).run()
    yield at
    banco.fechar_todas()
    mp.undo()


def test_md_escapa_o_cifrao_fora_do_codigo_e_nao_escapa_duas_vezes():
    assert md("US$ 1.000 e US$ 2.000") == "US\\$ 1.000 e US\\$ 2.000"
    assert md("US\\$ 1.000") == "US\\$ 1.000"
    assert md("use `SELECT '$'` e US$ 5") == "use `SELECT '$'` e US\\$ 5"
    assert not CIFRAO_SEM_ESCAPE.search(md("US$ 1 ... US$ 2 ... US$ 3"))


@precisa_do_banco
@pytest.mark.parametrize("idx", list(ABAS_DE_ANALISE))
def test_titulo_curto_sem_estatistica_e_detalhes_tecnicos_fechados(tela_real, idx):
    aba = tela_real.tabs[idx]
    titulo = next(m.value for m in aba.markdown if m.value.startswith("### "))[4:]
    assert len(titulo.split()) <= 20, titulo
    assert not ESTATISTICA.search(titulo), titulo
    detalhes = [e for e in aba.expander if e.label == "Detalhes técnicos"]
    assert len(detalhes) == 1
    assert detalhes[0].proto.expanded is False


@precisa_do_banco
@pytest.mark.parametrize("idx", list(ABAS_DE_ANALISE))
def test_nenhum_cifrao_sem_escape_nos_textos_da_aba(tela_real, idx):
    aba = tela_real.tabs[idx]
    textos = [m.value for m in aba.markdown] + [c.value for c in aba.caption] + [i.value for i in aba.info]
    textos += [w.value for w in aba.warning] + [e.value for e in aba.error] + [m.label for m in aba.metric] + [m.value for m in aba.metric]
    assert any("US" in t for t in textos)
    assert [t for t in textos if CIFRAO_SEM_ESCAPE.search(t)] == []
