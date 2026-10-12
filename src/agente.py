"""Agente do chat: pergunta em linguagem de negócio -> ferramentas -> resposta em texto.

O modelo é criado só em `criar_modelo()`, para a troca ser em um lugar. As ferramentas vêm do servidor MCP
(`criar_agente(servidor=ServidorMCP(...))`, o caminho do app); `ferramentas_do_nucleo()` chama as funções direto e
fica como reserva se o servidor não subir.
O glossário é injetado na pergunta antes de chegar ao modelo (determinístico, não é ferramenta).
"""

import contextlib
import functools
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from src.config import CFG, RAIZ
from src.cliente_mcp import texto_do_conteudo
from src.glossario_rag import buscar_termos_relevantes
from src.nucleo import banco, log
from src.nucleo.consulta import executar_consulta
from src.nucleo.descrever import catalogo_compacto, compactar_catalogo, descrever_dados

CAMINHO_USO = RAIZ / CFG["logs"]["uso_chat"]

INSTRUCOES_SISTEMA = """Você é o assistente comercial de uma rede de supermercados. Responde a gerentes e analistas, em português e em linguagem de negócio, consultando os dados com as ferramentas. Valores em dólares (US$).

Como trabalhar:
1. Para qualquer número de vendas, lojas, produtos ou clientes, execute uma consulta com executar_consulta antes de responder (as análises da regra 9 usam as ferramentas próprias). Nunca invente número e nunca responda só com SQL: execute e responda em texto. Não use SQL como calculadora.
2. Use as views vw_*: elas já trazem a definição oficial de cada métrica. Não recalcule faturamento, ticket, desconto nem comparação com o ano anterior à mão. Use só colunas do catálogo abaixo; na dúvida, chame descrever_dados(detalhe="<view>") para ver as colunas daquela view.
3. Comparações com o ano anterior: use vw_yoy_resumo, vw_yoy_loja ou vw_yoy_categoria (já alinham as semanas e as lojas). Para explicar por que algo mudou, consulte também vw_contexto_periodo. O número pedido vem da consulta que responde à pergunta: as vw_yoy_* servem para variação e contexto, e os totais delas cobrem só as lojas like-for-like; nunca use esse total no lugar do total geral (faturamento total = vw_vendas_item ou vw_metricas_cesta, todas as lojas).
4. "Loja", "unidade" e "filial" são STORE_ID. Texto de categoria e de produto: ILIKE '%...%'.
5. "Último mês", "ano passado" e semelhantes são relativos ao fim dos dados (vw_janela), nunca à data de hoje.
6. Listagens de registros: LIMIT 20 (máximo 200). Prefira uma consulta agregada a várias consultas.
7. Se a consulta falhar, leia o erro, corrija e tente de novo (no máximo duas vezes).
8. Se a pergunta for ambígua (qual loja? qual período?), pergunte antes de consultar.
9. Segmentação de clientes, CLV, churn e teste de desconto entre segmentos NÃO são consultas SQL: use as ferramentas segmentar_clientes, calcular_clv, prever_churn e testar_desconto_entre_segmentos (sem argumentos, a menos que a pergunta peça um segmento). Elas trazem um bloco e_dai: responda com a conclusão, a ação recomendada e a limitação mais importante, em poucas frases, citando as premissas (margem do CLV, "churn" = pausa de 8 semanas, teste de desconto = diferença entre grupos, não causa). Não repita o retorno inteiro.
10. Comece pela conclusão e dê o número com contexto (contra o ano anterior quando fizer sentido). Avise quando a loja tiver amostra_pequena = TRUE. Não existe vendedor: a menor unidade de equipe é a loja.
11. Faturamento (coluna faturamento, SALES_VALUE) já é líquido de descontos: nunca desconte de novo. Para o desconto use as colunas desconto_* e o percentual oficial.
12. Escreva identificadores (PRODUCT_ID, household_key, STORE_ID) e anos sempre sem separador de milhar: 5569230, não 5.569.230 nem 5 569 230.
13. "Fiéis" é o nome de um segmento RFM (ferramenta segmentar_clientes), não sinônimo de cliente de alta frequência. Para o segmento Fiéis use as ferramentas de análise; cliente de alta frequência é o corte de frequência (percentil 75) e nunca se chama "Fiéis".

{catalogo}"""


