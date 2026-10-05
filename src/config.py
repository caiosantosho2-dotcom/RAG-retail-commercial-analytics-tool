"""Carrega o config.yaml. Parâmetros do projeto ficam lá, não espalhados no código."""

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent


def carregar_config(caminho: Path | None = None) -> dict:
    caminho = caminho or RAIZ / "config.yaml"
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


CFG = carregar_config()
