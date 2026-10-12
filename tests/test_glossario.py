"""Glossário de negócio: recuperação dos termos certos, fonte única das fórmulas e referências válidas."""

import re

import duckdb
import pytest

from src import views
from src.config import CFG, RAIZ
from src.glossario_rag import buscar_termos_relevantes, pontuar
from src.glossario_termos import GLOSSARIO

CASOS = [   # pergunta -> termos que precisam estar entre os 4 mais relevantes
    ("Quanto a loja 367 vendeu de laticínios no último mês?", {"Loja", "Laticínios", "Último mês", "Faturamento"}),
    ("Qual loja teve o maior ticket médio nas últimas 4 semanas?", {"Ticket médio", "Loja", "Último mês"}),
    ("Quantos clientes compraram na filial 367 no último mês?", {"Clientes", "Loja", "Último mês"}),
    ("Qual departamento teve mais desconto de cupom?", {"Desconto de cupom", "Categoria"}),
    ("Quais os 5 produtos mais vendidos da categoria soft drinks?", {"Produto", "Categoria"}),
    # "Loja" fica de fora do top 4: o termo Árvore de vendas já aponta para vw_yoy_loja (por loja).
    ("A venda da loja 367 caiu contra o ano passado por menos clientes, menos idas ou menos gasto por ida?",
     {"Árvore de vendas", "Ano anterior"}),
    ("Quanto a marca própria cresceu em laticínios contra o mesmo período do ano passado?",
     {"Marca própria", "Laticínios", "Ano anterior", "Variação contra o ano anterior"}),
    ("Qual a penetração da categoria cheese no último trimestre?", {"Penetração", "Último trimestre", "Categoria"}),
    ("Quais produtos são mais comprados pelos clientes de alta frequência?", {"Cliente de alta frequência", "Produto"}),
    ("Qual departamento concentra 80% do faturamento?", {"Curva ABC", "Categoria", "Faturamento"}),
    ("Quantos households resgataram cupom da campanha 18 e quanto gastaram?", {"Campanha"}),
    ("Qual o percentual de desconto da janela atual?", {"Percentual de desconto", "Janela atual"}),
    ("Quantas lojas ficaram fora da comparação com o ano passado?", {"Like-for-like", "Ano anterior"}),
    ("Qual a renda dos clientes?", {"Demografia"}),
    ("Quais as filiais com amostra pequena?", {"Loja", "Amostra pequena"}),
]


def nomes(pergunta, k=4):
    return {item["termo"].split(" (")[0] for _, item in pontuar(pergunta)[:k]}


@pytest.mark.parametrize("pergunta,esperados", CASOS)
def test_termos_esperados_entre_os_mais_relevantes(pergunta, esperados):
    achados = nomes(pergunta)
    faltaram = esperados - achados
    assert len(faltaram) <= (1 if len(esperados) >= 4 else 0), f"faltaram {faltaram}; achou {achados}"


@pytest.mark.parametrize("pergunta", ["bom dia", "obrigado", "", "   "])
def test_perguntas_sem_assunto_nao_injetam_nada(pergunta):
    assert buscar_termos_relevantes(pergunta) == ""


def test_pergunta_sobre_vendedor_nao_cria_o_conceito():
    """Não existe vendedor no dataset: o glossário não o define (a regra está no prompt do sistema)."""
    saida = buscar_termos_relevantes("qual o vendedor que mais vendeu?").lower()
    assert "vendedor:" not in saida and "- vendedor" not in saida


def test_formato_da_saida_uma_linha_por_termo():
    saida = buscar_termos_relevantes("qual o ticket médio da loja 367?")
    linhas = saida.splitlines()
    assert 1 <= len(linhas) <= CFG["agente"]["glossario_top_k"]
    assert all(l.startswith("- ") and ": " in l for l in linhas)


def test_sinonimo_explicito_traz_o_termo_mesmo_com_pergunta_longa():
    assert "Loja" in nomes("Quantos clientes compraram na filial 367 no último mês?")
    assert "Loja" in nomes("Como foi a unidade 12 em relação às outras lojas da rede nas últimas semanas?", k=5)


