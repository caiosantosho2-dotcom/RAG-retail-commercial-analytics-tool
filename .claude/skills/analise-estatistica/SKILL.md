---
name: analise-estatistica
description: Use ao construir ou interpretar as análises estatísticas deste projeto (segmentação RFM com K-Means, CLV, modelo de churn, teste de hipótese de desconto entre segmentos), seja escrevendo o código, seja usando as ferramentas segmentar_clientes, calcular_clv, prever_churn e testar_desconto_entre_segmentos para responder perguntas.
---

# Análise estatística — clientes Dunnhumby

Fonte das regras: `docs/spec_ferramentas_mcp.md`. Modo de trabalho: `docs/guia_boas_praticas_analise_senior.md`.

## Qual ferramenta usar
| Pergunta | Ferramenta |
|---|---|
| "Quem são os clientes?", "quais segmentos existem?" | `segmentar_clientes` |
| "Quanto vale cada grupo de clientes?" | `calcular_clv` (`segmento` opcional) |
| "Quem vai parar de comprar?", "qual segmento está em risco?" | `prever_churn` (`segmento` opcional) |
| "Os segmentos recebem desconto diferente?" | `testar_desconto_entre_segmentos` |
| Número pontual (vendas, ticket, loja) | `executar_consulta` (skill `consultas-sql`) |

Nenhuma delas recebe SQL e nenhuma devolve a lista de households. Não reproduza a análise com SQL.

## Antes de qualquer análise
1. Qual decisão ela apoia? Escreva em uma frase.
2. Qual seria um resultado surpreendente? Escreva a hipótese antes de rodar.
3. A base passou pela checagem de qualidade? (skill `qualidade-validacao`)

## Ordem e papel de cada análise
1. **RFM + K-Means** — quem são os clientes.
2. **CLV** — quanto cada segmento vale.
3. **Churn** — quem vai parar de comprar.
4. **Teste de desconto** — os segmentos recebem desconto diferente?
Coorte de retenção é gráfico de apoio dentro do RFM. Market Basket está fora do escopo.

## Regras por análise
**RFM + K-Means**
- R em dias; F e V em log1p; tudo padronizado antes do K-Means. SQL ordenado por `household_key` (o K-Means depende da ordem das linhas).
- O K sai de uma **regra escrita antes de rodar** (`analises.rfm` no `config.yaml`): K ≥ 3, concordância entre sementes e subamostras (ARI mínima ≥ 0,90), menor segmento ≥ 5%, silhueta ≥ 0,25; vence a maior silhueta. A silhueta pura escolheria K=2, que só separa ativos de inativos. Reporte também a estabilidade.
- Segmentos nomeados pelo perfil real: Fiéis, Regulares, Esporádicos e **Em pausa** (recência ≥ 56 dias). Nenhum segmento sem nome.
- Households sem compra na janela (79) e com valor líquido ≤ 0 ficam fora, com a contagem documentada.

**CLV**
- Método: margem × gasto médio das últimas 26 semanas × razão (gasto nas 52 semanas seguintes ÷ gasto nas 26 anteriores) do mesmo segmento um ano antes. Households sem compra na janela formam o grupo "Sem compra na janela".
- **Margem (25%) e horizonte (52 semanas) são premissas**, não dado da base: diga sempre.
- IC de 95% por bootstrap. Backtest de 26 semanas disponível; o horizonte de 52 semanas não tem backtest.
- O CLV vale como **média de grupo**, não como previsão por household (o erro individual é igual ao da regra ingênua).

**Churn**
- Churn aqui é **pausa longa**: sem compra nas próximas 8 semanas. Não é saída definitiva: cerca de 80% de quem pausa volta em 18 semanas. Não escreva "perdeu o cliente".
- Split **temporal**: fotos de treino, uma de validação (define o limiar por F1) e duas de teste, com rótulos que não se sobrepõem. Nunca sorteio aleatório de linhas.
- Compare sempre com a regra simples ("sem compra há k semanas"). Se o modelo não ganhar, isso é o achado.
- Reporte AUC, AUC-PR, precisão e recall na classe de churn, matriz de confusão e calibração. A precisão por alerta é modesta (cerca de 29%): fale em "priorizar", não em "prever".
- Coeficientes em linguagem de negócio; são associação, não causa, e os fatores são correlacionados.
- Diga onde estão as pausas e onde está o dinheiro: não são o mesmo segmento.

**Teste de desconto**
- Hipótese escrita antes: os segmentos recebem desconto parecido. Cheque normalidade por grupo para justificar o teste não paramétrico.
- Kruskal-Wallis; post-hoc Mann-Whitney com Holm só se o geral for significativo.
- Com ~2.400 households quase tudo é "significativo": o veredito exige também efeito (eta² ≥ 1% ou um par com ≥ 1 ponto percentual e IC fora de zero). Três vereditos: sem diferença detectável, diferença desprezível, diferença relevante.
- Repita só com households de 5 ou mais compras: o % de desconto de quem comprou pouco é ruído. Se o veredito mudar, o resultado depende do ruído.
- Diferença entre grupos **não é** efeito causal do desconto. Está nas limitações e precisa aparecer na resposta.

## Sempre
- Documente cada escolha (K, teste, corte, threshold) e o motivo.
- Feche com o bloco "e daí?": conclusão, ação recomendada, impacto estimado, limitações.
- Título de gráfico diz a conclusão, não a descrição.
- Números e rótulos em português (vírgula decimal, US$).

## Ao responder perguntas com as ferramentas
- Comece pela conclusão do `e_dai`, depois o número, depois o método se perguntarem. Resuma o retorno: não despeje o JSON.
- Cite as premissas que mudam o número (margem do CLV, definição de churn, janela).
- Nunca omita as limitações quando a pergunta pedir uma recomendação.
- Se a ferramenta devolver `erro`, diga o que falta (`sugestao`) em vez de estimar de cabeça.
