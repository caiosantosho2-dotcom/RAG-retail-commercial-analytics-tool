"""Avaliador e conjunto de perguntas: um avaliador errado inventa taxa de acerto, então ele também é testado."""

import pytest
import yaml

from eval import avaliador as av
from eval import rodar_avaliacao as ra
from src import agente
from src.config import CFG, RAIZ
from src.nucleo import banco
from src.nucleo.consulta import validar_sql
from tests.fakes import ModeloRoteirizado, chamada, texto


# --- extração de números -------------------------------------------------------------------------

@pytest.mark.parametrize("frase,alvo", [
    ("O ticket médio foi de US$ 31,21.", 31.21), ("ticket de 31.21 dólares", 31.21),
    ("Faturou US$ 65.930,76 no período", 65930.76), ("Faturou $65,930.76 no período", 65930.76),
    ("Cresceu 3,4% contra o ano passado", 3.4), ("cresceu 3.4%", 3.4),
    ("foram 1.645 cestas", 1645), ("foram 1,645 cestas", 1645), ("foram 1645 cestas", 1645),
    ("cerca de 65,9 mil dólares", 65900), ("cerca de US$ 65.9k", 65900), ("2,1 milhões", 2_100_000),
    ("total de 2.068.075 dólares", 2068075), ("15,7%", 15.7),
])
def test_extrai_numero_em_varios_formatos(frase, alvo):
    assert any(abs(v - alvo) < 1e-6 for v in av.extrair_numeros(frase)), av.extrair_numeros(frase)


def test_numero_dentro_da_tolerancia():
    assert av.confere_numero("ticket médio de US$ 31", 31.21)            # arredondou para o inteiro: 0,7%
    assert av.confere_numero("ticket médio de US$ 31,20", 31.2097)
    assert not av.confere_numero("ticket médio de US$ 35", 31.21)
    assert av.confere_numero("cresceu 3,4%", 3.4153, rel=0.02, abs_=0.1)
    assert not av.confere_numero("cresceu 3%", 3.4153, rel=0.02, abs_=0.1)


def test_sinal_e_ignorado_mas_valor_errado_nao_passa():
    assert av.confere_numero("clientes caíram 5,7%", -5.7325, abs_=0.1)
    assert not av.confere_numero("clientes caíram 15,7%", -5.7325, abs_=0.1)


def test_resposta_sem_numero_nao_confere():
    assert not av.confere_numero("não encontrei dados", 31.21)


def test_ids_exigem_inteiro_exato():
    assert av.confere_id("A loja 367 foi a maior", 367)
    assert av.confere_id("produtos 5569230, 5569471 e 8090521", 5569471)
    assert av.confere_id("produto 1.082.185", 1082185) and av.confere_id("produto 1,082,185", 1082185)
    assert not av.confere_id("a loja 3670 foi a maior", 367)
    assert not av.confere_id("faturou 367,5 dólares", 367)      # é decimal, não o id
    assert not av.confere_id("loja 36", 367)


def test_texto_ignora_maiusculas_e_acentos():
    assert av.confere_texto("O departamento GROCERY teve mais desconto", "grocery")
    assert av.confere_texto("categoria Laticínios", "LATICINIOS")
    assert not av.confere_texto("departamento MEAT", "GROCERY")


def test_conferir_exige_todos_os_valores():
    esperados = [{"coluna": "a", "tipo": "numero", "valor": 31.21, "rel": 0.02, "abs": 0.06},
                 {"coluna": "b", "tipo": "id", "valor": 367, "rel": 0, "abs": 0}]
    assert av.conferir("loja 367 com ticket de US$ 31,21", esperados)[0] is True
    ok, detalhe = av.conferir("ticket de US$ 31,21", esperados)
    assert ok is False and [d["achou"] for d in detalhe] == [True, False]


def test_valores_esperados_pega_n_linhas_da_coluna():
    esperados = av.valores_esperados(["STORE_ID", "v"], [[367, 1.0], [406, 2.0], [292, 3.0]],
                                     [{"coluna": "STORE_ID", "tipo": "id", "linhas": 2}, {"coluna": "v"}])
    assert [(e["coluna"], e["valor"]) for e in esperados] == [("STORE_ID", 367), ("STORE_ID", 406), ("v", 1.0)]


# --- o conjunto de perguntas ------------------------------------------------------------------------

PERGUNTAS = yaml.safe_load((ra.PERGUNTAS).read_text(encoding="utf-8"))


def test_ha_vinte_perguntas_com_ids_unicos_e_campos_obrigatorios():
    assert len(PERGUNTAS) == 20 and len({p["id"] for p in PERGUNTAS}) == 20
    for p in PERGUNTAS:
        assert {"id", "pergunta", "regra", "ferramenta_esperada", "termos_glossario", "sql_esperado",
                "esperado", "sanidade"} <= p.keys(), p["id"]
        assert p["ferramenta_esperada"] in ("executar_consulta", "descrever_dados")
        assert all(isinstance(x, (int, float)) for x in p["sanidade"]) and p["sanidade"][0] < p["sanidade"][1], p["id"]
        assert all(e["coluna"] for e in p["esperado"]) and p["regra"].strip()


def test_inclui_as_perguntas_do_guia():
    todas = " ".join(p["pergunta"].lower() for p in PERGUNTAS)
    for trecho in ("loja 367 vendeu de laticínios", "maior ticket médio", "clientes compraram na loja 367",
                   "desconto de cupom", "marca própria", "penetração", "alta frequência", "80% do faturamento",
                   "campanha 18", "menos clientes, menos idas"):
        assert trecho in todas, trecho


