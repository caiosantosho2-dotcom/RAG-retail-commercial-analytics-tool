"""Pacote de dados em Parquet: recurso LOCAL (cerca de 18 MB, em `data/`, fora do Git). Não é forma de distribuir dados: o dataset é da
dunnhumby e não vai para o repositório.

Por que existe: construir o banco a partir dos CSV (700 MB, sobretudo `causal_data`) leva cerca de 2 minutos. O pacote guarda as tabelas que o ETL já produziu (vendas limpas, ajustes, dimensões, campanhas, cupons e o
agregado de display/mailer) e o relatório de qualidade. Carregar o pacote recria o DuckDB e as views em segundos.

Por que o histórico inteiro, e não só as duas janelas: o risco de pausa usa o histórico desde a semana 5, o CLV calibra nas semanas 24
a 101 e a coorte depende da primeira compra no histórico. Com só as duas janelas esses números mudariam.

  venv\\Scripts\\python.exe -m src.pacote exportar    # depois de rodar o ETL: grava data/processed/parquet/
  venv\\Scripts\\python.exe -m src.pacote verificar   # confere o pacote contra o manifesto e contra o config

A `versao_base` do pacote é a do ETL que o gerou (o manifesto guarda o MD5 dos CSV de origem): enquanto os parâmetros e a lógica do ETL
não mudarem, o banco do pacote e o do ETL têm a mesma versão e dão os mesmos números. Se mudarem, o pacote fica velho e a carga recusa
com a instrução de gerar de novo.
"""

import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import duckdb

from src import etl, views
from src.config import CFG, RAIZ
from src.etl import ErroCarga

PASTA = RAIZ / "data" / "processed" / "parquet"
TABELAS_PACOTE = ["fato_transacoes", "fato_ajustes", "dim_data", "dim_produto", "dim_loja", "dim_household", "campaign_desc",
                  "campaign_table", "coupon", "coupon_redempt", "causal_semana_loja", "reconciliacao_semanal", "log_cargas"]
FORMATO = 1


def _md5(caminho: Path) -> str:
    h = hashlib.md5()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def existe(pasta: Path | None = None) -> bool:
    return ((pasta or PASTA) / "manifesto.json").exists()


def ler_manifesto(pasta: Path | None = None) -> dict:
    return json.loads(((pasta or PASTA) / "manifesto.json").read_text(encoding="utf-8"))


