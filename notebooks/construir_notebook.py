"""Monta e executa o notebook narrado e salva o resultado, com as saídas, em notebooks/analise_clientes_dunnhumby.ipynb.

    venv\\Scripts\\python.exe notebooks\\construir_notebook.py            # monta, executa e salva (cerca de 1 minuto com o cache quente)
    venv\\Scripts\\python.exe notebooks\\construir_notebook.py --sem-executar   # só monta (sem saídas)

O texto e o código das células estão em notebooks/fonte/conteudo_*.py (um lugar só para editar). O notebook salvo traz as saídas
para quem abrir no GitHub ver os resultados sem rodar nada; o banco (`data/processed/dunnhumby.duckdb`) não vai para o Git.
"""

import argparse
import importlib
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent
DESTINO = PASTA / "analise_clientes_dunnhumby.ipynb"
PARTES = ["conteudo_a", "conteudo_b"]


def celulas() -> list[tuple[str, str]]:
    sys.path.insert(0, str(PASTA / "fonte"))
    saida = []
    for nome in PARTES:
        try:
            modulo = importlib.import_module(nome)
        except ModuleNotFoundError as e:
            if e.name != nome:
                raise
            continue
        saida += modulo.CELULAS
    return saida


def montar() -> nbformat.NotebookNode:
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    nb.metadata["language_info"] = {"name": "python"}
    for tipo, texto in celulas():
        nb.cells.append(nbformat.v4.new_markdown_cell(texto) if tipo == "md" else nbformat.v4.new_code_cell(texto))
    return nb


def executar(nb: nbformat.NotebookNode) -> nbformat.NotebookNode:
    NotebookClient(nb, timeout=1200, kernel_name="python3", resources={"metadata": {"path": str(PASTA)}}).execute()
    return nb


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sem-executar", action="store_true", help="só monta o notebook, sem executar")
    a = ap.parse_args(argv)
    nb = montar()
    if not a.sem_executar:
        nb = executar(nb)
    nbformat.validate(nb)
    nbformat.write(nb, DESTINO)
    print(f"{DESTINO.relative_to(RAIZ)}: {len(nb.cells)} células, {DESTINO.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
