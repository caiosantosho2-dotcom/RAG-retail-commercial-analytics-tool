"""Modelo de linguagem roteirizado para testar o agente e o app sem rede nem chave."""

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ModeloRoteirizado(BaseChatModel):
    """Devolve, em ordem, as respostas do roteiro. Guarda as mensagens que recebeu em `vistas`."""

    roteiro: list = []
    indice: int = 0
    vistas: list = []
    tokens: int = 100

    @property
    def _llm_type(self) -> str:
        return "roteirizado"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.vistas.append(list(messages))
        item = self.roteiro[min(self.indice, len(self.roteiro) - 1)]
        self.indice += 1
        if isinstance(item, Exception):
            raise item
        return ChatResult(
            generations=[ChatGeneration(message=item)],
            llm_output={"token_usage": {"prompt_tokens": self.tokens, "completion_tokens": 10,
                                        "total_tokens": self.tokens + 10}})


def chamada(sql: str, id_: str = "c1", nome: str = "executar_consulta", **extra) -> AIMessage:
    args = {"sql": sql, **extra} if nome == "executar_consulta" else {}
    return AIMessage(content="", tool_calls=[{"name": nome, "args": args, "id": id_, "type": "tool_call"}])


def texto(conteudo: str) -> AIMessage:
    return AIMessage(content=conteudo)
