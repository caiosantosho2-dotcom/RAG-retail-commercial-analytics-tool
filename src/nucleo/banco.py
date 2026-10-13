"""Conexão do núcleo com o banco: sempre só leitura, sem acesso a arquivos, config travada.

O DuckDB não aceita duas conexões ao mesmo arquivo com configurações diferentes, então há uma
conexão por arquivo, com a configuração fixa daqui, e cada chamada usa um cursor próprio
(o que permite interromper uma consulta por timeout sem afetar as outras).
"""

import contextlib
import contextvars
import threading
from pathlib import Path

import duckdb

from src.config import CFG, RAIZ

_lock = threading.Lock()
_conexoes: dict[str, duckdb.DuckDBPyConnection] = {}
_ativo: Path | None = None


def _config() -> dict:
    return {
        "enable_external_access": False,   # sem read_csv, glob, ATTACH, COPY ...
        "lock_configuration": True,        # SET não consegue desfazer o acima
        "memory_limit": CFG["consulta"]["memoria_maxima"],
    }


def definir_banco(caminho: str | Path | None) -> None:
    """Banco padrão do processo (scripts, avaliação, testes). Um app com várias sessões não deve
    depender disto: use `usando(caminho)`, que vale só para a chamada e para a sessão dela."""
    global _ativo
    _ativo = Path(caminho).resolve() if caminho else None


_da_chamada: contextvars.ContextVar[Path | None] = contextvars.ContextVar("banco_da_chamada", default=None)


@contextlib.contextmanager
def usando(caminho: str | Path):
    """Dentro do bloco, as ferramentas leem este banco, sem afetar outras sessões."""
    token = _da_chamada.set(Path(caminho).resolve())
    try:
        yield
    finally:
        _da_chamada.reset(token)


def banco_ativo() -> Path:
    return _da_chamada.get() or _ativo or (RAIZ / CFG["banco"]["arquivo"])


def conectar(caminho: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    destino = Path(caminho or banco_ativo()).resolve()
    if not destino.exists():
        raise FileNotFoundError(f"Banco não encontrado: {destino.name}")
    chave = str(destino)
    with _lock:
        if chave not in _conexoes:
            _conexoes[chave] = duckdb.connect(chave, read_only=True, config=_config())
        return _conexoes[chave]


def cursor(caminho: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    return conectar(caminho).cursor()


def fechar_todas() -> None:
    with _lock:
        for con in _conexoes.values():
            try:
                con.close()
            except duckdb.Error:
                pass
        _conexoes.clear()


def versao_base(cur) -> str | None:
    try:
        linha = cur.execute("SELECT valor FROM meta WHERE chave = 'versao_base'").fetchone()
        return linha[0] if linha else None
    except duckdb.Error:
        return None


def janela(cur) -> dict | None:
    """Semanas e datas das duas janelas, no formato compacto que vai em todo retorno."""
    try:
        j = cur.execute("SELECT * FROM vw_janela").df().iloc[0]
    except (duckdb.Error, IndexError):
        return None
    if j.isna().any():
        return None
    return {
        "atual": {"semanas": [int(j.semana_ini_atual), int(j.semana_fim_atual)],
                  "datas": [str(j.data_ini_atual)[:10], str(j.data_fim_atual)[:10]]},
        "base": {"semanas": [int(j.semana_ini_base), int(j.semana_fim_base)],
                 "datas": [str(j.data_ini_base)[:10], str(j.data_fim_base)[:10]]},
        "regra": f"janela de referência do projeto, usada só quando a consulta filtra periodo = 'atual' ou 'base' "
                 f"(não é o filtro da sua consulta): últimas {int(j.semanas)} semanas completas contra as mesmas "
                 f"semanas um ano antes (WEEK_NO - {int(j.offset_semanas)}), só lojas presentes nos dois períodos",
    }


def rastreabilidade(cur) -> dict:
    """Campos que todo retorno de ferramenta carrega (spec, regras globais)."""
    return {"versao_base": versao_base(cur), "janela": janela(cur)}
