"""Gera requirements.txt (o que o app e o servidor MCP precisam) e requirements-dev.txt (testes, notebook, avaliação) com versões
travadas, a partir do ambiente em que os testes passaram.

    venv\\Scripts\\python.exe gerar_requirements.py

Por que dois arquivos: o `pip freeze` de uma máquina de desenvolvimento traz de tudo (Jupyter, pytest, pacotes só do Windows) e o
Streamlit Community Cloud, que lê `requirements.txt`, roda Linux. O arquivo do app é o fecho das dependências diretas, resolvido pelas
`Requires-Dist` de cada pacote instalado, com os marcadores de plataforma preservados (ex.: `pywin32` só no Windows).
"""

import re
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

RAIZ = Path(__file__).resolve().parent
# Pacotes que o código do app importa (src/, app/, servidor MCP). Tudo o mais entra por dependência.
DIRETAS = ["streamlit", "duckdb", "pandas", "numpy", "scikit-learn", "scipy", "statsmodels", "altair", "PyYAML", "openpyxl",
           "langchain", "langchain-core", "langchain-groq", "langchain-mcp-adapters", "mcp", "groq"]
# Só para desenvolvimento: testes, notebook, avaliação. O resto do `pip freeze` que não for do app também cai aqui.
DEV_EXTRAS = ["pytest", "nbclient", "nbformat", "nbconvert", "ipykernel", "vl-convert-python"]
AMBIENTES = {
    "win32": {"sys_platform": "win32", "platform_system": "Windows", "os_name": "nt", "platform_machine": "AMD64"},
    "linux": {"sys_platform": "linux", "platform_system": "Linux", "os_name": "posix", "platform_machine": "x86_64"},
}


def fecho() -> dict[str, set[str]]:
    """nome canônico -> ambientes em que o pacote é necessário (as dependências diretas valem em todos)."""
    visto: dict[str, set[str]] = {}
    fila = [(canonicalize_name(n), set(AMBIENTES)) for n in DIRETAS]
    while fila:
        nome, ambientes = fila.pop()
        novos = ambientes - visto.get(nome, set())
        if not novos:
            continue
        visto.setdefault(nome, set()).update(novos)
        try:
            exigencias = metadata.distribution(nome).requires or []
        except metadata.PackageNotFoundError:
            continue                      # só existe em outra plataforma: fica sem versão aqui e é reportado
        for texto in exigencias:
            r = Requirement(texto)
            if r.extras and not r.marker:
                pass
            for amb in novos:
                env = {**AMBIENTES[amb], "extra": "", "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
                       "python_full_version": sys.version.split()[0], "implementation_name": "cpython", "platform_python_implementation": "CPython"}
                if r.marker is None or r.marker.evaluate(env):
                    fila.append((canonicalize_name(r.name), {amb}))
    return visto


def linha(nome: str, ambientes: set[str]) -> str | None:
    try:
        versao = metadata.version(nome)
    except metadata.PackageNotFoundError:
        return None
    nome_exibido = metadata.distribution(nome).metadata["Name"]
    if ambientes == {"win32"}:
        return f'{nome_exibido}=={versao}; sys_platform == "win32"'
    return f"{nome_exibido}=={versao}"


def main() -> int:
    visto = fecho()
    faltam = sorted(n for n in visto if linha(n, visto[n]) is None)
    app = sorted((linha(n, a) for n, a in visto.items() if linha(n, a)), key=str.lower)
    so_linux = [n for n in faltam if visto[n] == {"linux"}]
    cabecalho = ("# Gerado por gerar_requirements.py a partir do ambiente em que os testes passaram. Não edite à mão.\n"
                 "# Dependências do app e do servidor MCP, com versões travadas (o Streamlit Community Cloud lê este arquivo).\n")
    (RAIZ / "requirements.txt").write_text(cabecalho + "\n".join(app) + "\n", encoding="utf-8")

    instalados = {canonicalize_name(d.metadata["Name"]): d for d in metadata.distributions()}
    no_app = set(visto)
    dev = sorted((f"{d.metadata['Name']}=={d.version}" for n, d in instalados.items() if n not in no_app), key=str.lower)
    (RAIZ / "requirements-dev.txt").write_text(
        "# Gerado por gerar_requirements.py. Desenvolvimento: testes, notebook narrado e avaliação, além do que o app já pede.\n"
        "-r requirements.txt\n" + "\n".join(dev) + "\n", encoding="utf-8")
    print(f"requirements.txt: {len(app)} pacotes · requirements-dev.txt: {len(dev)} a mais")
    if so_linux:
        print("Atenção: dependências só de Linux, sem versão travada (o pip escolhe):", ", ".join(so_linux))
    return 0


if __name__ == "__main__":
    sys.exit(main())
