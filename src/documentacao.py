"""Blocos do README que vêm das fontes, não da mão: métricas, relatório de qualidade, texto "e daí?" das análises, números da avaliação
e estrutura de pastas. O que está entre `<!-- gerado:NOME -->` e `<!-- /gerado:NOME -->` é reescrito; o resto do README é texto fixo.

    venv\\Scripts\\python.exe -m src.documentacao             # reescreve os blocos do README.md
    venv\\Scripts\\python.exe -m src.documentacao --verificar # só confere (saída 1 se o README estiver velho)

Os números das análises vêm das mesmas funções do núcleo que o app, o servidor MCP e o notebook usam (base local ou pacote Parquet).
"""

import re
import sys
from pathlib import Path

from src import views
from src.config import CFG, RAIZ

README = RAIZ / "README.md"

# Estrutura de pastas: (caminho, o que é). Um teste confere que cada caminho existe e que nenhuma pasta versionada ficou de fora.
ESTRUTURA = [
    (".claude/skills/", "skills do Claude Desktop/Code: `consultas-sql`, `analise-estatistica`, `qualidade-validacao`"),
    ("app/", "app Streamlit (`app.py`): chat e abas de análise"),
    ("data/processed/parquet/", "pacote de dados em Parquet gerado localmente (fora do Git)"),
    ("docs/", "guia do projeto, rotina de trabalho e a spec das ferramentas MCP (`spec_ferramentas_mcp.md`, fonte única das regras)"),
    ("eval/", "perguntas de negócio, de análise e maliciosas, cargas de ataque e o script de avaliação"),
    ("notebooks/", "notebook narrado (com as saídas salvas), seu construtor, o texto-fonte e os PNG dos gráficos"),
    ("referencia/", "módulos genéricos de apoio (glossário RAG, contador de tokens, testes de hipótese)"),
    ("relatorios/", "auditoria da base e relatório de qualidade gerado pelo ETL"),
    ("src/", "núcleo: ETL, views de métricas, análises (`nucleo/`), guard-rails, agente, glossário, servidor MCP, cliente MCP e gráficos (`ui/`)"),
    ("tests/", "testes automatizados (guard-rails, formato das ferramentas, métricas, análises, app, MCP, notebook, README)"),
    (".streamlit/", "configuração do Streamlit e modelo de segredos (`secrets.toml.example`)"),
    ("baixar_dados.py", "baixa os CSV do Kaggle para `data/raw/`"),
    ("config.yaml", "janela, semente e parâmetros de todas as análises"),
    ("gerar_requirements.py", "gera `requirements.txt` (app) e `requirements-dev.txt` (testes, notebook)"),
    ("CLAUDE.md", "memória do projeto: comandos e decisões registradas"),
]


def bloco_metricas() -> str:
    linhas = ["| Métrica | Definição de negócio | Fórmula | View de origem |", "|---|---|---|---|"]
    for nome, definicao, formula, view in views.METRICAS:
        linhas.append(f"| `{nome}` | {definicao} | `{formula}` | `{view}` |".replace("\n", " "))
    return "\n".join(linhas)


def bloco_estrutura() -> str:
    return "```\n" + "\n".join(f"{caminho:<26}{descricao}" for caminho, descricao in ESTRUTURA) + "\n```"


