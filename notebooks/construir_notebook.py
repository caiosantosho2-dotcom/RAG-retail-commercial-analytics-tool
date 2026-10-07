"""Monta e executa o notebook narrado e salva o resultado, com as saídas, em notebooks/analise_clientes_dunnhumby.ipynb.

    venv\\Scripts\\python.exe notebooks\\construir_notebook.py            # monta, executa e salva (cerca de 1 minuto com o cache quente)
    venv\\Scripts\\python.exe notebooks\\construir_notebook.py --sem-executar   # só monta (sem saídas)

O texto e o código das células estão em notebooks/fonte/conteudo_*.py (um lugar só para editar). O notebook salvo traz as saídas
para quem abrir no GitHub ver os resultados sem rodar nada; o banco (`data/processed/dunnhumby.duckdb`) não vai para o Git.
"""

import argparse
import base64
import importlib
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

PASTA = Path(__file__).resolve().parent
RAIZ = PASTA.parent
DESTINO = PASTA / "analise_clientes_dunnhumby.ipynb"
PARTES = ["conteudo_a", "conteudo_b"]
IMAGENS = PASTA / "imagens"
# Nomes dos gráficos na ordem em que aparecem no notebook (o README usa estes arquivos; um teste confere a contagem).
NOMES_DAS_IMAGENS = ["01_escolha_do_k", "02_segmentos", "03_coorte", "04_clv", "05_ritmo_de_gasto", "06_backtest_clv", "07_precisao_recall",
                     "08_calibracao", "09_fatores", "10_risco_por_segmento", "11_desconto_distribuicao", "12_desconto_pares", "13_desconto_sensibilidade"]


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


def exportar_imagens(nb: nbformat.NotebookNode, destino: Path = IMAGENS) -> list[Path]:
    """Grava os PNG dos gráficos do notebook (na ordem em que aparecem) para o README e para quem quiser reaproveitar."""
    pngs = [o["data"]["image/png"] for c in nb.cells for o in c.get("outputs", []) if "image/png" in o.get("data", {})]
    if len(pngs) != len(NOMES_DAS_IMAGENS):
        raise SystemExit(f"O notebook tem {len(pngs)} gráficos e NOMES_DAS_IMAGENS tem {len(NOMES_DAS_IMAGENS)}: atualize a lista.")
    destino.mkdir(exist_ok=True)
    for antigo in destino.glob("*.png"):
        antigo.unlink()
    caminhos = []
    for nome, png in zip(NOMES_DAS_IMAGENS, pngs):
        caminhos.append(destino / f"{nome}.png")
        caminhos[-1].write_bytes(base64.b64decode(png))
    return caminhos


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sem-executar", action="store_true", help="só monta o notebook, sem executar")
    ap.add_argument("--so-imagens", action="store_true", help="só extrai os PNG do notebook já salvo (não executa nada)")
    a = ap.parse_args(argv)
    if a.so_imagens:
        n = len(exportar_imagens(nbformat.read(DESTINO, as_version=4)))
        print(f"{n} imagens em {IMAGENS.relative_to(RAIZ)}")
        return 0
    nb = montar()
    if not a.sem_executar:
        nb = executar(nb)
    nbformat.validate(nb)
    nbformat.write(nb, DESTINO)
    if not a.sem_executar:
        exportar_imagens(nb)
    print(f"{DESTINO.relative_to(RAIZ)}: {len(nb.cells)} células, {DESTINO.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
