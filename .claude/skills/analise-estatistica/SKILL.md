---
name: analise-estatistica
description: Use ao construir ou interpretar as análises estatísticas deste projeto (segmentação RFM com K-Means, CLV, modelo de churn, teste de hipótese de desconto entre segmentos), seja escrevendo o código, seja usando as ferramentas segmentar_clientes, calcular_clv, prever_churn e testar_desconto_entre_segmentos para responder perguntas.
---

# Análise estatística — clientes Dunnhumby

Fonte das regras: `docs/spec_ferramentas_mcp.md`. Modo de trabalho: `docs/guia_boas_praticas_analise_senior.md`.

## Antes de qualquer análise
1. Qual decisão ela apoia? Escreva em uma frase.
2. Qual seria um resultado surpreendente? Escreva a hipótese antes de rodar.
3. A base passou pela checagem de qualidade? (skill `qualidade-validacao`)

## Ordem e papel de cada análise
1. **RFM + K-Means** — quem são os clientes.
2. **CLV** — quanto cada segmento vale.
3. **Churn** — quem vai parar de comprar.
4. **Teste de desconto** — os segmentos recebem desconto diferente?
Cohort é gráfico de apoio dentro do RFM. Market Basket está fora do escopo.

## Regras por análise
**RFM + K-Means**
- Padronize R, F e V antes do K-Means.
- Escolha o K por silhueta e/ou cotovelo, com o gráfico. Nunca no chute.
- Teste estabilidade com outras sementes. Reporte se os segmentos se mantêm.
- Nomeie cada segmento olhando o perfil real. Nenhum segmento sem nome.
- Households com valor líquido ≤ 0 ficam fora, com a contagem documentada.

**CLV**
- Premissas explícitas: horizonte, margem assumida, método.
- Intervalo de confiança via bootstrap.

**Churn**
- Defina churn com um corte explícito (sem compra em N semanas) e justifique.
- Split **temporal**: treina num período, testa no seguinte. Nunca sorteio aleatório de linhas.
- Compare com uma regra simples. Se o modelo não ganhar, isso é o achado.
- Reporte AUC, precisão e recall na classe de churn, matriz de confusão. Cheque desbalanceamento.
- Interprete os coeficientes em linguagem de negócio.

**Teste de desconto**
- Cheque normalidade por grupo para justificar o teste não paramétrico.
- Kruskal-Wallis; post-hoc Mann-Whitney com Holm só se o geral for significativo.
- Reporte tamanho de efeito (eta²) e IC das diferenças, não só p-valor.
- Diferença entre grupos **não é** efeito causal do desconto. Escreva isso nas limitações.

## Sempre
- Documente cada escolha (K, teste, corte, threshold) e o motivo.
- Feche com o bloco "e daí?": conclusão, ação recomendada, impacto estimado, limitações.
- Título de gráfico diz a conclusão, não a descrição.

## Ao responder perguntas com as ferramentas
- Use a ferramenta certa; não tente reproduzir a análise com SQL.
- Comece pela conclusão do `e_dai`, depois o número, depois o método se perguntarem.
- Nunca omita as limitações quando a pergunta pedir uma recomendação.
