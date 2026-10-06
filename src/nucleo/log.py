"""Log de chamadas das ferramentas: uma linha JSON por chamada, fora do Git.

Registra ferramenta, parâmetros, tempo, nº de linhas, tamanho do retorno e erro. Falha ao gravar
o log nunca derruba a ferramenta. O servidor MCP (fase 6) reutiliza este decorador.
"""

import functools
import inspect
import json
import threading
import time
from datetime import datetime
from pathlib import Path

from src.config import CFG, RAIZ

CAMINHO: Path = RAIZ / CFG["logs"]["chamadas"]
_lock = threading.Lock()


def _curto(valor, limite=2000):
    if isinstance(valor, str) and len(valor) > limite:
        return valor[:limite] + "..."
    return valor


def gravar(registro: dict, caminho: Path | None = None) -> None:
    caminho = Path(caminho or CAMINHO)
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with _lock, open(caminho, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def registrar_chamada(ferramenta: str):
    def decorador(funcao):
        assinatura = inspect.signature(funcao)

        @functools.wraps(funcao)
        def envelope(*args, **kwargs):
            inicio = time.perf_counter()
            resultado, excecao = None, None
            try:
                resultado = funcao(*args, **kwargs)
                return resultado
            except Exception as e:  # registra e propaga
                excecao = e
                raise
            finally:
                try:
                    parametros = dict(assinatura.bind_partial(*args, **kwargs).arguments)
                except TypeError:
                    parametros = {}
                dicionario = resultado if isinstance(resultado, dict) else {}
                linhas = dicionario.get("linhas")
                gravar({
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "ferramenta": ferramenta,
                    "parametros": {k: _curto(v) for k, v in parametros.items()},
                    "tempo_ms": round((time.perf_counter() - inicio) * 1000, 1),
                    "n_linhas": len(linhas) if isinstance(linhas, list) else None,
                    "tamanho_bytes": len(json.dumps(resultado, default=str, ensure_ascii=False).encode())
                    if resultado is not None else 0,
                    "erro": dicionario.get("erro") or (type(excecao).__name__ if excecao else None),
                })
        return envelope
    return decorador
