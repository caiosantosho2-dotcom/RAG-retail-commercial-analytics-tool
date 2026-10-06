"""A spec é a fonte única: ferramentas, descrições, skills e prompt do agente dizem a mesma coisa. Sem banco, rodam em segundos."""

import inspect
import re
from pathlib import Path

import pytest

from src import agente, mcp_server
from src.config import CFG

RAIZ = Path(__file__).resolve().parent.parent
SPEC = (RAIZ / "docs" / "spec_ferramentas_mcp.md").read_text(encoding="utf-8")
SKILLS = {p.parent.name: p.read_text(encoding="utf-8") for p in sorted((RAIZ / ".claude" / "skills").glob("*/SKILL.md"))}
TODAS_AS_SKILLS = "\n".join(SKILLS.values())
FERRAMENTAS = ["descrever_dados", "executar_consulta", "segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos"]


def _normalizar(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace("`", "").replace('"', "").replace("'", "")).strip()


def _descricoes_da_spec() -> dict[str, str]:
    saida = {}
    for nome, bloco in re.findall(r"### 3\.\d `(\w+)\([^`]*`\n(.*?)(?=\n### |\n## )", SPEC, flags=re.S):
        achado = re.search(r'\*\*Descrição:\*\* "(.*?)"\n', bloco, flags=re.S)
        saida[nome] = _normalizar(achado.group(1))
    return saida


def test_a_spec_lista_exatamente_as_ferramentas_do_servidor():
    assert list(_descricoes_da_spec()) == FERRAMENTAS
    assert list(mcp_server.FERRAMENTAS) == FERRAMENTAS


@pytest.mark.parametrize("nome", FERRAMENTAS)
def test_descricao_da_ferramenta_comeca_pelo_texto_da_spec(nome):
    """A descrição que o modelo lê é o docstring; ele precisa conter a descrição da spec, na ordem."""
    spec = _descricoes_da_spec()[nome]
    docstring = _normalizar(inspect.getdoc(mcp_server.FERRAMENTAS[nome]))
    assert docstring.startswith(spec.rstrip(".")), f"\nspec:      {spec}\ndocstring: {docstring[:len(spec) + 40]}"


def test_skills_tem_nome_igual_a_pasta_descricao_e_tamanho_razoavel():
    assert set(SKILLS) == {"consultas-sql", "analise-estatistica", "qualidade-validacao"}
    for pasta, texto in SKILLS.items():
        cab = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", texto)
        assert cab and cab.group(1) == pasta and len(cab.group(2)) > 80, pasta
        assert len(texto) < 9_000, f"{pasta}: {len(texto)} caracteres (as skills entram no contexto)"


@pytest.mark.parametrize("nome", FERRAMENTAS)
def test_toda_ferramenta_da_spec_aparece_nas_skills(nome):
    assert nome in TODAS_AS_SKILLS


def test_skills_de_analise_dizem_quando_usar_cada_ferramenta_de_analise():
    tabela = SKILLS["analise-estatistica"].split("## Antes de qualquer análise")[0]
    for nome in ("segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos", "executar_consulta"):
        assert nome in tabela


@pytest.mark.parametrize("nome", FERRAMENTAS)
def test_prompt_do_agente_cita_toda_ferramenta(nome):
    assert nome in agente.INSTRUCOES_SISTEMA


def test_skills_nao_repetem_decisoes_ja_substituidas():
    for velho in ("silhueta e/ou cotovelo", "Inativos", "já são perdas", "Rode `descrever_dados()` (ou leia"):
        assert velho not in TODAS_AS_SKILLS, velho
    analise = SKILLS["analise-estatistica"]
    for atual in ("Em pausa", "Margem (25%)", "8 semanas", "eta²", "5 ou mais compras", "regra escrita antes de rodar", "pausa longa"):
        assert atual in analise, atual
    assert "detalhe=" in SKILLS["consultas-sql"] and "soma do desconto / soma do valor bruto" in SKILLS["consultas-sql"]


def test_numeros_citados_nas_skills_batem_com_o_config():
    analise = SKILLS["analise-estatistica"]
    assert f"{CFG['analises']['clv']['margem'] * 100:.0f}%" in analise
    assert f"{CFG['analises']['clv']['horizonte_semanas']} semanas" in analise
    assert f"{CFG['analises']['churn']['horizonte_semanas']} semanas" in analise
    assert f"{CFG['analises']['teste_desconto']['compras_minimas_sensibilidade']} ou mais compras" in analise
    assert f"{CFG['analises']['rfm']['ari_minimo']:.2f}".replace(".", ",") in analise
    assert f"{CFG['consulta']['limite_maximo']}" in SKILLS["consultas-sql"]


def test_skills_e_spec_nao_tem_segredo():
    for texto in (TODAS_AS_SKILLS, SPEC):
        assert not re.search(r"gsk_[A-Za-z0-9]{10,}|GROQ_API_KEY\s*=\s*\S{10,}", texto)
