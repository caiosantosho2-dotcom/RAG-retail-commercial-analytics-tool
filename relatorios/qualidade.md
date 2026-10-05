# Relatório de qualidade dos dados

- **versao_base:** `e402c867f49e` · carga em 2026-10-05T19:52:21
- **Reconciliação com o bruto:** OK (102 semanas conferidas, 0 divergentes, maior diferença semanal US$ 0.0000)

## 1. Do bruto ao limpo
2,595,732 linhas brutas = 2,548,662 em `fato_transacoes` + 47,070 em `fato_ajustes`. Vendas: US$ 8,057,463.08 bruto = US$ 7,376,322.37 limpo + US$ 681,140.71 ajustes.

Cada linha cai numa única regra (por precedência, na ordem abaixo). `linhas_afetadas` conta quem satisfaz a regra independentemente das outras.

| regra | descricao | linhas_afetadas | linhas_atribuidas | valor_atribuido_usd | motivo |
|---|---|---|---|---|---|
| valor_nao_numerico | QUANTITY ou SALES_VALUE ausente ou não numérico | 0 | 0 | 0.00 | Sem quantidade ou valor a linha não é venda mensurável. |
| cesta_ausente | BASKET_ID ausente | 0 | 0 | 0.00 | Venda válida exige cesta; sem ela não há transação concluída. |
| chave_ou_data_invalida | DAY, WEEK_NO, household, loja ou produto ausente/inválido | 0 | 0 | 0.00 | Sem data não entra em recência/cohort; sem chave não entra no esquema. |
| nao_mercadoria | Combustível, transações diversas e pseudo-itens de cupom | 32,805 | 32,805 | 681,121.53 | Não é mercadoria: distorce itens por cesta e ticket (pseudo-itens chegam a 89 mil unidades). Decisão A, 2026-10-05. |
| quantidade_nao_positiva | QUANTITY menor ou igual a zero | 14,466 | 14,265 | 19.18 | Venda válida exige QUANTITY > 0. Na auditoria só havia QUANTITY = 0 (sem devoluções). |

## 2. Conversão numérica (QUANTITY, SALES_VALUE, descontos, chaves)
| coluna | ausentes | nao_numericos | arredondadas | efeito_arredondamento_usd |
|---|---|---|---|---|
| household_key | 0 | 0 | 0 | 0.00 |
| BASKET_ID | 0 | 0 | 0 | 0.00 |
| DAY | 0 | 0 | 0 | 0.00 |
| PRODUCT_ID | 0 | 0 | 0 | 0.00 |
| QUANTITY | 0 | 0 | 0 | 0.00 |
| SALES_VALUE | 0 | 0 | 29 | -0.00 |
| STORE_ID | 0 | 0 | 0 | 0.00 |
| RETAIL_DISC | 0 | 0 | 34 | -0.00 |
| COUPON_DISC | 0 | 0 | 0 | 0.00 |
| COUPON_MATCH_DISC | 0 | 0 | 0 | 0.00 |
| WEEK_NO | 0 | 0 | 0 | 0.00 |

Valores monetários são lidos com 4 casas decimais. `arredondadas` conta as linhas com mais casas que isso (ruído de ponto flutuante do arquivo, como 5.55E-17) e `efeito_arredondamento_usd` a diferença que o arredondamento causa na soma.

Descontos nulos convertidos para 0 na venda válida: RETAIL_DISC = 0, COUPON_DISC = 0, COUPON_MATCH_DISC = 0. Horários inválidos (`hora` fica nula): 0.

## 3. JOINs (linhas antes e depois)
| join | antes | depois | ok |
|---|---|---|---|
| product -> dim_produto (chave única) | 92,353 | 92,353 | True |
| raw_transaction_data -> dim_produto (LEFT) | 2,595,732 | 2,595,732 | True |
| households -> hh_demographic (LEFT) | 2,500 | 2,500 | True |

## 4. Nulos e duplicados no bruto
| coluna | nulos |
|---|---|
| household_key | 0 |
| BASKET_ID | 0 |
| DAY | 0 |
| PRODUCT_ID | 0 |
| QUANTITY | 0 |
| SALES_VALUE | 0 |
| STORE_ID | 0 |
| RETAIL_DISC | 0 |
| COUPON_DISC | 0 |
| COUPON_MATCH_DISC | 0 |
| WEEK_NO | 0 |
| TRANS_TIME | 0 |

Duplicados e órfãos: product_id_duplicado = 0, produto_orfao = 0, cesta_produto_repetido = 0, linhas_identicas = 0

## 5. Casos mantidos na venda (registro)
| caso | linhas |
|---|---|
| itens_gratis_sales_zero_qtd_positiva | 3,994 |
| retail_disc_positivo_estorno | 2 |
| coupon_disc_positivo | 0 |
| coupon_match_positivo | 0 |
| departamento_vazio | 0 |
| quantidade_extrema_gt_100 | 1 |

## 6. Cobertura
- Households: 2,500 (1,699 sem demografia, 68%) · lojas: 582 · semanas: 102
- DAY 1–711 (datas 2016-01-01 a 2017-12-11; data-base arbitrária, o dataset não tem calendário real)
- Semanas incompletas: WEEK_NO 1 (5 dias), WEEK_NO 102 (6 dias)
- `causal_data` (display/mailer) cobre as semanas 9–101

## 7. Sanity check (provisório)
- Ticket médio: US$ 29.39 · itens por cesta: 13.3 · desconto: 16.1% do bruto (US$ 1,417,355 sobre US$ 7,376,322 líquidos)
- Provisório: a definição oficial vem das views da fase 3.
