"""
token_counter.py
REAPROVEITÁVEL 100% — nenhuma linha depende do schema de dados.
Callback do LangChain que soma tokens consumidos em cada chamada ao Groq.
"""

from langchain_core.callbacks import BaseCallbackHandler

LIMITES_REFERENCIA_TPM = {
    "openai/gpt-oss-120b": 8000,
    "openai/gpt-oss-20b": 8000,
}


class ContadorTokens(BaseCallbackHandler):
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.chamadas_llm = 0

    def on_llm_end(self, response, **kwargs):
        self.chamadas_llm += 1

        uso = {}
        info = getattr(response, "llm_output", None) or {}
        uso = info.get("token_usage") or {}

        if not uso:
            try:
                mensagem = response.generations[0][0].message
                uso = getattr(mensagem, "response_metadata", {}).get("token_usage", {})
            except (AttributeError, IndexError, KeyError):
                uso = {}

        self.prompt_tokens += uso.get("prompt_tokens", 0)
        self.completion_tokens += uso.get("completion_tokens", 0)
        self.total_tokens += uso.get("total_tokens", 0)

    def resumo(self) -> dict:
        return {
            "chamadas_llm": self.chamadas_llm,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }
