"""Cliente do servidor MCP para o agente: um processo `src.mcp_server` por sessão, falando por stdio.

Cada sessão do app abre o seu servidor apontando para o seu banco (`ASSISTENTE_BANCO`), então o isolamento entre sessões é
do processo, não de um parâmetro. As ferramentas vêm do `langchain-mcp-adapters` (`load_mcp_tools`) e são embrulhadas para
chamada síncrona: a sessão MCP vive num laço asyncio próprio, numa thread de fundo (a sessão stdio precisa ser aberta e
fechada pela mesma tarefa, e o Streamlit chama o agente de forma síncrona).

Custo: um interpretador Python + DuckDB por sessão (cerca de 150 a 250 MB de memória); `fechar()` encerra o processo.
"""

import asyncio
import atexit
import concurrent.futures
import json
import os
import sys
import threading
import time
from pathlib import Path

from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.config import CFG, RAIZ

_abertos: set["ServidorMCP"] = set()


class ErroServidorMCP(Exception):
    """O servidor não subiu ou foi encerrado. A mensagem é legível para quem usa o app."""


def texto_do_conteudo(conteudo) -> str:
    """Texto de um retorno de ferramenta: string pura (chamada direta) ou lista de blocos (via adaptador MCP)."""
    if isinstance(conteudo, str):
        return conteudo
    partes = []
    for bloco in conteudo or []:
        if isinstance(bloco, str):
            partes.append(bloco)
        elif isinstance(bloco, dict) and bloco.get("type") == "text":
            partes.append(str(bloco.get("text", "")))
    return "".join(partes)


@atexit.register
def _fechar_todos() -> None:
    for servidor in list(_abertos):
        servidor.fechar()


class ServidorMCP:
    def __init__(self, caminho_banco: str | Path | None = None, caminho_log: str | Path | None = None,
                 timeout_inicio: float = 90, timeout_chamada: float = 240, ocioso_s: float | None = None):
        self._timeout_chamada = timeout_chamada
        self._ocioso_s = CFG["agente"]["mcp_ocioso_minutos"] * 60 if ocioso_s is None else ocioso_s
        self._ultimo_uso = time.monotonic()
        self.caminho_banco = Path(caminho_banco).resolve() if caminho_banco else None
        self._env = {**os.environ}
        if caminho_banco:
            self._env["ASSISTENTE_BANCO"] = str(Path(caminho_banco).resolve())
        if caminho_log:
            self._env["ASSISTENTE_LOG"] = str(caminho_log)
        self._loop = asyncio.new_event_loop()
        self._parar: asyncio.Event | None = None
        self._sessao: ClientSession | None = None
        self._originais: list = []
        self._vida: concurrent.futures.Future | None = None
        self._fechado = False
        self._thread = threading.Thread(target=self._loop.run_forever, name="servidor-mcp", daemon=True)
        self._thread.start()
        _abertos.add(self)
        pronto: concurrent.futures.Future = concurrent.futures.Future()
        self._vida = asyncio.run_coroutine_threadsafe(self._viver(pronto), self._loop)
        try:
            pronto.result(timeout=timeout_inicio)
        except BaseException as e:
            self.fechar()
            raise ErroServidorMCP("Não consegui iniciar o servidor de ferramentas.") from e
        self.ferramentas = [self._sincrona(t) for t in self._originais]

    async def _viver(self, pronto: concurrent.futures.Future) -> None:
        self._parar = asyncio.Event()
        params = StdioServerParameters(command=sys.executable, args=["-m", "src.mcp_server"], cwd=str(RAIZ), env=self._env)
        try:
            async with stdio_client(params) as (leitura, escrita):
                async with ClientSession(leitura, escrita) as sessao:
                    await sessao.initialize()
                    self._originais = await load_mcp_tools(sessao)
                    self._sessao = sessao
                    self._ultimo_uso = time.monotonic()      # a ociosidade conta a partir de agora, não do início da subida
                    pronto.set_result(None)
                    while not self._parar.is_set():
                        try:
                            await asyncio.wait_for(self._parar.wait(), timeout=min(30.0, max(self._ocioso_s / 4, 0.05)))
                        except asyncio.TimeoutError:
                            if time.monotonic() - self._ultimo_uso > self._ocioso_s:
                                break           # sessão abandonada: libera o processo
        except BaseException as e:   # inclui o cancelamento; quem espera `pronto` recebe o motivo
            if not pronto.done():
                pronto.set_exception(e)
        finally:
            self._sessao = None
            self._fechado = True
            _abertos.discard(self)
            self._loop.call_soon(self._loop.stop)

    def _executar(self, corrotina, timeout: float):
        if self._fechado or self._sessao is None:
            corrotina.close()
            raise ErroServidorMCP("O servidor de ferramentas foi encerrado. Recarregue a página.")
        self._ultimo_uso = time.monotonic()
        try:
            return asyncio.run_coroutine_threadsafe(corrotina, self._loop).result(timeout=timeout)
        except concurrent.futures.TimeoutError as e:
            raise ErroServidorMCP("O servidor de ferramentas demorou demais para responder.") from e

    def _sincrona(self, original) -> StructuredTool:
        """A ferramenta do adaptador (assíncrona) com uma entrada síncrona que roda no laço do servidor."""
        def func(**argumentos):
            return self._executar(original.coroutine(**argumentos), self._timeout_chamada)

        return StructuredTool(name=original.name, description=original.description, args_schema=original.args_schema, func=func,
                              response_format="content_and_artifact", metadata=original.metadata,
                              handle_tool_error=original.handle_tool_error)

    def chamar(self, nome: str, **argumentos) -> dict:
        """Chama uma ferramenta e devolve o JSON dela como dict."""
        ferramenta = next((f for f in self.ferramentas if f.name == nome), None)
        if ferramenta is None:
            raise ErroServidorMCP(f"Ferramenta desconhecida: {nome}")
        conteudo, _ = ferramenta.func(**argumentos)
        return json.loads(texto_do_conteudo(conteudo))

    @property
    def aberto(self) -> bool:
        return not self._fechado and self._sessao is not None

    def fechar(self) -> None:
        """Encerra o processo do servidor. Pode ser chamado mais de uma vez."""
        if not self._fechado:
            self._fechado = True
            _abertos.discard(self)
            if self._parar is not None and self._vida is not None and not self._vida.done():
                self._loop.call_soon_threadsafe(self._parar.set)
                try:
                    self._vida.result(timeout=20)
                except BaseException:
                    self._vida.cancel()
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)
        if not self._loop.is_running() and not self._loop.is_closed():
            self._loop.close()
