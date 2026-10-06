"""Carga por upload e por pasta: formatos, tabelas opcionais, prioridade, cache e mensagens de erro."""

import io

import pandas as pd
import pytest

from src import carga
from src.etl import ErroCarga
from src.nucleo import banco
from tests.test_etl_regras import CABECALHO_TRANS, OUTROS, PRODUTOS, TRANSACOES


@pytest.fixture(autouse=True)
def limpar_banco():
    yield
    banco.fechar_todas()
    banco.definir_banco(None)


def texto_transacoes(cabecalho=CABECALHO_TRANS, linhas=TRANSACOES):
    return "\n".join([cabecalho, *linhas])


def upload_csv(**extras) -> dict[str, bytes]:
    base = {"transaction_data.csv": texto_transacoes().encode(), "product.csv": "\n".join(PRODUTOS).encode()}
    return {**base, **{k: v.encode() for k, v in extras.items()}}


def xlsx(abas: dict[str, str]) -> bytes:
    saida = io.BytesIO()
    with pd.ExcelWriter(saida, engine="openpyxl") as w:
        for nome, texto in abas.items():
            pd.read_csv(io.StringIO(texto), dtype=str, keep_default_na=False).to_excel(w, sheet_name=nome, index=False)
    return saida.getvalue()


def consulta(resultado, sql):
    return banco.cursor(resultado.caminho_banco).execute(sql).fetchall()


def test_upload_com_so_as_duas_tabelas_obrigatorias(tmp_path):
    r = carga.carregar(upload=upload_csv(), pasta_bancos=tmp_path)
    assert r.origem == "upload" and not r.reaproveitado and r.caminho_banco.exists()
    assert any("hh_demographic" in a and "ficam vazias" in a for a in r.avisos)
    assert consulta(r, "SELECT COUNT(*), SUM(tem_demografia::INT) FROM dim_household") == [(3, 0)]
    assert consulta(r, "SELECT COUNT(*) FROM campaign_desc") == [(0,)]
    consulta(r, "SELECT * FROM vw_contexto_periodo")   # a view de contexto não quebra sem as tabelas de campanha
    assert r.resumo["linhas_brutas"] == 9 and r.resumo["linhas_vendas"] == 4
    assert r.resumo["lojas"] == 2 and r.resumo["households"] == 3 and r.resumo["reconciliacao_ok"] is True
    assert r.resumo["periodo"].startswith("2016-01-01")


def test_banco_fica_ativo_para_as_ferramentas(tmp_path):
    from src.nucleo.consulta import executar_consulta
    r = carga.carregar(upload=upload_csv(), pasta_bancos=tmp_path)
    assert executar_consulta("SELECT COUNT(*) AS n FROM fato_transacoes")["linhas"] == [[4]]
    assert executar_consulta("SELECT 1")["versao_base"] == r.versao_base


def test_upload_com_todas_as_tabelas_nao_avisa_de_opcionais(tmp_path):
    extras = {f"{t}.csv": c for t, c in OUTROS.items()}
    r = carga.carregar(upload=upload_csv(**extras), pasta_bancos=tmp_path)
    assert not any("ficam vazias" in a for a in r.avisos)
    assert consulta(r, "SELECT SUM(tem_demografia::INT) FROM dim_household") == [(1,)]


def test_excel_com_uma_aba_por_tabela(tmp_path):
    arquivo = xlsx({"transaction_data": texto_transacoes(), "product": "\n".join(PRODUTOS)})
    r = carga.carregar(upload={"exportacao_bi.xlsx": arquivo}, pasta_bancos=tmp_path)
    assert r.resumo["linhas_brutas"] == 9 and r.resumo["linhas_vendas"] == 4


def test_excel_um_arquivo_por_tabela_com_nome_livre_de_acentos_e_espacos(tmp_path):
    upload = {"Transaction Data.xlsx": xlsx({"Planilha1": texto_transacoes()}),
              "PRODUCT.xlsx": xlsx({"dados": "\n".join(PRODUTOS)})}
    r = carga.carregar(upload=upload, pasta_bancos=tmp_path)
    assert r.resumo["linhas_vendas"] == 4


