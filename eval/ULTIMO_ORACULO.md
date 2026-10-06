# Avaliação do chat (oraculo)

- Data: 2026-10-06 19:21 · base `ddb4d8032cc2`

- Valor esperado resolvido e dentro da faixa de sanidade: **100%** de 28 (20 de negócio com SQL esperado, 8 de análise com o valor da ferramenta)
- Glossário traz os termos esperados entre os 4 primeiros: **100%**

| id | tipo | oráculo | glossário | valores esperados |
|---|---|---|---|---|
| q01 | negocio | ok | ok | faturamento=2151812.0 |
| q02 | negocio | ok | ok | ticket=31.2097 |
| q03 | negocio | ok | ok | itens_por_cesta=13.8036 |
| q04 | negocio | ok | ok | pct_desconto=15.6716 |
| q05 | negocio | ok | ok | faturamento=850.82 |
| q06 | negocio | ok | ok | STORE_ID=408, ticket=55.3204 |
| q07 | negocio | ok | ok | clientes=72 |
| q08 | negocio | ok | ok | DEPARTMENT=GROCERY, desconto_cupom=9417.75 |
| q09 | negocio | ok | ok | PRODUCT_ID=5569230, PRODUCT_ID=5569471, PRODUCT_ID=8090521, PRODUCT_ID=8090537, PRODUCT_ID=1053690 |
| q10 | negocio | ok | ok | var_faturamento_pct=3.9782, var_clientes_pct=-5.7325, var_cestas_pct=-7.7398, var_ticket_pct=12.7009 |
| q11 | negocio | ok | ok | crescimento_pct=0.3965 |
| q12 | negocio | ok | ok | penetracao_atual=81.3355 |
| q13 | negocio | ok | ok | penetracao=82.8658 |
| q14 | negocio | ok | ok | PRODUCT_ID=1029743, PRODUCT_ID=1106523, PRODUCT_ID=995242 |
| q15 | negocio | ok | ok | departamentos=4 |
| q16 | negocio | ok | ok | households=214, gasto=138216.96 |
| q17 | negocio | ok | ok | STORE_ID=367, STORE_ID=406, STORE_ID=292 |
| q18 | negocio | ok | ok | lojas_so_atual=105 |
| q19 | negocio | ok | ok | var_faturamento_pct=3.4153 |
| q20 | negocio | ok | ok | clientes_ativos=2205 |
| a01 | analise | ok | ok | k_usado=4, segmento_principal=Fiéis |
| a02 | analise | ok | ok | pct_faturamento_fieis=70.9 |
| a03 | analise | ok | ok | clv_fieis=819.752 |
| a04 | analise | ok | ok | clv_total=1103220.323 |
| a05 | analise | ok | ok | segmento_maior_risco=Esporádicos, risco_pct=22.9125 |
| a06 | analise | ok | ok | auc_modelo=0.8531, auc_regra=0.7378 |
| a07 | analise | ok | ok | p_valor=0.0085 |
| a08 | analise | ok | ok | mediana_desconto_fieis=14.966 |
