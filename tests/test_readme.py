"""README e entrega: os blocos gerados não envelhecem, os links e as imagens existem, as regras de texto do projeto valem
(nada sobre versão anterior ou saída de emprego) e os arquivos de dependências cobrem o que o app importa."""

import ast
import re
import sys
from importlib import metadata
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from src import documentacao
from src.config import CFG, RAIZ

README = (RAIZ / "README.md").read_text(encoding="utf-8")
SECOES = ["O problema de negócio", "O que o produto faz", "Arquitetura", "Dados", "Limpeza e qualidade", "Definição das métricas", "O chatbot",
          "As análises", "Guard-rails e testes", "Como rodar local", "Estrutura de pastas",
          "Limitações", "Implementado e roadmap", "Fonte dos dados e termos de uso"]


def test_readme_tem_as_secoes_do_guia_na_ordem():
    titulos = re.findall(r"^## (\d+)\. (.+)$", README, flags=re.M)
    assert [t[1] for t in titulos] == SECOES and [int(t[0]) for t in titulos] == list(range(1, len(SECOES) + 1))


def test_sumario_aponta_para_titulos_que_existem():
    ancoras = re.findall(r"\]\(#([^)]+)\)", README)
    assert len(ancoras) == len(SECOES)
    gerados = {re.sub(r"[^\w\- ]", "", t.lower()).replace(" ", "-") for t in re.findall(r"^#{2,3} (.+)$", README, flags=re.M)}
    assert set(ancoras) <= gerados, set(ancoras) - gerados


def test_links_e_imagens_locais_existem():
    alvos = [a for a in re.findall(r"\]\(([^)#]+)\)", README) if not a.startswith(("http", "mailto"))]
    assert alvos and all((RAIZ / a).exists() for a in alvos), [a for a in alvos if not (RAIZ / a).exists()]
    assert sum(a.endswith(".png") for a in alvos) >= 6


def test_blocos_gerados_estao_todos_marcados_e_o_diagrama_de_arquitetura_existe():
    abertos = set(re.findall(r"<!-- gerado:(\w+) -->", README))
    fechados = set(re.findall(r"<!-- /gerado:(\w+) -->", README))
    assert abertos == fechados == {"QUALIDADE", "METRICAS", "AVALIACAO", "ESTRUTURA", "ANALISE_RFM", "ANALISE_CLV", "ANALISE_CHURN", "ANALISE_DESCONTO"}
    assert "```mermaid" in README and "Servidor MCP" in README


def test_estrutura_de_pastas_cita_so_o_que_existe_e_nao_esquece_pasta_versionada():
    for caminho, _ in documentacao.ESTRUTURA:
        assert (RAIZ / caminho).exists(), caminho
    import subprocess
    versionados = subprocess.run(["git", "ls-files"], cwd=RAIZ, capture_output=True, text=True).stdout.split()
    topo = {Path(f).parts[0] + ("/" if len(Path(f).parts) > 1 else "") for f in versionados}
    citados = {c.split("/")[0] + ("/" if c.endswith("/") else "") for c, _ in documentacao.ESTRUTURA}
    esquecidos = {t for t in topo if t not in citados and t not in {"README.md", "requirements.txt", "requirements-dev.txt", ".gitignore", ".gitattributes"}}
    assert not esquecidos, esquecidos


def test_readme_e_app_nao_citam_versao_anterior_nem_saida_de_emprego():
    proibidos = ["versão anterior", "versao anterior", "one up", "saída de emprego", "saí do emprego", "não consegui aplicar", "transição de carreira",
                 "implementação anterior"]
    textos = {"README.md": README}
    for pasta in ("app", "src"):
        for arquivo in (RAIZ / pasta).rglob("*.py"):
            textos[str(arquivo.relative_to(RAIZ))] = arquivo.read_text(encoding="utf-8")
    textos["notebook"] = "\n".join(a.read_text(encoding="utf-8") for a in (RAIZ / "notebooks" / "fonte").glob("*.py"))
    for nome, texto in textos.items():
        achados = [p for p in proibidos if p in texto.lower()]
        assert not achados, (nome, achados)


def test_readme_traz_a_rodada_final_completa_e_nao_diz_que_esta_pendente():
    assert "20 de 28 (71%)" in README and "23 de 28 (82%)" in README and "27/28 (96%)" in README
    assert "em duas partes por limite de uso" in README and "q06" in README and "está pendente" not in README
    assert "nenhuma taxa vem de `eval/ULTIMO_VIVO.md`" not in README


def test_readme_nao_promete_app_publicado_nem_dados_no_repositorio():
    for proibido in ("versionado no repositório", "Parquet do repositório", "Publicação no Streamlit", "set GROQ_API_KEY"):
        assert proibido not in README, proibido
    assert "O repositório não contém dados da dunnhumby" in README and "Demonstração em vídeo" in README