def test_excel_e_csv_dao_o_mesmo_resultado(tmp_path):
    a = carga.carregar(upload=upload_csv(), pasta_bancos=tmp_path / "a")
    b = carga.carregar(upload={"x.xlsx": xlsx({"transaction_data": texto_transacoes(), "product": "\n".join(PRODUTOS)})},
                       pasta_bancos=tmp_path / "b")
    sql = "SELECT household_key, BASKET_ID, data_id, STORE_ID, PRODUCT_ID, QUANTITY, SALES_VALUE, hora " \
          "FROM fato_transacoes ORDER BY ALL"
    assert consulta(a, sql) == consulta(b, sql)


def test_cabecalho_em_minusculas_e_aceito(tmp_path):
    cab = CABECALHO_TRANS.lower()
    r = carga.carregar(upload={"transaction_data.csv": texto_transacoes(cab).encode(),
                               "product.csv": "\n".join(PRODUTOS).lower().encode()}, pasta_bancos=tmp_path)
    assert r.resumo["linhas_vendas"] == 4


def test_pasta_e_reaproveitada_quando_a_versao_nao_muda(tmp_path):
    pasta = tmp_path / "dados"
    pasta.mkdir()
    for nome, conteudo in upload_csv().items():
        (pasta / nome).write_bytes(conteudo)
    bancos = tmp_path / "bancos"
    primeira = carga.carregar(pastas=[pasta], pasta_bancos=bancos)
    segunda = carga.carregar(pastas=[pasta], pasta_bancos=bancos)
    assert primeira.origem == "pasta" and not primeira.reaproveitado
    assert segunda.reaproveitado and segunda.caminho_banco == primeira.caminho_banco
    assert segunda.versao_base == primeira.versao_base
    assert len(list(bancos.glob("*.duckdb"))) == 1


def test_mudar_o_arquivo_gera_nova_versao(tmp_path):
    pasta = tmp_path / "dados"
    pasta.mkdir()
    for nome, conteudo in upload_csv().items():
        (pasta / nome).write_bytes(conteudo)
    bancos = tmp_path / "bancos"
    antes = carga.carregar(pastas=[pasta], pasta_bancos=bancos)
    (pasta / "transaction_data.csv").write_text(texto_transacoes().replace("5.00", "6.00"), encoding="utf-8")
    depois = carga.carregar(pastas=[pasta], pasta_bancos=bancos)
    assert depois.versao_base != antes.versao_base and not depois.reaproveitado
    assert len(list(bancos.glob("*.duckdb"))) == 2


def test_mudar_parametro_do_config_invalida_o_cache(tmp_path):
    import copy
    from src.config import CFG
    pasta = tmp_path / "dados"
    pasta.mkdir()
    for nome, conteudo in upload_csv().items():
        (pasta / nome).write_bytes(conteudo)
    cfg2 = copy.deepcopy(CFG)
    cfg2["metricas"]["cliente_ativo_semanas"] = 4
    a = carga.carregar(pastas=[pasta], pasta_bancos=tmp_path / "b")
    b = carga.carregar(pastas=[pasta], pasta_bancos=tmp_path / "b", cfg=cfg2)
    assert a.versao_base != b.versao_base and not b.reaproveitado


def test_upload_tem_prioridade_sobre_a_pasta(tmp_path):
    pasta = tmp_path / "dados"
    pasta.mkdir()
    for nome, conteudo in upload_csv().items():
        (pasta / nome).write_bytes(conteudo)
    so_uma_venda = texto_transacoes(linhas=TRANSACOES[:1]).encode()
    r = carga.carregar(upload={"transaction_data.csv": so_uma_venda, "product.csv": "\n".join(PRODUTOS).encode()},
                       pastas=[pasta], pasta_bancos=tmp_path / "bancos")
    assert r.origem == "upload" and r.resumo["linhas_brutas"] == 1
    sem_upload = carga.carregar(pastas=[pasta], pasta_bancos=tmp_path / "bancos")
    assert sem_upload.origem == "pasta" and sem_upload.resumo["linhas_brutas"] == 9


