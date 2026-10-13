# Composição do prompt (medição, sem otimização)

Estimativa: 4.45 caracteres por token (m05: 3150 tokens em 1 chamada sem ferramenta; 14,015 caracteres enviados e recebidos).

## Parte fixa: vai em toda chamada ao modelo

| Parte | Caracteres | Tokens (est.) | % do fixo |
|---|---:|---:|---:|
| Instruções (15 regras) | 4,028 | 905 | 32% |
| Catálogo compacto (views e colunas) | 5,166 | 1,161 | 41% |
| Esquema das 6 ferramentas | 3,557 | 799 | 28% |
| **Total fixo** | **12,751** | **2,866** | 100% |

Esquema por ferramenta (caracteres): descrever_dados 703, executar_consulta 575, segmentar_clientes 641, calcular_clv 747, prever_churn 508, testar_desconto_entre_segmentos 383.

## Por pergunta

| Parte | Média (caract.) | Máximo | Tokens médios (est.) |
|---|---:|---:|---:|
| Glossário injetado (top 4, limiar 0.3) | 926 | 1,620 | 208 |
| Pergunta | 73 | | 16 |

Glossário inteiro: 12,312 caracteres (2,767 tokens). Maiores termos: Campanha (972); Segmentação, CLV, churn e teste de desconto (662); Penetração (542); Árvore de vendas (532); Semanas com compra (380).

## Resultados de ferramenta (voltam ao modelo em cada rodada seguinte)

| Resultado | Caracteres | Tokens (est.) |
|---|---:|---:|
| executar_consulta, 20 consultas de avaliação (mediana) | 740 | 166 |
| executar_consulta, maior | 1,018 | 229 |
| segmentar_clientes | 4,965 | 1,116 |
| calcular_clv | 5,643 | 1,268 |
| prever_churn | 6,905 | 1,552 |
| testar_desconto_entre_segmentos | 8,579 | 1,928 |
| descrever_dados() | 6,815 | 1,532 |
| descrever_dados('vw_vendas_item') | 2,987 | 671 |
| descrever_dados('tudo') | 20,883 | 4,694 |

## Custo de uma pergunta típica

Cada chamada ao modelo reenvia a parte fixa e o histórico da própria pergunta (glossário, resultados anteriores).

| Cenário | Chamadas | Tokens (est.) |
|---|---:|---:|
| 1 consulta (2 chamadas) | 2 | 6,346 |
| 2 consultas (3 chamadas) | 3 | 9,768 |
| 4 consultas (5 chamadas) | 5 | 17,110 |