@dataclass
class Consulta:
    sql: str
    colunas: list = field(default_factory=list)
    linhas: list = field(default_factory=list)
    total_linhas: int | None = None
    truncado: bool = False
    erro: str | None = None


@dataclass
class Resposta:
    texto: str
    consultas: list[Consulta] = field(default_factory=list)
    ferramentas: list[str] = field(default_factory=list)
    glossario: str = ""
    tempo_s: float = 0.0
    tokens: dict = field(default_factory=dict)
    erro: str | None = None


def _vinculada(funcao, caminho_banco):
    """A mesma função, lendo sempre o banco desta sessão (assinatura e docstring preservadas)."""
    @functools.wraps(funcao)
    def envelope(*args, **kwargs):
        with banco.usando(caminho_banco):
            return funcao(*args, **kwargs)
    return envelope


def ferramentas_do_nucleo(caminho_banco: str | Path | None = None) -> list[StructuredTool]:
    """As ferramentas da spec que existem até aqui; a descrição vem do docstring de cada função.
    Com `caminho_banco`, ficam presas a esse banco (sessões de um app público não se misturam)."""
    funcoes = {"executar_consulta": executar_consulta, "descrever_dados": descrever_dados}
    if caminho_banco:
        funcoes = {nome: _vinculada(f, caminho_banco) for nome, f in funcoes.items()}
    return [StructuredTool.from_function(func=f, name=nome) for nome, f in funcoes.items()]


def criar_modelo(api_key: str, modelo: str | None = None):
    """Único ponto que conhece o provedor do modelo."""
    from langchain_groq import ChatGroq
    return ChatGroq(model=modelo or CFG["agente"]["modelo"], temperature=CFG["agente"]["temperatura"],
                    groq_api_key=api_key, max_retries=2)


def criar_agente(api_key: str | None = None, modelo: str | None = None, llm=None, ferramentas=None,
                 catalogo: str | None = None, caminho_banco: str | Path | None = None, servidor=None):
    """Monta o agente. `llm` permite injetar um modelo pronto (testes); sem ele, usa o Groq.
    `caminho_banco` prende as ferramentas e o catálogo ao banco de uma sessão. Com `servidor` (ServidorMCP), as seis
    ferramentas e o catálogo vêm do servidor MCP; sem ele, são as funções do núcleo chamadas direto."""
    llm = llm or criar_modelo(api_key, modelo)
    if servidor is not None:
        ferramentas = ferramentas or servidor.ferramentas
        if catalogo is None:
            catalogo = compactar_catalogo(servidor.chamar("descrever_dados", detalhe="tudo"))
    if catalogo is None:
        with banco.usando(caminho_banco) if caminho_banco else contextlib.nullcontext():
            catalogo = catalogo_compacto()
    return create_agent(llm, ferramentas or ferramentas_do_nucleo(caminho_banco),
                        system_prompt=INSTRUCOES_SISTEMA.replace("{catalogo}", catalogo))


def montar_pergunta(pergunta: str) -> tuple[str, str]:
    """Pergunta + definições relevantes do glossário. Devolve (texto para o modelo, glossário injetado)."""
    glossario = buscar_termos_relevantes(pergunta)
    if not glossario:
        return pergunta, ""
    return f"{pergunta}\n\nDefinições de negócio relevantes:\n{glossario}", glossario


