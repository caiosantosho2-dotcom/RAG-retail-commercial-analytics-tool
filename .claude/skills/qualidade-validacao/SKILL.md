---
name: qualidade-validacao
description: Use ao carregar, limpar ou auditar a base Dunnhumby deste projeto, ao revisar o relatório de qualidade, e ao validar qualquer resultado antes de mostrar (sanity check, reconciliação, validação de modelo, testes de guard-rail e avaliação do chatbot).
---

# Qualidade e validação

Fonte das regras: `docs/spec_ferramentas_mcp.md` e seção 7 de `docs/guia_projeto_dunnhumby.md`.

## Antes da análise: auditoria da base
Responda e registre no relatório de qualidade:
- O que é uma linha de cada tabela? A chave é única?
- Período coberto, buracos de datas, semanas iniciais incompletas.
- Nulos por coluna, e se nulo significa zero ou desconhecido.
- Valores negativos ou zero em `SALES_VALUE` e `QUANTITY`: devolução, ajuste ou erro?
- Sinal das colunas de desconto.
- Linhas estranhas (combustível, valor zero, quantidade extrema).
- Households sem demografia.

## Limpeza
- Cada regra registra **quantas linhas afetou e por quê**. Nada de `fillna`/`dropna` em silêncio.
- Dados brutos nunca são alterados; a limpeza gera uma nova camada.
- Venda válida = `BASKET_ID` presente e `QUANTITY > 0`. Devolução e ajuste ficam separados.
- Hash do arquivo e data da carga registrados em `log_cargas`; `versao_base` (hash dos arquivos + parâmetros + `ETL_VERSAO`) vai em todo retorno de ferramenta.
- **Reconciliação:** total por semana da base limpa = bruto menos o que foi removido de propósito. Se não bater, parar e investigar.
- Valores monetários em `DECIMAL(18,4)`: em 2 casas o ruído de ponto flutuante do arquivo faz a soma divergir do CSV.

## Antes de mostrar qualquer resultado
- Sanity check de ordem de grandeza: ticket médio (cerca de US$ 31), itens por cesta (cerca de 14), % de desconto (cerca de 15%).
- Calcular o número principal por um segundo caminho (SQL e pandas, por exemplo).
- O número do chat e o da aba de análise batem para a mesma pergunta? (cada métrica é definida uma vez, na view)
- A comparação com o ano anterior usou as mesmas semanas e as mesmas lojas?

## Validação de modelos
- Churn: split temporal e comparação com regra simples; IC da diferença de AUC por household.
- Clusters: estabilidade com outras sementes e subamostras.
- CLV: IC via bootstrap e backtest com um período para conferir no seguinte.
- Teste de desconto: tamanho de efeito e repetição sem os households de poucas compras.

## Testes e avaliação
- `pytest` para os guard-rails e o formato de cada ferramenta. Esta máquina tem pouca memória: rode **por partes, um processo por vez** (receita no `CLAUDE.md`); os testes de MCP sobem servidores e levam de 1 a 3 minutos por arquivo.
- Avaliação do chat (`eval/`), três modos:
  - `python -m eval.rodar_avaliacao --modo oraculo`: 20 perguntas de negócio com SQL esperado + 8 de análise com o valor da ferramenta (sem LLM);
  - `--modo bloqueio`: perguntas maliciosas e cargas de ataque pelo servidor MCP, meta de 100% recusadas ou limitadas, nenhum falso positivo e tabelas intactas (sem LLM);
  - `--modo vivo`: o agente de verdade (precisa de `GROQ_API_KEY` no terminal; nunca cole a chave na conversa): acerto, ferramenta certa, tokens e tempo médios, bloqueio das maliciosas.
- Nunca cite taxa de acerto do modelo sem ter rodado o modo vivo: o oráculo só prova que o valor esperado existe e é plausível.
- Rodar tudo antes de cada commit de fase e sempre que mudar prompt, glossário, views, skills ou descrições das ferramentas.