def exportar(banco_origem: Path | None = None, destino: Path | None = None, log=print) -> dict:
    """Grava as tabelas do banco construído pelo ETL em Parquet (zstd) e o manifesto. Substitui o pacote anterior."""
    banco_origem = Path(banco_origem or RAIZ / CFG["banco"]["arquivo"])
    destino = Path(destino or PASTA)
    if not banco_origem.exists():
        raise ErroCarga(f"Banco não encontrado: {banco_origem}. Rode `venv\\Scripts\\python.exe -m src.etl` antes.")
    con = duckdb.connect(str(banco_origem), read_only=True)
    try:
        meta = dict(con.execute("SELECT chave, valor FROM meta").fetchall())
        relatorio = json.loads(meta["relatorio_qualidade"])
        if not relatorio["reconciliacao"]["ok"]:
            raise ErroCarga("O banco de origem não reconcilia com o bruto: o pacote não é gerado.")
        arquivos = sorted(relatorio["arquivos"], key=lambda a: etl.TABELAS.index(a["tabela"]))
        if etl.versao_de_md5s([a["md5"] for a in arquivos]) != meta["versao_base"]:
            raise ErroCarga("A versão do banco de origem não bate com os parâmetros atuais do config.yaml ou com a versão do ETL: "
                            "rode o ETL de novo antes de exportar.")
        tmp = destino.parent / (destino.name + "_novo")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        itens = []
        for tabela in TABELAS_PACOTE:
            arquivo = tmp / f"{tabela}.parquet"
            con.execute(f"COPY (SELECT * FROM {tabela}) TO '{arquivo.as_posix()}' "
                        "(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 12, ROW_GROUP_SIZE 200000)")
            linhas = con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            itens.append({"tabela": tabela, "arquivo": arquivo.name, "linhas": int(linhas), "bytes": arquivo.stat().st_size, "md5": _md5(arquivo)})
            log(f"{tabela}: {linhas} linhas, {arquivo.stat().st_size / 1e6:.2f} MB")
    finally:
        con.close()
    manifesto = {"formato": FORMATO, "versao_base": meta["versao_base"], "etl_versao": etl.ETL_VERSAO, "data_carga": meta["data_carga"],
                 "data_base": meta["data_base"], "gerado_em": datetime.now().isoformat(timespec="seconds"),
                 "arquivos_de_origem": arquivos, "tabelas": itens}
    (tmp / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8")
    (tmp / "relatorio_qualidade.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    shutil.rmtree(destino, ignore_errors=True)
    tmp.replace(destino)
    log(f"Pacote: {destino} ({sum(i['bytes'] for i in itens) / 1e6:.1f} MB, versão {manifesto['versao_base']})")
    return manifesto


def verificar(pasta: Path | None = None, cfg: dict | None = None) -> dict:
    """Confere integridade (tamanho e MD5 de cada arquivo) e se o pacote ainda vale para os parâmetros atuais. Devolve o manifesto."""
    pasta = Path(pasta or PASTA)
    if not existe(pasta):
        raise ErroCarga("Pacote de dados não encontrado.")
    m = ler_manifesto(pasta)
    if m.get("formato") != FORMATO:
        raise ErroCarga("Formato de pacote desconhecido: gere o pacote de novo (`python -m src.pacote exportar`).")
    for item in m["tabelas"]:
        arquivo = pasta / item["arquivo"]
        if not arquivo.exists() or arquivo.stat().st_size != item["bytes"] or _md5(arquivo) != item["md5"]:
            raise ErroCarga(f"Pacote de dados corrompido ou incompleto ({item['arquivo']}). Gere de novo com `python -m src.pacote exportar`.")
    esperada = etl.versao_de_md5s([a["md5"] for a in m["arquivos_de_origem"]], cfg)
    if esperada != m["versao_base"]:
        raise ErroCarga("O pacote de dados foi gerado com outros parâmetros ou outra versão do ETL (config.yaml ou ETL_VERSAO mudaram). "
                        "Rode o ETL e depois `venv\\Scripts\\python.exe -m src.pacote exportar`.")
    return m


def carregar_pacote(pasta: Path | None = None, destino: Path | None = None, cfg: dict | None = None, log=lambda m: None) -> str:
    """Cria o banco DuckDB (tabelas + views de métricas + relatório) a partir do pacote e devolve a `versao_base`."""
    cfg = cfg or CFG
    pasta = Path(pasta or PASTA)
    m = verificar(pasta, cfg)
    destino = Path(destino)
    tmp = destino.with_suffix(".duckdb.tmp")
    for p in (tmp, Path(str(tmp) + ".wal")):
        p.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        for item in m["tabelas"]:
            log(f"Lendo {item['tabela']} ...")
            con.execute(f"CREATE TABLE {item['tabela']} AS SELECT * FROM read_parquet('{(pasta / item['arquivo']).as_posix()}')")
            n = con.execute(f"SELECT COUNT(*) FROM {item['tabela']}").fetchone()[0]
            if n != item["linhas"]:
                raise ErroCarga(f"{item['tabela']}: {n} linhas, o manifesto diz {item['linhas']}.")
        relatorio = json.loads((pasta / "relatorio_qualidade.json").read_text(encoding="utf-8"))
        con.execute("CREATE TABLE meta (chave VARCHAR, valor VARCHAR)")
        for k, v in {"versao_base": m["versao_base"], "data_carga": m["data_carga"], "data_base": m["data_base"],
                     "origem": "pacote", "pacote_gerado_em": m["gerado_em"]}.items():
            con.execute("INSERT INTO meta VALUES (?, ?)", [k, v])
        log("Criando views de métricas ...")
        views.criar_views(con, cfg)
        con.execute("INSERT INTO meta VALUES ('relatorio_qualidade', ?)", [json.dumps(relatorio, default=str)])
    except BaseException:
        con.close()
        for p in (tmp, Path(str(tmp) + ".wal")):
            p.unlink(missing_ok=True)
        raise
    con.close()
    for p in (destino, Path(str(destino) + ".wal")):
        p.unlink(missing_ok=True)
    tmp.replace(destino)
    return m["versao_base"]


if __name__ == "__main__":
    comando = sys.argv[1] if len(sys.argv) > 1 else ""
    if comando == "exportar":
        exportar()
    elif comando == "verificar":
        m = verificar()
        print(f"Pacote ok: versão {m['versao_base']}, {len(m['tabelas'])} tabelas, "
              f"{sum(t['bytes'] for t in m['tabelas']) / 1e6:.1f} MB, gerado em {m['gerado_em']}")
    else:
        raise SystemExit("Uso: python -m src.pacote exportar | verificar")