def test_pasta_procura_na_ordem_e_usa_a_primeira_com_dados(tmp_path):
    vazia, cheia = tmp_path / "vazia", tmp_path / "cheia"
    vazia.mkdir(), cheia.mkdir()
    for nome, conteudo in upload_csv().items():
        (cheia / nome).write_bytes(conteudo)
    r = carga.carregar(pastas=[vazia, tmp_path / "nao_existe", cheia], pasta_bancos=tmp_path / "bancos")
    assert r.origem == "pasta" and r.resumo["linhas_brutas"] == 9


# --- Erros com mensagem clara -----------------------------------------------------------------

def test_sem_nenhum_dado(tmp_path):
    with pytest.raises(ErroCarga, match="Nenhum dado encontrado"):
        carga.carregar(pastas=[tmp_path / "vazia"], pasta_bancos=tmp_path / "b")


def test_falta_arquivo_obrigatorio_diz_quais(tmp_path):
    with pytest.raises(ErroCarga) as e:
        carga.carregar(upload={"product.csv": "\n".join(PRODUTOS).encode()}, pasta_bancos=tmp_path)
    assert "transaction_data" in str(e.value) and "obrigatórios" in str(e.value)


def test_coluna_faltando_diz_arquivo_e_coluna(tmp_path):
    sem_valor = texto_transacoes(CABECALHO_TRANS.replace("SALES_VALUE,", "VALOR,")).encode()
    with pytest.raises(ErroCarga) as e:
        carga.carregar(upload={"transaction_data.csv": sem_valor, "product.csv": "\n".join(PRODUTOS).encode()},
                       pasta_bancos=tmp_path)
    assert "transaction_data.csv" in str(e.value) and "SALES_VALUE" in str(e.value)


def test_coluna_faltando_em_excel_cita_o_arquivo_original(tmp_path):
    ruim = xlsx({"transaction_data": texto_transacoes(CABECALHO_TRANS.replace("SALES_VALUE,", "VALOR,")),
                 "product": "\n".join(PRODUTOS)})
    with pytest.raises(ErroCarga) as e:
        carga.carregar(upload={"export.xlsx": ruim}, pasta_bancos=tmp_path)
    assert "export.xlsx" in str(e.value) and "aba transaction_data" in str(e.value) and "SALES_VALUE" in str(e.value)


@pytest.mark.parametrize("nome", ["notas.pdf", "dados.xls", "planilha.txt", "base.parquet", "sem_extensao"])
def test_formato_nao_aceito(tmp_path, nome):
    with pytest.raises(ErroCarga, match="Formato não aceito"):
        carga.carregar(upload={nome: b"x"}, pasta_bancos=tmp_path)


def test_excel_corrompido(tmp_path):
    with pytest.raises(ErroCarga, match="Não consegui ler o Excel"):
        carga.carregar(upload={"transaction_data.xlsx": b"isto nao e um xlsx"}, pasta_bancos=tmp_path)


def test_arquivo_de_nome_desconhecido_e_ignorado_com_aviso(tmp_path):
    r = carga.carregar(upload=upload_csv(**{"leia-me.csv": "a\n1"}), pasta_bancos=tmp_path)
    assert any("leia-me.csv" in a and "ignorado" in a for a in r.avisos)


def test_arquivos_temporarios_sao_apagados(tmp_path):
    import tempfile
    from pathlib import Path
    antes = {p.name for p in Path(tempfile.gettempdir()).glob("carga_*")}
    carga.carregar(upload=upload_csv(), pasta_bancos=tmp_path)
    with pytest.raises(ErroCarga):
        carga.carregar(upload={"product.csv": b"x"}, pasta_bancos=tmp_path)
    assert {p.name for p in Path(tempfile.gettempdir()).glob("carga_*")} == antes
