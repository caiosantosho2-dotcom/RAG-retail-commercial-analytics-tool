"""Pacote Parquet (a base limpa, versionada no repositório, que o app publicado carrega sem os CSV): íntegro, em dia com o config,
pequeno o bastante para o Git e, sobretudo, igual ao banco do ETL: mesmas tabelas, mesmas views e os mesmos números nas análises."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from src import carga, etl, pacote
from src.config import CFG, RAIZ
from src.etl import ErroCarga
from src.nucleo import banco, cache
from tests.test_carga import upload_csv

ETL_DB = RAIZ / CFG["banco"]["arquivo"]
pytestmark = pytest.mark.skipif(not pacote.existe(), reason="rode `python -m src.etl` e `python -m src.pacote exportar`")


@pytest.fixture
def copia(tmp_path):
    destino = tmp_path / "parquet"
    shutil.copytree(pacote.PASTA, destino)
    return destino


# --- integridade e validade --------------------------------------------------------------------------------------

def test_pacote_esta_integro_e_em_dia_com_o_config_e_a_versao_do_etl():
    m = pacote.verificar()
    assert m["etl_versao"] == etl.ETL_VERSAO and m["versao_base"] == etl.versao_de_md5s([a["md5"] for a in m["arquivos_de_origem"]])
    assert {t["tabela"] for t in m["tabelas"]} == set(pacote.TABELAS_PACOTE) and len(m["arquivos_de_origem"]) == len(etl.TABELAS)


def test_pacote_cabe_no_git_nenhum_arquivo_perto_do_limite_de_100_mb():
    arquivos = list(pacote.PASTA.glob("*"))
    assert max(a.stat().st_size for a in arquivos) < 30_000_000 and sum(a.stat().st_size for a in arquivos) < 40_000_000


@pytest.mark.skipif(not ETL_DB.exists(), reason="rode `python -m src.etl`")
def test_pacote_e_da_mesma_versao_do_banco_do_etl_local():
    assert carga._meta(ETL_DB, "versao_base") == pacote.ler_manifesto()["versao_base"]
    banco.fechar_todas()


def test_pacote_corrompido_ou_incompleto_e_recusado_com_instrucao(copia):
    arquivo = copia / "fato_transacoes.parquet"
    arquivo.write_bytes(arquivo.read_bytes()[:-1000])
    with pytest.raises(ErroCarga, match="corrompido ou incompleto.*exportar"):
        pacote.verificar(copia)
    shutil.copy(pacote.PASTA / "fato_transacoes.parquet", arquivo)          # restaura o primeiro e tira outro arquivo
    (copia / "dim_loja.parquet").unlink()
    with pytest.raises(ErroCarga, match="dim_loja"):
        pacote.verificar(copia)


def test_pacote_velho_para_os_parametros_atuais_e_recusado(copia):
    cfg = json.loads(json.dumps(CFG))
    cfg["janela"]["semanas_atuais"] = 13
    with pytest.raises(ErroCarga, match="outros parâmetros ou outra versão do ETL"):
        pacote.verificar(copia, cfg)
    m = pacote.ler_manifesto(copia)
    m["formato"] = 99
    (copia / "manifesto.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ErroCarga, match="Formato de pacote desconhecido"):
        pacote.verificar(copia)


def test_sem_pacote_a_verificacao_diz_que_nao_existe(tmp_path):
    assert not pacote.existe(tmp_path)
    with pytest.raises(ErroCarga, match="não encontrado"):
        pacote.verificar(tmp_path)


# --- carga: prioridade, reaproveitamento, e o banco do pacote é o mesmo do ETL -----------------------------------------

def test_sem_csv_a_carga_usa_o_pacote_e_reaproveita_na_segunda_vez(tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    r = carga.carregar(pastas=[vazio], pasta_bancos=tmp_path / "bancos", pasta_pacote=pacote.PASTA)
    assert r.origem == "pacote" and not r.reaproveitado and r.versao_base == pacote.ler_manifesto()["versao_base"]
    assert r.resumo["households"] == 2500 and r.resumo["reconciliacao_ok"] and r.resumo["linhas_vendas"] == 2548662
    assert carga.relatorio(r.caminho_banco)["reconciliacao"]["ok"]
    outra = carga.carregar(pastas=[vazio], pasta_bancos=tmp_path / "bancos", pasta_pacote=pacote.PASTA)
    assert outra.reaproveitado and outra.caminho_banco == r.caminho_banco
    banco.fechar_todas()


def test_upload_tem_prioridade_sobre_o_pacote(tmp_path):
    r = carga.carregar(upload=upload_csv(), pasta_bancos=tmp_path, pasta_pacote=pacote.PASTA)
    assert r.origem == "upload" and r.versao_base != pacote.ler_manifesto()["versao_base"]
    banco.fechar_todas()


def test_pastas_explicitas_sem_dados_e_sem_pacote_continuam_dando_erro_claro(tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    with pytest.raises(ErroCarga, match="Nenhum dado encontrado"):
        carga.carregar(pastas=[vazio], pasta_bancos=tmp_path)


def test_pacote_velho_na_carga_vira_erro_legivel_e_nao_deixa_banco_pela_metade(tmp_path, copia):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    (copia / "dim_loja.parquet").unlink()
    with pytest.raises(ErroCarga):
        carga.carregar(pastas=[vazio], pasta_bancos=tmp_path / "bancos", pasta_pacote=copia)
    assert not list((tmp_path / "bancos").glob("*.duckdb*"))


@pytest.mark.skipif(not ETL_DB.exists(), reason="rode `python -m src.etl`")
def test_banco_do_pacote_e_igual_ao_do_etl_tabelas_views_e_analises(tmp_path):
    novo = tmp_path / "do_pacote.duckdb"
    pacote.carregar_pacote(destino=novo)
    a, b = banco.cursor(ETL_DB), banco.cursor(novo)

    def tabela(cur, nome):
        df = cur.execute(f"SELECT * FROM {nome}").df()
        return df.sort_values(list(df.columns)).reset_index(drop=True)

    for t in pacote.TABELAS_PACOTE:
        if t != "fato_transacoes":      # 2,5 milhões de linhas: conferida por contagem e soma abaixo
            pd.testing.assert_frame_equal(tabela(a, t), tabela(b, t), check_dtype=False)
    for v in ("vw_janela", "vw_yoy_resumo", "vw_yoy_categoria", "vw_yoy_loja", "vw_metricas_cliente", "vw_cliente_semana", "metricas_definicao"):
        pd.testing.assert_frame_equal(tabela(a, v), tabela(b, v), check_dtype=False, check_exact=False, rtol=1e-9, atol=1e-9)
    soma = "SELECT COUNT(*), SUM(SALES_VALUE), SUM(RETAIL_DISC), SUM(COUPON_DISC), SUM(COUPON_MATCH_DISC), SUM(QUANTITY), COUNT(DISTINCT BASKET_ID) FROM fato_transacoes"
    assert a.execute(soma).fetchone() == b.execute(soma).fetchone()
    assert carga.relatorio(ETL_DB) == carga.relatorio(novo)
    assert carga._meta(novo, "origem") == "pacote"

    from src.nucleo.churn import prever_churn
    from src.nucleo.clv import calcular_clv
    from src.nucleo.rfm import segmentar_clientes
    from src.nucleo.teste_desconto import testar_desconto_entre_segmentos
    resultados = {}
    for rotulo, caminho in (("etl", ETL_DB), ("pacote", novo)):
        cache.limpar()
        with banco.usando(caminho):
            resultados[rotulo] = [json.dumps(f(), ensure_ascii=False, default=str, sort_keys=True)
                                  for f in (segmentar_clientes, calcular_clv, prever_churn, testar_desconto_entre_segmentos)]
    assert resultados["etl"] == resultados["pacote"]            # mesmos números, campo a campo (inclui versao_base e janela)
    cache.limpar()
    banco.fechar_todas()
