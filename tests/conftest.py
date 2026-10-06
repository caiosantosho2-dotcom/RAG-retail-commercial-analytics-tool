"""Fixtures comuns."""

import pytest


@pytest.fixture(autouse=True)
def fechar_servidores_mcp_abertos_pelo_teste():
    """Cada AppTest que faz uma pergunta abre um servidor MCP (um processo, ~150 a 250 MB). Sem fechar, os processos se
    acumulam até o fim da sessão de testes e esta máquina (3,9 GB) fica sem memória. Os abertos antes do teste (fixtures
    de módulo) ficam como estão."""
    from src import cliente_mcp

    antes = set(cliente_mcp._abertos)
    yield
    for servidor in set(cliente_mcp._abertos) - antes:
        servidor.fechar()
