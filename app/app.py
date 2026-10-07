"""Assistente comercial: o chat é a primeira aba; a carga de dados é por arquivo (ou pela pasta data/).

Rodar: streamlit run app/app.py
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import agente, carga, qualidade  # noqa: E402
from src.cliente_mcp import ErroServidorMCP, ServidorMCP  # noqa: E402
from src.config import CFG  # noqa: E402
from src.etl import ErroCarga  # noqa: E402
from src.token_counter import LIMITES_REFERENCIA_TPM, ContadorTokens  # noqa: E402
from src.ui import aba_churn, aba_clv, aba_desconto, aba_segmentos  # noqa: E402

EXEMPLOS = [
    "Qual loja teve o maior ticket médio nas últimas 4 semanas?",
    "Quanto a loja 367 vendeu de laticínios no último mês?",
    "Qual departamento teve mais desconto de cupom?",
    "A venda da loja 367 caiu contra o ano passado por menos clientes, menos idas ou menos gasto por ida?",
]

st.set_page_config(page_title="Assistente Comercial", page_icon="🛒", layout="wide")


# --------------------------------------------------------------------------- estado e carga

def _estado():
    s = st.session_state
    s.setdefault("carga", None)
    s.setdefault("autocarga_tentada", False)
    s.setdefault("mensagens", [])
    s.setdefault("contador", ContadorTokens())
    s.setdefault("ultimos_tokens", {})
    s.setdefault("agente", None)
    s.setdefault("agente_ctx", None)
    s.setdefault("servidor_mcp", None)
    s.setdefault("modo_ferramentas", "mcp")


def _carregar_dados(upload: dict[str, bytes] | None = None, silencioso: bool = False) -> bool:
    """Carrega upload (prioridade) ou pasta. Mostra o andamento e a mensagem de erro, se houver."""
    status = st.status("Carregando os dados ...", expanded=True)
    try:
        resultado = carga.carregar(upload=upload, progresso=status.write)
    except ErroCarga as e:
        if silencioso and str(e).startswith("Nenhum dado encontrado"):
            status.update(label="Nenhum dado na pasta data/", state="complete", expanded=False)
        else:
            status.update(label="Não foi possível carregar os dados", state="error")
            st.error(str(e))
        return False
    except Exception as e:  # falha inesperada: mensagem curta, sem despejo técnico
        status.update(label="Não foi possível carregar os dados", state="error")
        st.error(f"Algo deu errado ao carregar os dados ({type(e).__name__}). Confira os arquivos e tente de novo.")
        return False
    status.update(label="Dados carregados", state="complete", expanded=False)
    antes = st.session_state.carga
    st.session_state.carga = resultado
    if antes is None or antes.versao_base != resultado.versao_base:
        st.session_state.mensagens = []
        st.session_state.agente = st.session_state.agente_ctx = None
        _fechar_servidor()
    return True


def _segredo_groq() -> str:
    try:
        return st.secrets.get("GROQ_API_KEY", "")
    except Exception:   # sem arquivo de segredos
        return ""


def _fechar_servidor():
    if st.session_state.servidor_mcp is not None:
        st.session_state.servidor_mcp.fechar()
    st.session_state.servidor_mcp = None


def _obter_servidor():
    """O servidor MCP desta sessão, aberto sob demanda (na primeira pergunta) e preso ao banco dela. Se não subir, as
    funções do núcleo são chamadas direto: o chat continua funcionando e a barra lateral avisa."""
    caminho = st.session_state.carga.caminho_banco
    atual = st.session_state.servidor_mcp
    if atual is not None and atual.aberto and atual.caminho_banco == Path(caminho).resolve():
        return atual
    _fechar_servidor()
    try:
        st.session_state.servidor_mcp = ServidorMCP(caminho_banco=caminho)
        st.session_state.modo_ferramentas = "mcp"
    except ErroServidorMCP:
        st.session_state.modo_ferramentas = "direto"
    return st.session_state.servidor_mcp


def _obter_agente(chave: str, modelo: str):
    servidor = _obter_servidor()
    ctx = (st.session_state.carga.versao_base, modelo, hash(chave), id(servidor))
    if st.session_state.agente_ctx != ctx:
        st.session_state.agente = agente.criar_agente(
            api_key=chave, modelo=modelo, caminho_banco=st.session_state.carga.caminho_banco, servidor=servidor)
        st.session_state.agente_ctx = ctx
    return st.session_state.agente


# --------------------------------------------------------------------------- componentes

def _tela_de_carga(chave: str = "carga"):
    st.subheader("Comece carregando os dados")
    st.markdown(
        "Arraste as planilhas exportadas do BI (**CSV** ou **Excel**). O nome do arquivo (ou da aba, no Excel) "
        "diz de que tabela se trata.\n\n"
        "- **Obrigatórias:** `transaction_data` (itens vendidos) e `product` (cadastro de produtos).\n"
        "- **Opcionais:** `hh_demographic`, `campaign_table`, `campaign_desc`, `coupon`, `coupon_redempt`, "
        "`causal_data`. Sem elas, as perguntas sobre demografia, campanhas e cupons ficam indisponíveis.\n\n"
        "Se a pasta `data/` já tiver os arquivos, eles são carregados sozinhos ao abrir o app. "
        "O arquivo enviado aqui tem prioridade sobre a pasta.")
    arquivos = st.file_uploader("Arquivos de dados", type=["csv", "xlsx"], accept_multiple_files=True,
                                key=f"arquivos_{chave}")
    if st.button("Carregar dados", type="primary", disabled=not arquivos, key=f"botao_{chave}"):
        if _carregar_dados({a.name: a.getvalue() for a in arquivos}):
            st.rerun()


def _resumo(resumo: dict):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Período dos dados", resumo["periodo"])
    c2.metric("Linhas de venda", f"{resumo['linhas_vendas']:,}")
    c3.metric("Lojas", f"{resumo['lojas']:,}")
    c4.metric("Households", f"{resumo['households']:,}")


def _mostrar_consultas(consultas):
    if not consultas:
        return
    with st.expander("Consulta SQL usada", expanded=False):
        for i, c in enumerate(consultas, 1):
            if len(consultas) > 1:
                st.markdown(f"**Consulta {i}**")
            st.code(c["sql"], language="sql")
            if c["erro"]:
                st.warning(c["erro"])
            elif c["linhas"]:
                st.dataframe(pd.DataFrame(c["linhas"], columns=c["colunas"]), hide_index=True, width="stretch")
                if c["truncado"]:
                    st.caption(f"Mostrando {len(c['linhas'])} de {c['total_linhas']:,} linhas.")


def _mensagens():
    for m in st.session_state.mensagens:
        with st.chat_message(m["papel"]):
            st.markdown(m["texto"])
            if m["papel"] == "assistant":
                _mostrar_consultas(m.get("consultas"))


def _responder(pergunta: str, chave: str, modelo: str):
    with st.chat_message("user"):
        st.markdown(pergunta)
    with st.chat_message("assistant"):
        with st.spinner("Consultando os dados ..."):
            historico = [(m["papel"], m["texto"]) for m in st.session_state.mensagens if not m.get("erro")]
            ag = _obter_agente(chave, modelo)
            r = agente.perguntar(ag, pergunta, contador=st.session_state.contador, historico=historico)
    st.session_state.mensagens.append({"papel": "user", "texto": pergunta})
    st.session_state.mensagens.append({
        "papel": "assistant", "texto": r.texto, "erro": bool(r.erro),
        "consultas": [{"sql": c.sql, "colunas": c.colunas, "linhas": c.linhas, "erro": c.erro,
                       "total_linhas": c.total_linhas, "truncado": c.truncado} for c in r.consultas]})
    st.session_state.ultimos_tokens = r.tokens
    st.rerun()   # atualiza o contador de tokens da barra lateral


def _aba_chat(chave: str, modelo: str):
    if st.session_state.carga is None:
        _tela_de_carga()
        return
    if not st.session_state.mensagens:
        st.markdown("Pergunte do jeito que você fala no dia a dia. A resposta vem dos dados, e a consulta "
                    "usada fica disponível para você conferir.")
        colunas = st.columns(2)
        for i, exemplo in enumerate(EXEMPLOS):
            if colunas[i % 2].button(exemplo, key=f"exemplo_{i}", width="stretch"):
                st.session_state.pergunta_pendente = exemplo
    _mensagens()
    pergunta = st.chat_input("Pergunte sobre vendas, lojas, categorias, descontos ...")
    pergunta = pergunta or st.session_state.pop("pergunta_pendente", None)
    if pergunta:
        if not chave:
            st.info("Informe a chave do Groq na barra lateral para fazer perguntas.")
        else:
            _responder(pergunta, chave, modelo)


def _aba_dados():
    c = st.session_state.carga
    if c is None:
        st.info("Nenhum dado carregado ainda. Envie os arquivos na aba Chat.")
        return
    origem = {"upload": "arquivos enviados", "pacote": "pacote de dados (Parquet versionado no repositório)"}.get(c.origem, "pasta de dados")
    st.markdown(f"Dados carregados dos **{origem}** · versão da base `{c.versao_base}`"
                + (" · reaproveitada do cache" if c.reaproveitado else ""))
    _resumo(c.resumo)
    for aviso in c.avisos:
        st.warning(aviso)
    if not c.resumo["reconciliacao_ok"]:
        st.error("O total limpo não reconcilia com o bruto: não use estes números.")
    with st.expander("Relatório de qualidade dos dados"):
        rel = carga.relatorio(c.caminho_banco)
        st.markdown(qualidade.renderizar_markdown(rel))
    with st.expander("Trocar os dados"):
        _tela_de_carga("troca")


def _barra_lateral() -> tuple[str, str]:
    with st.sidebar:
        st.title("🛒 Assistente Comercial")
        st.caption("Perguntas em linguagem de negócio, respondidas com os dados da planilha carregada.")
        if st.session_state.carga is not None:
            r = st.session_state.carga.resumo
            st.caption(f"Base `{st.session_state.carga.versao_base}` · {r['periodo']}")
        st.divider()
        st.subheader("Modelo")
        modelos = CFG["agente"]["modelos_disponiveis"]
        modelo = st.selectbox("Modelo do Groq", modelos, index=modelos.index(CFG["agente"]["modelo"]))
        chave = _segredo_groq()
        if chave:
            st.caption("Chave do Groq configurada.")
        else:
            # O campo é sempre desenhado: o Streamlit descarta o estado de widgets que somem entre execuções.
            chave = st.text_input("Chave do Groq", type="password", key="chave_groq",
                                  help="Grátis em console.groq.com. A chave fica só nesta sessão do navegador.")
        if st.session_state.servidor_mcp is not None or st.session_state.modo_ferramentas == "direto":
            st.caption("Ferramentas pelo servidor MCP." if st.session_state.modo_ferramentas == "mcp"
                       else "Ferramentas em modo direto: o servidor MCP não iniciou nesta sessão.")
        st.divider()
        st.subheader("Uso de tokens")
        total = st.session_state.contador.resumo()
        ultimo = st.session_state.ultimos_tokens
        st.metric("Última resposta", f"{ultimo.get('total_tokens', 0):,}")
        st.metric("Sessão", f"{total['total_tokens']:,}")
        st.caption(f"{total['chamadas_llm']} chamadas ao modelo · "
                   f"referência do plano gratuito: {LIMITES_REFERENCIA_TPM.get(modelo, 6000):,} tokens por minuto.")
    return chave, modelo


def main():
    _estado()
    if st.session_state.carga is None and not st.session_state.autocarga_tentada:
        st.session_state.autocarga_tentada = True
        _carregar_dados(silencioso=True)
    chave, modelo = _barra_lateral()
    aba_chat, aba_segmentos_, aba_clv_, aba_churn_, aba_desconto_, aba_dados = st.tabs(
        ["Chat", "Segmentos (RFM)", "Valor do cliente (CLV)", "Risco de pausa (churn)", "Desconto por segmento", "Dados e qualidade"])
    with aba_chat:
        _aba_chat(chave, modelo)
    with aba_segmentos_:
        if st.session_state.carga is None:
            st.info("Carregue os dados na aba Chat para ver os segmentos.")
        else:
            aba_segmentos.renderizar(st.session_state.carga.caminho_banco)
    with aba_clv_:
        if st.session_state.carga is None:
            st.info("Carregue os dados na aba Chat para ver o valor dos clientes.")
        else:
            aba_clv.renderizar(st.session_state.carga.caminho_banco)
    with aba_churn_:
        if st.session_state.carga is None:
            st.info("Carregue os dados na aba Chat para ver o risco de pausa.")
        else:
            aba_churn.renderizar(st.session_state.carga.caminho_banco)
    with aba_desconto_:
        if st.session_state.carga is None:
            st.info("Carregue os dados na aba Chat para ver o desconto por segmento.")
        else:
            aba_desconto.renderizar(st.session_state.carga.caminho_banco)
    with aba_dados:
        _aba_dados()


main()
