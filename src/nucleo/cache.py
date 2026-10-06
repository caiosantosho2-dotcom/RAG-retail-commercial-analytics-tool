"""Cache dos resultados das análises, por banco, versão da base e parâmetros.

Uma análise só é recalculada quando a base (versao_base) ou os parâmetros mudam. Sessões com bancos
diferentes não se misturam: o caminho do banco faz parte da chave.
"""

import copy
import hashlib
import json
import threading

_dados: dict[str, object] = {}
_trava = threading.Lock()


def chave(cur, nome: str, **parametros) -> str:
    from src.nucleo import banco
    # `PRAGMA database_list` não é aceito pelo validador do agente, mas aqui é código interno.
    arquivo = cur.execute("SELECT path FROM duckdb_databases() WHERE NOT internal AND path IS NOT NULL").fetchone()
    versao = banco.versao_base(cur)
    bruto = json.dumps({"n": nome, "a": arquivo[0] if arquivo else "", "v": versao, **parametros},
                       sort_keys=True, default=str)
    return hashlib.md5(bruto.encode()).hexdigest()


def obter(chave_: str, calcular):
    """Devolve o valor guardado ou calcula e guarda. Quem chama recebe uma cópia, para não alterar o cache."""
    with _trava:
        if chave_ not in _dados:
            _dados[chave_] = calcular()
        return copy.deepcopy(_dados[chave_])


def limpar() -> None:
    with _trava:
        _dados.clear()
