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
- Hash do arquivo e data da carga registrados em `log_cargas`.
- **Reconciliação:** total por semana da base limpa = bruto menos o que foi removido de propósito. Se não bater, parar e investigar.

## Antes de mostrar qualquer resultado
- Sanity check de ordem de grandeza: ticket médio, itens por cesta, % de desconto.
- Calcular o número principal por um segundo caminho (SQL e pandas, por exemplo).
- O número do chat e o da aba de análise batem para a mesma pergunta?
- A comparação com o ano anterior usou as mesmas semanas e as mesmas lojas?

## Validação de modelos
- Churn: split temporal e comparação com regra simples.
- Clusters: estabilidade com outras sementes.
- CLV: IC via bootstrap; se possível, prever com um período e conferir no seguinte.

## Testes e avaliação
- `pytest` para os guard-rails: escrita bloqueada, múltiplas instruções bloqueadas, limite de linhas respeitado, formato de cada ferramenta.
- Avaliação do chatbot (`eval/`): taxa de acerto, ferramenta certa, tokens e tempo médios, bloqueio de perguntas maliciosas.
- Rodar tudo antes de cada commit de fase e sempre que mudar prompt, glossário, views, skills ou descrições das ferramentas.
