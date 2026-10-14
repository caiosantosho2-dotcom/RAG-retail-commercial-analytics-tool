"""Carga de dados: upload (CSV/Excel) ou pasta `data/`, com o upload tendo prioridade.

Cada arquivo é reconhecido pelo nome (ou, no Excel, pelo nome da aba): transaction_data, product,
hh_demographic, campaign_table, campaign_desc, coupon, coupon_redempt, causal_data. Só
transaction_data e product são obrigatórios; as demais, quando faltam, entram como tabelas vazias
e a carga avisa o que deixa de existir. O banco é reaproveitado quando a versão da base (hash dos
arquivos + parâmetros + lógica do ETL) já foi construída.
"""

import json
import re
import shutil
import tempfile
import threading
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from src import etl, pacote
from src.config import CFG, RAIZ
from src.etl import COLUNAS_OBRIGATORIAS, TABELAS, ErroCarga
from src.nucleo import banco

OBRIGATORIAS = ["transaction_data", "product"]
OPCIONAIS = [t for t in TABELAS if t not in OBRIGATORIAS]
SEM_OPCIONAL = {
    "hh_demographic": "demografia dos households (idade, renda ...)",
    "campaign_table": "quais campanhas cada household recebeu",
    "campaign_desc": "datas das campanhas",
    "coupon": "cupons de cada campanha",
    "coupon_redempt": "resgates de cupom",
    "causal_data": "display e mailer por semana e loja",
}
FORMATOS = {".csv", ".xlsx"}
_trava = threading.Lock()


@dataclass
class ResultadoCarga:
    caminho_banco: Path
    versao_base: str
    origem: str                      # "upload" ou "pasta"
    reaproveitado: bool              # True quando o banco dessa versão já existia
    resumo: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)