def _pt(x: float, casas: int = 0) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _milhar(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def _usd(x: float, casas: int = 0) -> str:
    inteiro, _, frac = f"{x:,.{casas}f}".partition(".")
    return "US$ " + inteiro.replace(",", ".") + ("," + frac if frac else "")


def bloco_qualidade(rel: dict) -> str:
    rc = rel["reconciliacao"]
    linhas = [f"- **{_milhar(rc['linhas_brutas'])}** linhas brutas = **{_milhar(rc['linhas_limpas'])}** vendas limpas + **{_milhar(rc['linhas_ajustes'])}** ajustes "
              f"(não-mercadoria e quantidade ≤ 0, guardados à parte). Valor: {_usd(rc['vendas_brutas_usd'])} = {_usd(rc['vendas_limpas_usd'])} + {_usd(rc['vendas_ajustes_usd'])}.",
              f"- **Reconciliação por semana:** {rc['semanas_conferidas']} semanas conferidas, {rc['semanas_divergentes']} divergentes "
              f"(maior diferença: {_usd(rc['maior_diferenca_semanal_usd'], 2)}; tolerância {_usd(rc['tolerancia_usd'], 2)}).",
              f"- **Nulos:** {sum(rel['nulos_por_coluna'].values())} em todas as colunas. **Duplicados:** {sum(rel['duplicados'].values())}. "
              f"**Junções que multiplicam linhas:** {sum(1 for j in rel['joins'] if not j['ok'])}.",
              f"- **Ruído de ponto flutuante** no arquivo: {rel['conversao_numerica']['SALES_VALUE']['arredondadas']} linhas de `SALES_VALUE` e "
              f"{rel['conversao_numerica']['RETAIL_DISC']['arredondadas']} de `RETAIL_DISC` (valores como `5,55E-17`); por isso os valores monetários são lidos com 4 casas decimais.",
              "", "| Regra | O que filtra | Linhas atribuídas | Valor (US$) |", "|---|---|---|---|"]
    for r in rel["regras"]:
        linhas.append(f"| `{r['regra']}` | {r['descricao']} | {_milhar(r['linhas_atribuidas'])} | {_milhar(r['valor_atribuido_usd'])} |")
    return "\n".join(linhas)


def _citacao(e: dict) -> str:
    partes = ["> **E daí?**", ">", f"> **Conclusão.** {e['conclusao']}", ">", f"> {e['evidencia']}", ">",
              f"> **Ação recomendada.** {e['acao_recomendada']}", ">", f"> **Impacto estimado.** {e['impacto_estimado']}", ">",
              f"> **Limitações.** {e['limitacoes']}", ">", "> **Detalhes técnicos.** " + " ".join(e["detalhes_tecnicos"])]
    return chr(10).join(partes)


def _resumo_de_avaliacao(arquivo: Path) -> str | None:
    if not arquivo.exists():
        return None
    return "\n".join(l for l in arquivo.read_text(encoding="utf-8").splitlines() if l.startswith("- "))


def bloco_avaliacao() -> str:
    eval_ = RAIZ / "eval"
    oraculo, bloqueio, vivo = (_resumo_de_avaliacao(eval_ / f"ULTIMO_{n}.md") for n in ("ORACULO", "BLOQUEIO", "VIVO"))
    partes = ["**Oráculo (sem modelo de linguagem)**: o SQL esperado de cada pergunta, escrito à mão, e o valor de cada ferramenta de análise, conferidos contra faixas de sanidade. "
              "Valida o conjunto de perguntas, não o modelo.", "", oraculo or "_Ainda não executado._", "",
              "**Bloqueio (sem modelo de linguagem)**: o SQL de cada pergunta maliciosa e 40 cargas de ataque passam pelo servidor MCP, o caminho real do agente.", "",
              bloqueio or "_Ainda não executado._", ""]
    if vivo:
        partes += ["**Ao vivo (com o modelo do Groq)**: o agente responde às 28 perguntas e às 6 maliciosas pelo servidor MCP.", "", vivo]
    else:
        partes += ["**Ao vivo (com o modelo do Groq)**: **ainda não medido.** Depende de uma chave do Groq no terminal de quem roda "
                   "(`set GROQ_API_KEY=...` e `venv\\Scripts\\python.exe -m eval.rodar_avaliacao --modo vivo`). Até lá, o README não afirma taxa de acerto do modelo."]
    return "\n".join(partes)


def gerar_blocos(rel: dict, seg: dict, clv: dict, churn: dict, desc: dict) -> dict[str, str]:
    return {"METRICAS": bloco_metricas(), "ESTRUTURA": bloco_estrutura(), "QUALIDADE": bloco_qualidade(rel), "AVALIACAO": bloco_avaliacao(),
            "ANALISE_RFM": _citacao(seg["e_dai"]), "ANALISE_CLV": _citacao(clv["e_dai"]),
            "ANALISE_CHURN": _citacao(churn["e_dai"]), "ANALISE_DESCONTO": _citacao(desc["e_dai"])}


def aplicar(texto: str, blocos: dict[str, str]) -> str:
    for nome, conteudo in blocos.items():
        padrao = re.compile(rf"(<!-- gerado:{nome} -->).*?(<!-- /gerado:{nome} -->)", re.S)
        if not padrao.search(texto):
            raise ValueError(f"README sem o bloco gerado:{nome}")
        texto = padrao.sub(lambda m: m.group(1) + "\n" + conteudo + "\n" + m.group(2), texto)
    return texto


def calcular_blocos() -> dict[str, str]:
    """Carrega a base (CSV/ETL local ou pacote Parquet) e roda as quatro análises pelas funções do núcleo."""
    from src import carga
    from src.nucleo import banco
    from src.nucleo.churn import prever_churn
    from src.nucleo.clv import calcular_clv
    from src.nucleo.rfm import segmentar_clientes
    from src.nucleo.teste_desconto import testar_desconto_entre_segmentos

    carregado = carga.carregar()
    banco.definir_banco(carregado.caminho_banco)
    rel = carga.relatorio(carregado.caminho_banco)
    resultados = [f() for f in (segmentar_clientes, calcular_clv, prever_churn, testar_desconto_entre_segmentos)]
    erros = [r["erro"] for r in resultados if "erro" in r]
    if erros:
        raise SystemExit(f"Alguma análise falhou: {erros}")
    return gerar_blocos(rel, *resultados)


def main(argv=None) -> int:
    verificar = "--verificar" in (argv if argv is not None else sys.argv[1:])
    atual = README.read_text(encoding="utf-8")
    novo = aplicar(atual, calcular_blocos())
    if verificar:
        print("README em dia." if novo == atual else "README velho: rode `venv\\Scripts\\python.exe -m src.documentacao`.")
        return 0 if novo == atual else 1
    README.write_text(novo, encoding="utf-8")
    print(f"README atualizado ({sum(1 for _ in re.finditer('<!-- gerado:', novo))} blocos gerados).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