def test_aceita_plural_e_acento():
    assert "Faturamento" in nomes("quanto foi o faturamento?") and "Faturamento" in nomes("quanto foram as vendas?")
    assert "Loja" in nomes("quais as filiais maiores?")


def test_glossario_nao_trata_vendedor_como_conceito():
    assert not any(re.search(r"vendedor", i["termo"], re.I) for i in GLOSSARIO)
    assert not any("vendedora" in i["definicao"].lower() for i in GLOSSARIO)


def test_formulas_das_metricas_vem_da_fonte_unica():
    por_metrica = {nome: (f, v) for nome, _, f, v in views.METRICAS}
    for item in GLOSSARIO:
        if "Fórmula:" in item["definicao"]:
            trecho = item["definicao"].split("Fórmula:")[1].split(". View:")[0].strip()
            assert any(trecho == f for f, _ in por_metrica.values()), f"fórmula fora de views.METRICAS: {trecho}"


def test_toda_metrica_tem_termo_no_glossario():
    com_formula = {i["definicao"].split("Fórmula:")[1].split(". View:")[0].strip() for i in GLOSSARIO if "Fórmula:" in i["definicao"]}
    sem_termo = [n for n, _, f, _ in views.METRICAS if f not in com_formula]
    assert sem_termo == [], f"métricas sem termo no glossário: {sem_termo}"


def test_views_citadas_existem():
    existentes = {v[0] for v in views.VIEWS}
    # `vw_yoy_*` (curinga) não é o nome de uma view: o `(?!\*)` descarta essas citações.
    citadas = {m for i in GLOSSARIO for m in re.findall(r"\bvw_[a-z_]+\b(?!\*)", i["definicao"])}
    assert citadas <= existentes, citadas - existentes


# --- contra o banco real: toda coluna e tabela citada precisa existir ----------------------------------

BANCO = RAIZ / CFG["banco"]["arquivo"]


@pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")
def test_colunas_e_tabelas_citadas_existem_no_banco_real():
    con = duckdb.connect(str(BANCO), read_only=True)
    colunas = {c.lower() for (c,) in con.execute("SELECT DISTINCT column_name FROM information_schema.columns").fetchall()}
    tabelas = {t.lower() for (t,) in con.execute("SELECT DISTINCT table_name FROM information_schema.tables").fetchall()}
    con.close()
    permitidos = {"quantile_cont"}   # função SQL citada de propósito
    inexistentes = set()
    for item in GLOSSARIO:
        texto = item["definicao"]
        for token in re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", texto) + re.findall(r"\b[A-Z]+(?:_[A-Z]+)+\b", texto):
            if token.lower() not in colunas | tabelas | permitidos:
                inexistentes.add((item["termo"].split(" (")[0], token))
    assert inexistentes == set(), inexistentes


@pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")
def test_commodities_de_laticinios_existem_e_tem_venda():
    con = duckdb.connect(str(BANCO), read_only=True)
    lista = re.search(r"COMMODITY_DESC IN \((.*?)\)", next(i["definicao"] for i in GLOSSARIO if i["termo"].startswith("Laticínios"))).group(1)
    achadas = con.execute(f"SELECT COUNT(DISTINCT COMMODITY_DESC) FROM dim_produto WHERE COMMODITY_DESC IN ({lista})").fetchone()[0]
    con.close()
    assert achadas == lista.count("'") // 2


def test_fieis_e_do_segmento_rfm_e_nao_de_cliente_de_alta_frequencia():
    alta = next(i for i in GLOSSARIO if i["termo"].startswith("Cliente de alta frequência"))
    assert "fiéis" not in alta["termo"].lower() and "Não é o segmento Fiéis" in alta["definicao"]
    for pergunta in ("Que parcela do faturamento vem dos clientes Fiéis?", "Qual a mediana do desconto dos clientes Fiéis?"):
        primeiro = pontuar(pergunta)[0][1]["termo"]
        assert primeiro.startswith("Segmentação, CLV"), (pergunta, primeiro)
    assert buscar_termos_relevantes("Os 3 produtos que mais faturam entre os clientes de alta frequência").count("Cliente de alta frequência") == 1