def _normalizar(nome: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


def _tabela_do_nome(nome: str) -> str | None:
    alvo = _normalizar(Path(nome).stem)
    return alvo if alvo in TABELAS else None


def _excel_para_csv(caminho: Path, destino: Path) -> dict[str, tuple[Path, str]]:
    """Converte as abas de um .xlsx cujo nome é uma tabela conhecida (ou a única aba, se o arquivo
    tem nome de tabela). Tudo como texto: a limpeza converte os tipos e registra o que falhar."""
    try:
        abas = pd.read_excel(caminho, sheet_name=None, dtype=str)
    except Exception as e:  # arquivo corrompido, protegido etc.
        raise ErroCarga(f"Não consegui ler o Excel '{caminho.name}': {str(e)[:120]}.") from e
    achadas: dict[str, tuple[Path, str]] = {}
    tabela_arquivo = _tabela_do_nome(caminho.name)
    for aba, df in abas.items():
        tabela = _tabela_do_nome(aba) or (tabela_arquivo if len(abas) == 1 else None)
        if tabela:
            saida = destino / f"{tabela}.csv"
            df.to_csv(saida, index=False)
            achadas[tabela] = (saida, f"{caminho.name} (aba {aba})")
    return achadas


def identificar_fontes(arquivos: list[Path], trabalho: Path) -> tuple[dict[str, Path], dict[str, str], list[str]]:
    """Mapeia arquivos para tabelas. Devolve (fontes, nome original por tabela, avisos)."""
    fontes: dict[str, Path] = {}
    origem: dict[str, str] = {}
    avisos: list[str] = []
    for arq in arquivos:
        sufixo = arq.suffix.lower()
        if sufixo not in FORMATOS:
            raise ErroCarga(f"Formato não aceito: '{arq.name}'. Envie arquivos CSV ou Excel (.xlsx).")
        if sufixo == ".csv":
            tabela = _tabela_do_nome(arq.name)
            if tabela is None:
                avisos.append(f"Arquivo ignorado (nome não reconhecido): {arq.name}.")
                continue
            fontes[tabela], origem[tabela] = arq, arq.name
        else:
            achadas = _excel_para_csv(arq, trabalho)
            if not achadas:
                avisos.append(f"Arquivo ignorado (nenhuma aba com nome de tabela): {arq.name}.")
            for tabela, (csv, nome) in achadas.items():
                fontes[tabela], origem[tabela] = csv, nome
    return fontes, origem, avisos


def _completar_opcionais(fontes: dict[str, Path], trabalho: Path) -> list[str]:
    avisos = []
    ausentes = [t for t in OPCIONAIS if t not in fontes]
    for tabela in ausentes:
        vazio = trabalho / f"{tabela}.csv"
        vazio.write_text(",".join(COLUNAS_OBRIGATORIAS[tabela]) + "\n", encoding="utf-8")
        fontes[tabela] = vazio
    if ausentes:
        avisos.append("Tabelas opcionais não enviadas, então ficam vazias: "
                      + "; ".join(f"{t} ({SEM_OPCIONAL[t]})" for t in ausentes) + ".")
    return avisos


def _validar(fontes: dict[str, Path], origem: dict[str, str]) -> None:
    faltam = [t for t in OBRIGATORIAS if t not in fontes]
    if faltam:
        raise ErroCarga("Faltam arquivos obrigatórios: " + ", ".join(faltam) + ". Cada arquivo precisa ter o nome da "
                        "tabela (ex.: transaction_data.csv) ou, no Excel, uma aba com esse nome. "
                        f"Obrigatórios: {', '.join(OBRIGATORIAS)}; opcionais: {', '.join(OPCIONAIS)}.")
    for tabela in TABELAS:
        if tabela not in fontes:
            continue
        faltantes = etl.colunas_faltantes(fontes[tabela], tabela)
        if faltantes:
            raise ErroCarga(f"No arquivo '{origem.get(tabela, tabela)}' faltam as colunas: {', '.join(faltantes)}.")


def _meta(caminho: Path, chave: str):
    cur = banco.cursor(caminho)
    linha = cur.execute("SELECT valor FROM meta WHERE chave = ?", [chave]).fetchone()
    return linha[0] if linha else None


def _banco_da_versao(versao: str, pasta: Path) -> Path | None:
    """Procura, na pasta de bancos, um que já tenha sido construído com esta versão."""
    for candidato in sorted(pasta.glob("*.duckdb")):
        try:
            if _meta(candidato, "versao_base") == versao:
                return candidato
        except (duckdb.Error, OSError):
            continue
    return None


def relatorio(caminho: Path) -> dict:
    """O relatório de qualidade completo que o ETL gravou junto com o banco."""
    return json.loads(_meta(caminho, "relatorio_qualidade"))


def resumir(caminho: Path) -> dict:
    """O que a tela de carga mostra: período, linhas, lojas, households."""
    rel = relatorio(caminho)
    cob, rec = rel["cobertura"], rel["reconciliacao"]
    return {
        "periodo": f"{cob['data_min'][:10]} a {cob['data_max'][:10]}",
        "semanas": cob["semanas"],
        "linhas_brutas": rec["linhas_brutas"],
        "linhas_vendas": rec["linhas_limpas"],
        "linhas_ajustadas": rec["linhas_ajustes"],
        "lojas": cob["lojas"],
        "households": cob["households"],
        "households_sem_demografia": cob["households_sem_demografia"],
        "versao_base": rel["versao_base"],
        "reconciliacao_ok": rec["ok"],
        "janela": rel.get("janela"),
        "avisos_etl": rel.get("avisos", []),
    }


def pastas_de_dados() -> list[Path]:
    return [RAIZ / "data", RAIZ / CFG["dados"]["pasta_raw"]]


def _arquivos_da_pasta(pasta: Path) -> list[Path]:
    return sorted(p for p in pasta.glob("*") if p.is_file() and p.suffix.lower() in FORMATOS) if pasta.exists() else []


def _carregar_do_pacote(pasta_pacote: Path | None, pasta_bancos: Path, cfg: dict, progresso) -> ResultadoCarga:
    """Terceira origem: o pacote Parquet gerado localmente por `python -m src.pacote exportar` (não vai para o Git). Mesma versão e mesmos números do ETL."""
    m = pacote.verificar(pasta_pacote, cfg)
    versao = m["versao_base"]
    with _trava:
        existente = _banco_da_versao(versao, pasta_bancos)
        reaproveitado = existente is not None
        alvo = existente or pasta_bancos / f"base_{versao}.duckdb"
        if not reaproveitado:
            progresso("Construindo o banco a partir do pacote de dados (Parquet) ...")
            pacote.carregar_pacote(pasta_pacote, alvo, cfg, progresso)
    banco.definir_banco(alvo)
    resumo = resumir(alvo)
    avisos = resumo.pop("avisos_etl")
    return ResultadoCarga(alvo, versao, "pacote", reaproveitado, resumo, avisos)


def carregar(upload: dict[str, bytes] | None = None, pastas: list[Path] | None = None,
             pasta_bancos: Path | None = None, cfg: dict | None = None,
             progresso=lambda mensagem: None, pasta_pacote: Path | None = None) -> ResultadoCarga:
    """Carrega os dados e deixa o banco pronto para as ferramentas. Prioridade: upload, CSV/Excel das pastas, pacote Parquet."""
    cfg = cfg or CFG
    pasta_bancos = Path(pasta_bancos or RAIZ / "data" / "processed")
    pasta_bancos.mkdir(parents=True, exist_ok=True)
    trabalho = Path(tempfile.mkdtemp(prefix="carga_"))
    try:
        if upload:
            origem_carga = "upload"
            arquivos = []
            for nome, conteudo in upload.items():
                destino = trabalho / "enviados" / Path(nome).name
                destino.parent.mkdir(exist_ok=True)
                destino.write_bytes(conteudo)
                arquivos.append(destino)
        else:
            origem_carga = "pasta"
            arquivos = []
            for pasta in (pastas or pastas_de_dados()):
                if any(_tabela_do_nome(p.name) in OBRIGATORIAS for p in _arquivos_da_pasta(pasta)):
                    arquivos = _arquivos_da_pasta(pasta)
                    break
            if not arquivos and (pastas is None or pasta_pacote is not None) and pacote.existe(pasta_pacote):
                return _carregar_do_pacote(pasta_pacote, pasta_bancos, cfg, progresso)
            if not arquivos:
                raise ErroCarga("Nenhum dado encontrado. Arraste os arquivos exportados do BI para a tela de carga "
                                "ou coloque-os na pasta data/. Sem arquivos próprios: rode `python baixar_dados.py` e `python -m src.etl`.")
        fontes, origem, avisos = identificar_fontes(arquivos, trabalho)
        _validar(fontes, origem)
        avisos += _completar_opcionais(fontes, trabalho)

        progresso("Calculando a versão da base ...")
        versao, _ = etl.calcular_versao(fontes, cfg)
        with _trava:
            existente = _banco_da_versao(versao, pasta_bancos)
            reaproveitado = existente is not None
            alvo = existente or pasta_bancos / f"base_{versao}.duckdb"
            if not reaproveitado:
                progresso("Construindo o banco (limpeza, esquema e métricas) ...")
                etl.construir_banco(fontes, destino=alvo, cfg=cfg, log=progresso)
        banco.definir_banco(alvo)
        resumo = resumir(alvo)
        avisos += resumo.pop("avisos_etl")
        return ResultadoCarga(alvo, versao, origem_carga, reaproveitado, resumo, avisos)
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)