def test_numeros_fixos_do_texto_batem_com_o_config():
    assert f"{CFG['janela']['semanas_atuais']} semanas" in README and f"`WEEK_NO - {CFG['janela']['offset_ano_anterior']}`" in README
    assert f"{CFG['analises']['churn']['horizonte_semanas']} semanas sem comprar" in README
    assert f"({CFG['analises']['clv']['margem'] * 100:.0f}%)" in README and f"{CFG['agente']['mcp_ocioso_minutos']} minutos" in README
    assert f"ARI ≥ {CFG['analises']['rfm']['ari_minimo']:.2f}".replace(".", ",") in README
    assert f"eta² ≥ {CFG['analises']['teste_desconto']['eta2_relevante'] * 100:.0f}%" in README


def test_readme_nao_tem_segredo_e_o_modelo_de_segredos_e_so_um_exemplo():
    exemplo = (RAIZ / ".streamlit" / "secrets.toml.example").read_text(encoding="utf-8")
    for texto in (README, exemplo):
        assert not re.search(r"gsk_[A-Za-z0-9]{10,}", texto)
    assert "cole-aqui" in exemplo
    assert ".streamlit/secrets.toml" in (RAIZ / ".gitignore").read_text(encoding="utf-8")


@pytest.mark.skipif(not ((RAIZ / CFG["banco"]["arquivo"]).exists() or (RAIZ / "data" / "processed" / "parquet" / "manifesto.json").exists()),
                    reason="sem dados: rode `python baixar_dados.py` e `python -m src.etl`")
def test_blocos_gerados_do_readme_estao_em_dia_com_as_ferramentas_de_hoje():
    """Roda as quatro análises (cerca de 1 minuto). Se falhar: `venv\\Scripts\\python.exe -m src.documentacao`."""
    from src.nucleo import banco, cache
    anterior = banco._ativo
    try:
        novo = documentacao.aplicar(README, documentacao.calcular_blocos())
    finally:
        banco.fechar_todas()
        banco.definir_banco(anterior)
        cache.limpar()
    assert novo == README, "README velho: rode `venv\\Scripts\\python.exe -m src.documentacao`"


# --- dependências ---------------------------------------------------------------------------------------------------

def _pins(arquivo: str) -> dict[str, str]:
    saida = {}
    for linha in (RAIZ / arquivo).read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith(("#", "-r")):
            continue
        r = Requirement(linha)
        assert len(r.specifier) == 1 and next(iter(r.specifier)).operator == "==", f"{arquivo}: {linha} não está travado"
        saida[canonicalize_name(r.name)] = next(iter(r.specifier)).version
    return saida


def test_requirements_do_app_e_do_desenvolvimento_estao_travados_e_separados():
    app, dev = _pins("requirements.txt"), _pins("requirements-dev.txt")
    assert "-r requirements.txt" in (RAIZ / "requirements-dev.txt").read_text(encoding="utf-8")
    for so_dev in ("pytest", "ipykernel", "nbconvert", "nbclient", "vl-convert-python", "nbformat"):
        assert so_dev not in app and so_dev in dev, so_dev
    assert not set(app) & set(dev)
    assert {"streamlit", "duckdb", "pandas", "scikit-learn", "scipy", "statsmodels", "altair", "mcp", "langchain-mcp-adapters", "langchain-groq"} <= set(app)
    assert 'sys_platform == "win32"' in (RAIZ / "requirements.txt").read_text(encoding="utf-8")       # pywin32 só no Windows


def test_versoes_travadas_sao_as_do_ambiente_em_que_os_testes_passam():
    for arquivo in ("requirements.txt", "requirements-dev.txt"):
        for linha in (RAIZ / arquivo).read_text(encoding="utf-8").splitlines():
            if linha.startswith(("#", "-r")) or not linha.strip():
                continue
            r = Requirement(linha)
            if r.marker is not None and not r.marker.evaluate():
                continue
            assert metadata.version(r.name) == next(iter(r.specifier)).version, linha


def test_tudo_o_que_o_app_importa_esta_no_requirements_do_app():
    app = set(_pins("requirements.txt"))
    donos = metadata.packages_distributions()
    so_desenvolvimento = {"notebook_apoio"}          # usa IPython e vl-convert: ferramenta do notebook, fora do app
    ausentes = set()
    for pasta in ("app", "src"):
        for arquivo in (RAIZ / pasta).rglob("*.py"):
            if arquivo.stem in so_desenvolvimento:
                continue
            for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
                modulos = [a.name for a in no.names] if isinstance(no, ast.Import) else ([no.module] if isinstance(no, ast.ImportFrom) and no.level == 0 and no.module else [])
                for m in modulos:
                    topo = m.split(".")[0]
                    if topo in sys.stdlib_module_names or topo in {"src", "app"}:
                        continue
                    ausentes |= {f"{topo} ({arquivo.name})" for d in [donos.get(topo, [])] if not {canonicalize_name(x) for x in d} & app}
    assert not ausentes, sorted(ausentes)
