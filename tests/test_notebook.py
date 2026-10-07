"""Notebook narrado: estrutura (cada análise abre com a decisão e fecha com "e daí?"), o arquivo salvo traz as saídas sem erro e
confere com as ferramentas (não está velho), e o notebook roda do zero. O notebook não recalcula nada: os números vêm do núcleo."""

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import nbformat
import pytest

from src.config import CFG, RAIZ

PASTA = RAIZ / "notebooks"
SALVO = PASTA / "analise_clientes_dunnhumby.ipynb"
BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


def _construtor():
    spec = importlib.util.spec_from_file_location("construir_notebook", PASTA / "construir_notebook.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def montado():
    return _construtor().montar()


@pytest.fixture(scope="module")
def salvo():
    assert SALVO.exists(), "rode `venv\\Scripts\\python.exe notebooks\\construir_notebook.py`"
    return nbformat.read(SALVO, as_version=4)


def textos_de_saida(nb) -> str:
    partes = []
    for c in nb.cells:
        for o in c.get("outputs", []):
            d = o.get("data", {})
            partes.append(d.get("text/markdown") or d.get("text/plain") or o.get("text", ""))
    return "\n".join(partes)


# --- estrutura (sem banco) -----------------------------------------------------------------------------------------

def test_todo_codigo_do_notebook_compila(montado):
    for i, c in enumerate(montado.cells):
        if c.cell_type == "code":
            ast.parse(c.source, filename=f"celula_{i}")


def test_secoes_na_ordem_da_narrativa(montado):
    titulos = [re.match(r"## (\d)\. (.+)", l).group(0) for c in montado.cells if c.cell_type == "markdown" for l in c.source.splitlines() if l.startswith("## ")]
    assert [t[3] for t in titulos] == list("012345678")
    nomes = " ".join(titulos).lower()
    for trecho in ("resumo", "dados e qualidade", "métricas", "rfm", "clv", "pausa", "teste de hipótese", "costura", "reprodutibilidade"):
        assert trecho in nomes, trecho


def test_cada_analise_abre_com_a_decisao_e_fecha_com_o_bloco_e_dai(montado):
    secoes, atual = {}, None
    for c in montado.cells:
        if c.cell_type == "markdown":
            for l in c.source.splitlines():
                achou = re.match(r"## ([1-6])\. ", l)
                if achou:
                    atual = achou.group(1)
                    secoes[atual] = {"decisao": False, "e_dai": False}
            if atual and "Decisão que esta seção apoia" in c.source:
                secoes[atual]["decisao"] = True
        elif atual and "na.e_dai(" in c.source:
            secoes[atual]["e_dai"] = True
    assert set(secoes) == set("123456")
    assert all(v["decisao"] and v["e_dai"] for v in secoes.values()), secoes


def test_o_notebook_nao_recalcula_metricas_por_conta_propria(montado):
    codigo = "\n".join(c.source for c in montado.cells if c.cell_type == "code")
    for ferramenta in ("segmentar_clientes()", "calcular_clv()", "prever_churn()", "testar_desconto_entre_segmentos()"):
        assert ferramenta in codigo
    assert "KMeans" not in codigo and "LogisticRegression" not in codigo and "kruskal(" not in codigo   # modelos ficam no núcleo
    assert "api_key" not in codigo.lower() and "GROQ" not in codigo


def test_graficos_vem_do_modulo_do_app_e_o_texto_nao_cita_versao_anterior(montado):
    codigo = "\n".join(c.source for c in montado.cells if c.cell_type == "code")
    assert codigo.count("graficos.grafico_") >= 13 and "alt.Chart" not in codigo
    tudo = "\n".join(c.source for c in montado.cells).lower()
    for proibido in ("versão anterior", "implementação anterior", "one up", "saída de emprego"):
        assert proibido not in tudo, proibido


def test_numeros_de_resultado_nao_estao_digitados_nas_celulas_de_texto(montado):
    """O texto fixo explica o método. Resultado (K escolhido, CLV, AUC, p-valor) vem de célula de código."""
    fixo = "\n".join(c.source for c in montado.cells if c.cell_type == "markdown")
    for digitado in ("US$ 820", "0,853", "0,0085", "22,9%", "71%", "AUC 0,85", "K = 4", "K=4"):
        assert digitado not in fixo, digitado


# --- arquivo salvo (com as saídas) ------------------------------------------------------------------------------------

def test_arquivo_salvo_tem_as_mesmas_celulas_do_construtor_e_nenhum_erro(salvo, montado):
    assert [c.source for c in salvo.cells] == [c.source for c in montado.cells], "notebook salvo desatualizado: rode construir_notebook.py"
    erros = [(i, o.ename) for i, c in enumerate(salvo.cells) for o in c.get("outputs", []) if o.output_type == "error"]
    assert not erros, erros
    sem_saida = [i for i, c in enumerate(salvo.cells) if c.cell_type == "code" and not c.get("outputs") and "na." in c.source and "na.iniciar" not in c.source]
    assert not sem_saida, f"células que mostram resultado e estão sem saída: {sem_saida}"


def test_arquivo_salvo_traz_os_graficos_como_imagem_e_vega_lite_e_cabe_no_git(salvo):
    graficos = [o for c in salvo.cells for o in c.get("outputs", []) if "image/png" in o.get("data", {})]
    assert len(graficos) >= 13
    assert all(any(m.startswith("application/vnd.vegalite") for m in o["data"]) for o in graficos)
    assert SALVO.stat().st_size < 8_000_000


def test_cada_bloco_e_dai_do_arquivo_salvo_tem_os_quatro_itens(salvo):
    blocos = [o["data"]["text/markdown"] for c in salvo.cells for o in c.get("outputs", []) if "text/markdown" in o.get("data", {}) and "**E daí?**" in o["data"]["text/markdown"]]
    assert len(blocos) == 6
    for b in blocos:
        for rotulo in ("Conclusão.", "Ação recomendada.", "Impacto estimado.", "Limitações."):
            assert rotulo in b


@precisa_do_banco
def test_arquivo_salvo_confere_com_as_ferramentas_de_hoje(salvo):
    """Se a base, os parâmetros ou o código das análises mudarem, o notebook salvo fica velho e este teste avisa."""
    from src import carga
    from src.nucleo import banco, cache
    from src.nucleo.clv import calcular_clv
    from src.nucleo.churn import prever_churn
    from src.nucleo.rfm import segmentar_clientes
    from src.nucleo.teste_desconto import testar_desconto_entre_segmentos

    banco.definir_banco(BANCO)
    cache.limpar()
    try:
        versao = carga.relatorio(BANCO)["versao_base"]
        saida = textos_de_saida(salvo)
        assert f"`{versao}`" in saida
        for ferramenta in (segmentar_clientes, calcular_clv, prever_churn, testar_desconto_entre_segmentos):
            r = ferramenta()
            assert r["e_dai"]["conclusao"] in saida and r["e_dai"]["limitacoes"] in saida, ferramenta.__name__
        clv = calcular_clv()
        assert f"{round(clv['total']['clv_total_usd']):,}".replace(",", ".") in saida
    finally:
        banco.fechar_todas()
        banco.definir_banco(None)
        cache.limpar()


@precisa_do_banco
def test_notebook_roda_do_zero_sem_erro_e_reproduz_o_arquivo_salvo(salvo):
    """Executa tudo de novo (inclui subir o servidor MCP e comparar os números). Lento: cerca de 1 a 2 minutos."""
    construtor = _construtor()
    refeito = construtor.executar(construtor.montar())
    erros = [(i, o.ename) for i, c in enumerate(refeito.cells) for o in c.get("outputs", []) if o.output_type == "error"]
    assert not erros, erros
    assert textos_de_saida(refeito) == textos_de_saida(salvo)         # mesmos números, mesmos textos


def test_imagens_do_readme_vem_do_notebook_salvo_e_sao_identicas_aos_graficos():
    import base64
    nomes = _construtor().NOMES_DAS_IMAGENS
    salvo_ = nbformat.read(SALVO, as_version=4)
    pngs = [o["data"]["image/png"] for c in salvo_.cells for o in c.get("outputs", []) if "image/png" in o.get("data", {})]
    assert len(pngs) == len(nomes) == 13
    for nome, png in zip(nomes, pngs):
        arquivo = PASTA / "imagens" / f"{nome}.png"
        assert arquivo.exists() and arquivo.read_bytes() == base64.b64decode(png), nome