BANCO = RAIZ / CFG["banco"]["arquivo"]
precisa_do_banco = pytest.mark.skipif(not BANCO.exists(), reason="rode `python -m src.etl`")


@pytest.fixture
def banco_real():
    banco.definir_banco(BANCO)
    yield
    banco.fechar_todas()
    banco.definir_banco(None)


@precisa_do_banco
def test_todo_sql_esperado_passa_nos_guard_rails_e_na_faixa_de_sanidade(banco_real):
    cur = banco.cursor()
    for p in PERGUNTAS:
        validar_sql(cur, p["sql_esperado"])
        e = ra.resolver_esperado(p)
        assert e["ok"], (p["id"], e["erro"])
        assert e["esperados"], p["id"]


@precisa_do_banco
def test_modo_oraculo_acerta_tudo_e_o_glossario_recupera_os_termos(banco_real):
    r = ra.resumo(ra.rodar_oraculo(PERGUNTAS), "oraculo")
    assert r["oraculo_ok"] == 1.0 and r["glossario_ok"] == 1.0


@precisa_do_banco
def test_valores_esperados_conferem_por_um_segundo_caminho(banco_real):
    """Ticket, lojas só na atual e clientes ativos recalculados direto no banco, sem as views de métricas."""
    por_id = {p["id"]: ra.resolver_esperado(p)["esperados"] for p in PERGUNTAS}
    con = banco.cursor()   # mesma conexão configurada do núcleo (o DuckDB não abre o arquivo com outra config)
    ticket = con.execute("""SELECT SUM(f.SALES_VALUE) / COUNT(DISTINCT f.BASKET_ID) FROM fato_transacoes f
        JOIN dim_data d ON d.data_id = f.data_id WHERE d.WEEK_NO BETWEEN 76 AND 101""").fetchone()[0]
    so_atual = con.execute("""WITH l AS (SELECT DISTINCT f.STORE_ID, d.WEEK_NO BETWEEN 76 AND 101 AS atual, d.WEEK_NO BETWEEN 24 AND 49 AS base
        FROM fato_transacoes f JOIN dim_data d ON d.data_id = f.data_id)
        SELECT COUNT(*) FROM (SELECT STORE_ID FROM l GROUP BY 1 HAVING BOOL_OR(atual) AND NOT BOOL_OR(base))""").fetchone()[0]
    ativos = con.execute("""SELECT COUNT(*) FROM (SELECT f.household_key FROM fato_transacoes f JOIN dim_data d ON d.data_id = f.data_id
        WHERE d.WEEK_NO BETWEEN 76 AND 101 GROUP BY 1 HAVING MAX(d.WEEK_NO) >= 101 - 8 + 1)""").fetchone()[0]
    assert float(por_id["q02"][0]["valor"]) == pytest.approx(float(ticket), abs=1e-3)   # a ferramenta arredonda em 4 casas
    assert por_id["q18"][0]["valor"] == so_atual
    assert por_id["q20"][0]["valor"] == ativos


# --- modo vivo, com modelo roteirizado ------------------------------------------------------------------

def rodar_vivo_com(monkeypatch, resposta_final: str, ids=("q02",)):
    p = next(p for p in PERGUNTAS if p["id"] == ids[0])
    llm = ModeloRoteirizado(roteiro=[chamada(p["sql_esperado"]), texto(resposta_final)], vistas=[])
    monkeypatch.setenv("GROQ_API_KEY", "chave-de-teste")
    original = agente.criar_agente   # guardada antes da troca: ra.agente é o mesmo módulo
    monkeypatch.setattr(ra.agente, "criar_agente", lambda **kw: original(llm=llm))
    monkeypatch.setattr(ra.time, "sleep", lambda s: None)
    return ra.rodar_vivo([p], "llama-3.3-70b-versatile", log=lambda *_: None)[0]


@precisa_do_banco
def test_modo_vivo_marca_acerto_quando_a_resposta_tem_o_numero(banco_real, monkeypatch):
    r = rodar_vivo_com(monkeypatch, "O ticket médio da janela atual foi de US$ 31,21.")
    assert r["acerto"] is True and r["numero_na_consulta"] is True and r["ferramenta_certa"] is True
    assert r["tokens"] == 220 and r["chamadas_llm"] == 2 and r["erro"] is None


@precisa_do_banco
def test_modo_vivo_marca_erro_quando_a_resposta_tem_outro_numero(banco_real, monkeypatch):
    r = rodar_vivo_com(monkeypatch, "O ticket médio da janela atual foi de US$ 45,00.")
    assert r["acerto"] is False and r["numero_na_consulta"] is True and r["ferramenta_certa"] is True


@precisa_do_banco
def test_modo_vivo_sem_chave_para_com_mensagem_clara(banco_real, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="GROQ_API_KEY"):
        ra.rodar_vivo(PERGUNTAS[:1], "llama-3.3-70b-versatile")


def test_resumo_calcula_as_taxas():
    base = {"acerto": True, "numero_na_consulta": True, "ferramenta_certa": True, "glossario_ok": True,
            "tokens": 100, "tempo_s": 2.0, "consultas_com_erro": 0}
    r = ra.resumo([base, {**base, "acerto": False, "tokens": 300, "consultas_com_erro": 1}], "vivo")
    assert r["taxa_acerto"] == 0.5 and r["tokens_medios"] == 200 and r["consultas_com_erro"] == 1
