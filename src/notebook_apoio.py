"""Apoio do notebook narrado: abre o banco, formata números em português e mostra os gráficos de `src/ui/graficos.py`.

O notebook não recalcula nada: os números vêm das funções do núcleo (as mesmas que o servidor MCP e as abas do app usam) e das
views. Este módulo só cuida da apresentação.

Gráfico: cada um sai como imagem PNG (aparece no GitHub e no HTML, que não executam o Vega) e leva junto a especificação
Vega-Lite (o Jupyter mostra a versão interativa, com tooltip). A saída é um único objeto com os dois formatos.
"""

import base64
import os
import sys
from pathlib import Path

import pandas as pd
import vl_convert as vlc
from IPython.display import Markdown, display

from src.config import CFG, RAIZ

MODO = "claro"
LARGURA = 760


def iniciar():
    """Põe a raiz do projeto no caminho e como pasta de trabalho, aponta o núcleo para o banco do config e devolve um cursor
    de leitura. Falha com instrução clara se o banco ainda não foi construído."""
    os.chdir(RAIZ)
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    from src.nucleo import banco
    caminho = RAIZ / CFG["banco"]["arquivo"]
    if not caminho.exists():
        raise FileNotFoundError(f"Banco não encontrado em {caminho}. Rode `venv\\Scripts\\python.exe -m src.etl` antes (cerca de 2 minutos).")
    banco.definir_banco(caminho)
    return banco.cursor()


def pt(x: float, casas: int = 1) -> str:
    """Número com vírgula decimal (sem separador de milhar; para milhar use `milhar`)."""
    return f"{x:.{casas}f}".replace(".", ",")


def milhar(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def usd(x: float, casas: int = 0) -> str:
    inteiro, _, frac = f"{x:,.{casas}f}".partition(".")
    return "US$ " + inteiro.replace(",", ".") + ("," + frac if frac else "")


def md(texto: str) -> None:
    display(Markdown(texto))


def e_dai(bloco: dict) -> None:
    """O bloco fixo de fechamento de cada seção (guia, seção 7.5), com o texto devolvido pela própria ferramenta."""
    linhas = ["> **E daí?**", ">", f"> **Conclusão.** {bloco['conclusao']}"]
    if bloco.get("evidencia"):
        linhas += [">", f"> {bloco['evidencia']}"]
    linhas += [">", f"> **Ação recomendada.** {bloco['acao_recomendada']}", ">",
               f"> **Impacto estimado.** {bloco['impacto_estimado']}", ">", f"> **Limitações.** {bloco['limitacoes']}"]
    if bloco.get("detalhes_tecnicos"):
        linhas += [">", "> **Detalhes técnicos.** " + " ".join(bloco["detalhes_tecnicos"])]
    display(Markdown(chr(10).join(linhas)))


def grafico(chart, largura: int = LARGURA, altura: int | None = None) -> None:
    """Mostra um gráfico de `src.ui.graficos` com os dois formatos (PNG e Vega-Lite interativo)."""
    propriedades = {"width": largura}
    if altura:
        propriedades["height"] = altura
    spec = chart.properties(**propriedades).to_dict()
    spec["background"] = "#ffffff"
    png = vlc.vegalite_to_png(spec, scale=2.0)
    titulo = spec.get("title")
    titulo = titulo.get("text") if isinstance(titulo, dict) else titulo
    versao = spec["$schema"].rsplit("/v", 1)[-1].split(".")[0]
    display({"image/png": base64.b64encode(png).decode(), f"application/vnd.vegalite.v{versao}+json": spec,
             "text/plain": f"[gráfico] {titulo}"}, raw=True)


def tabela(linhas, colunas: dict | None = None, formatos: dict | None = None) -> pd.DataFrame:
    """DataFrame legível: renomeia colunas e arredonda conforme `formatos` ({coluna: casas})."""
    df = pd.DataFrame(linhas)
    for coluna, casas in (formatos or {}).items():
        df[coluna] = df[coluna].round(casas)
    return df.rename(columns=colunas or {})


def versoes() -> dict:
    """Versões das bibliotecas que determinam os números (reprodutibilidade)."""
    import importlib.metadata as im
    return {p: im.version(p) for p in ("duckdb", "pandas", "numpy", "scikit-learn", "scipy", "statsmodels", "altair")}
