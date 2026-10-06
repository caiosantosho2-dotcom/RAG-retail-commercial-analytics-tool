"""Servidor MCP: só embrulha as funções do núcleo, sem lógica própria.

As descrições das ferramentas são os docstrings das funções (spec: docs/spec_ferramentas_mcp.md). Guard-rails, log e
rastreabilidade (`versao_base`, `janela`) ficam no núcleo; o servidor não os reimplementa.

Uso (stdio, o que Claude Desktop/Code e o app Streamlit esperam):
    venv\\Scripts\\python.exe -m src.mcp_server

Variáveis de ambiente (opcionais):
    ASSISTENTE_BANCO  caminho do .duckdb a consultar (padrão: o do config.yaml); sempre aberto só para leitura
    ASSISTENTE_LOG    arquivo do log de chamadas (padrão: o do config.yaml)

Nada é impresso em stdout além do protocolo: stdout é o canal do MCP.
"""

import inspect
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from src.nucleo import banco, log
from src.nucleo.churn import prever_churn
from src.nucleo.clv import calcular_clv
from src.nucleo.consulta import executar_consulta
from src.nucleo.descrever import descrever_dados
from src.nucleo.rfm import segmentar_clientes
from src.nucleo.teste_desconto import testar_desconto_entre_segmentos

NOME = "assistente-comercial"
FERRAMENTAS = {
    "descrever_dados": descrever_dados,
    "executar_consulta": executar_consulta,
    "segmentar_clientes": segmentar_clientes,
    "calcular_clv": calcular_clv,
    "prever_churn": prever_churn,
    "testar_desconto_entre_segmentos": testar_desconto_entre_segmentos,
}


def _compacta(funcao):
    """Mesma função, resultado em JSON compacto. O FastMCP indentaria o dict com 2 espaços, o que só gasta tokens do modelo
    (o plano gratuito do Groq limita tokens por minuto). Nome, docstring e parâmetros ficam como no núcleo."""
    def ferramenta(*args, **kwargs) -> str:
        return json.dumps(funcao(*args, **kwargs), ensure_ascii=False, separators=(",", ":"), default=str)

    ferramenta.__name__, ferramenta.__doc__ = funcao.__name__, funcao.__doc__
    ferramenta.__signature__ = inspect.signature(funcao).replace(return_annotation=str)
    return ferramenta


def criar_servidor() -> FastMCP:
    servidor = FastMCP(NOME)
    for nome, funcao in FERRAMENTAS.items():
        servidor.add_tool(_compacta(funcao), name=nome)
    return servidor


def configurar_do_ambiente() -> None:
    if os.environ.get("ASSISTENTE_BANCO"):
        banco.definir_banco(os.environ["ASSISTENTE_BANCO"])
    if os.environ.get("ASSISTENTE_LOG"):
        log.CAMINHO = Path(os.environ["ASSISTENTE_LOG"])


def main() -> None:
    configurar_do_ambiente()
    criar_servidor().run(transport="stdio")


if __name__ == "__main__":
    main()