def _extrair(mensagens, novas_a_partir_de: int) -> tuple[str, list[Consulta], list[str]]:
    import json
    pedidos: dict[str, str] = {}
    ferramentas: list[str] = []
    consultas: list[Consulta] = []
    texto = ""
    for m in mensagens[novas_a_partir_de:]:
        if isinstance(m, AIMessage):
            for chamada in m.tool_calls or []:
                ferramentas.append(chamada["name"])
                if chamada["name"] == "executar_consulta":
                    pedidos[chamada["id"]] = str((chamada.get("args") or {}).get("sql", ""))
            if not m.tool_calls:
                texto = m.content if isinstance(m.content, str) else str(m.content)
        elif isinstance(m, ToolMessage) and m.name == "executar_consulta":
            try:
                dado = json.loads(texto_do_conteudo(m.content))
            except (TypeError, ValueError):
                dado = {"erro": texto_do_conteudo(m.content)[:200]}
            consultas.append(Consulta(
                sql=dado.get("sql_executado") or pedidos.get(m.tool_call_id, ""),
                colunas=dado.get("colunas", []), linhas=dado.get("linhas", []),
                total_linhas=dado.get("total_linhas"), truncado=bool(dado.get("truncado")),
                erro=dado.get("erro")))
    return texto, consultas, ferramentas


def _segundos_de_espera(erro: Exception) -> float | None:
    achado = re.search(r"try again in (?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", str(erro))
    if not achado or not (achado.group(1) or achado.group(2)):
        return None
    return int(achado.group(1) or 0) * 60 + float(achado.group(2) or 0)


def perguntar(agente, pergunta: str, contador=None, historico: list[tuple[str, str]] | None = None,
              espera_maxima_s: float = 25, tentativas: int = 3, registrar: bool = True, ao_esperar=None) -> Resposta:
    """Faz uma pergunta ao agente. Nunca levanta: falhas voltam em Resposta.erro com texto legível."""
    import groq

    inicio = time.perf_counter()
    antes = dict(contador.resumo()) if contador else {}
    texto_modelo, glossario = montar_pergunta(pergunta)
    mensagens = [HumanMessage(c) if papel == "user" else AIMessage(c) for papel, c in (historico or [])[-6:]]
    mensagens.append(HumanMessage(texto_modelo))
    config = {"recursion_limit": 2 * CFG["agente"]["max_iteracoes"] + 2}
    if contador:
        config["callbacks"] = [contador]

    resposta = Resposta(texto="", glossario=glossario)
    for tentativa in range(1, tentativas + 1):
        try:
            saida = agente.invoke({"messages": mensagens}, config=config)
            texto, consultas, ferramentas = _extrair(saida["messages"], len(mensagens))
            resposta.texto, resposta.consultas, resposta.ferramentas = texto, consultas, ferramentas
            resposta.erro = None
            break
        except groq.RateLimitError as e:
            espera = _segundos_de_espera(e)
            if tentativa < tentativas and espera is not None and espera <= espera_maxima_s:
                if ao_esperar:
                    ao_esperar(espera + 1)
                time.sleep(espera + 1)
                continue
            resposta.erro = ("O limite de uso do modelo foi atingido"
                             + (f"; tente de novo em cerca de {espera:.0f} s." if espera else "; tente de novo em instantes."))
            break
        except groq.AuthenticationError:
            resposta.erro = "A chave do Groq foi recusada. Confira a chave na barra lateral."
            break
        except groq.BadRequestError as e:
            # O modelo às vezes monta uma chamada de ferramenta malformada; uma nova tentativa costuma resolver.
            if tentativa < tentativas and "tool" in str(e).lower():
                continue
            resposta.erro = "O modelo não conseguiu montar a consulta. Reformule a pergunta ou tente de novo."
            break
        except Exception as e:  # rede, limite de recursão, formato inesperado
            resposta.erro = f"Não consegui responder agora ({type(e).__name__}). Tente de novo."
            break

    if resposta.erro and not resposta.texto:
        resposta.texto = resposta.erro
    resposta.tempo_s = round(time.perf_counter() - inicio, 2)
    if contador:
        depois = contador.resumo()
        resposta.tokens = {k: depois[k] - antes.get(k, 0) for k in depois}
    if registrar:
        log.gravar({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pergunta": pergunta,
                    "sql": [c.sql for c in resposta.consultas], "ferramentas": resposta.ferramentas,
                    "erro": resposta.erro or next((c.erro for c in resposta.consultas if c.erro), None),
                    "tokens": resposta.tokens, "tempo_s": resposta.tempo_s}, CAMINHO_USO)
    return resposta
