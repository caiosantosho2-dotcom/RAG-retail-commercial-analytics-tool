# Auditoria da base bruta (fase 1)

## 1. Tabelas, linhas e colunas
| tabela           |   linhas | colunas                                                                                                                                      |
|:-----------------|---------:|:---------------------------------------------------------------------------------------------------------------------------------------------|
| transaction_data |  2595732 | household_key, BASKET_ID, DAY, PRODUCT_ID, QUANTITY, SALES_VALUE, STORE_ID, RETAIL_DISC, TRANS_TIME, WEEK_NO, COUPON_DISC, COUPON_MATCH_DISC |
| product          |    92353 | PRODUCT_ID, MANUFACTURER, DEPARTMENT, BRAND, COMMODITY_DESC, SUB_COMMODITY_DESC, CURR_SIZE_OF_PRODUCT                                        |
| hh_demographic   |      801 | AGE_DESC, MARITAL_STATUS_CODE, INCOME_DESC, HOMEOWNER_DESC, HH_COMP_DESC, HOUSEHOLD_SIZE_DESC, KID_CATEGORY_DESC, household_key              |
| campaign_table   |     7208 | DESCRIPTION, household_key, CAMPAIGN                                                                                                         |
| campaign_desc    |       30 | DESCRIPTION, CAMPAIGN, START_DAY, END_DAY                                                                                                    |
| coupon           |   124548 | COUPON_UPC, PRODUCT_ID, CAMPAIGN                                                                                                             |
| coupon_redempt   |     2318 | household_key, DAY, COUPON_UPC, CAMPAIGN                                                                                                     |
| causal_data      | 36786524 | PRODUCT_ID, STORE_ID, WEEK_NO, display, mailer                                                                                               |

## 2. Granularidade e chaves
| checagem                                             |   valor |
|:-----------------------------------------------------|--------:|
| transaction_data: (BASKET_ID, PRODUCT_ID) duplicado  |       0 |
| transaction_data: linhas 100% idênticas              |       0 |
| product: PRODUCT_ID duplicado                        |       0 |
| hh_demographic: household_key duplicado              |       0 |
| transaction_data: PRODUCT_ID órfão (fora de product) |       0 |
| households em transaction_data                       |    2500 |
| households sem demografia                            |    1699 |
| lojas distintas                                      |     582 |
| cestas distintas                                     |  276484 |
| cestas que aparecem em mais de uma loja ou household |       0 |

## 3. Nulos por coluna
_(vazio)_

## 4. Sinais e valores estranhos (contagem de linhas)
| metrica              |          linhas |
|:---------------------|----------------:|
| sales_negativo       |     0           |
| sales_zero           | 18850           |
| qtd_nao_positiva     | 14466           |
| qtd_zero             | 14466           |
| qtd_maior_100        | 23136           |
| qtd_max              | 89638           |
| retail_disc_positivo |    36           |
| retail_disc_negativo |     1.30303e+06 |
| coupon_disc_positivo |     0           |
| coupon_disc_negativo | 36422           |
| match_disc_positivo  |     0           |
| match_disc_negativo  | 17449           |

### Distribuição numérica
| c                 |     min |   mediana |   p99 |    max |             soma |
|:------------------|--------:|----------:|------:|-------:|-----------------:|
| SALES_VALUE       |    0    |      2    |    20 | 840    |      8.05746e+06 |
| RETAIL_DISC       | -180    |     -0.01 |     0 |   3.99 |     -1.39833e+06 |
| COUPON_DISC       |  -55.93 |      0    |     0 |   0    | -42611.5         |
| COUPON_MATCH_DISC |   -7.7  |      0    |     0 |   0    |  -7575.81        |

### Departamentos suspeitos (combustível, cupom, misc, sem cadastro)
| DEPARTMENT      |   linhas |   vendas |
|:----------------|---------:|---------:|
| KIOSK-GAS       |    22059 |   544222 |
| MISC SALES TRAN |     6050 |   119960 |
| MISC. TRANS.    |     2351 |    10679 |

### Vendas por departamento (todas)
| departamento    |   linhas |           vendas |
|:----------------|---------:|-----------------:|
| GROCERY         |  1646076 |      4.09381e+06 |
| DRUG GM         |   277232 |      1.05536e+06 |
| PRODUCE         |   257290 | 557452           |
| MEAT            |    88416 | 548787           |
| KIOSK-GAS       |    22059 | 544222           |
| MEAT-PCKGD      |   111957 | 412437           |
| DELI            |    62787 | 260867           |
| PASTRY          |    38179 | 121740           |
| MISC SALES TRAN |     6050 | 119960           |
| NUTRITION       |    32164 |  97669           |
| SEAFOOD-PCKGD   |    11216 |  63094           |
| FLORAL          |     4524 |  39653           |
| COSMETICS       |     7692 |  32360           |
| SALAD BAR       |     9516 |  30953           |
| SEAFOOD         |     4093 |  29497           |
| SPIRITS         |     2119 |  21671           |
| MISC. TRANS.    |     2351 |  10679           |
| GARDEN CENTER   |      720 |   7668           |
| TRAVEL & LEISUR |      862 |   2550           |
| CHEF SHOPPE     |      766 |   2291           |
| RESTAURANT      |      465 |   1987           |
| COUP/STR & MFG  |      817 |   1028           |
| FROZEN GROCERY  |      251 |    653           |
| AUTOMOTIVE      |       65 |    453           |
| RX              |       14 |    160           |
| GM MERCH EXP    |       49 |    101           |
| DAIRY DELI      |       53 |     73           |
| CNTRL/STORE SUP |       21 |     49           |
| PHOTO           |       17 |     41           |
| DELI/SNACK BAR  |       11 |     36           |
| VIDEO           |        3 |     35           |
| POSTAL CENTER   |       20 |     24           |
| VIDEO RENTAL    |        5 |     21           |
| PHARMACY SUPPLY |        6 |     17           |
| PORK            |        2 |     16           |
| TOYS            |        5 |     10           |
| HBC             |        4 |      9           |
| CHARITABLE CONT |        2 |      8           |
| PROD-WHS SALES  |        4 |      8           |
| MEAT-WHSE       |        6 |      7           |
| HOUSEWARES      |        1 |      3           |
| GRO BAKERY      |        2 |      2           |
| ELECT &PLUMBING |        1 |      1           |
|                 |     7839 |      0           |

### Totais de venda e desconto (conferir sinal antes de somar)
|   sales_total |   retail_total |   coupon_total |   match_total |   pct_desc_loja_sobre_bruto_hipotese |
|--------------:|---------------:|---------------:|--------------:|-------------------------------------:|
|   8.05746e+06 |   -1.39834e+06 |         -42612 |         -7576 |                                14.86 |

## 5. Cobertura temporal
|   dia_min |   dia_max |   sem_min |   sem_max |   dias_distintos |   semanas_distintas |
|----------:|----------:|----------:|----------:|-----------------:|--------------------:|
|         1 |       711 |         1 |       102 |              711 |                 102 |

Linhas em que `WEEK_NO` ≠ `ceil(DAY/7)`:
|   linhas_semana_diferente_de_formula |
|-------------------------------------:|
|                               694450 |

Dias sem nenhuma transação (até 50):
_(vazio)_

### Volume por semana (conferir semanas iniciais/finais incompletas)
|   WEEK_NO |   dias |   lojas |   households |   cestas |   vendas |
|----------:|-------:|--------:|-------------:|---------:|---------:|
|         1 |      5 |      68 |           88 |      142 |     5211 |
|         2 |      7 |      92 |          175 |      324 |    10821 |
|         3 |      7 |      91 |          228 |      482 |    13498 |
|         4 |      7 |     108 |          270 |      545 |    15966 |
|         5 |      7 |     112 |          370 |      757 |    20140 |
|         6 |      7 |     121 |          433 |      861 |    24924 |
|         7 |      7 |     120 |          491 |      999 |    28074 |
|         8 |      7 |     124 |          530 |     1086 |    31794 |
|         9 |      7 |     130 |          622 |     1212 |    31244 |
|        10 |      7 |     128 |          708 |     1553 |    42994 |
|        11 |      7 |     142 |          846 |     1823 |    51011 |
|        12 |      7 |     135 |          905 |     1926 |    53187 |
|        13 |      7 |     139 |          972 |     2203 |    55203 |
|        14 |      7 |     151 |         1119 |     2433 |    62875 |
|        15 |      7 |     144 |         1156 |     2743 |    74261 |
|        16 |      7 |     159 |         1309 |     2840 |    79135 |
|        17 |      7 |     158 |         1371 |     3048 |    79556 |
|        18 |      7 |     148 |         1313 |     3080 |    75968 |
|        19 |      7 |     142 |         1268 |     2973 |    72537 |
|        20 |      7 |     147 |         1319 |     3091 |    86109 |
|        21 |      7 |     142 |         1312 |     2999 |    83262 |
|        22 |      7 |     149 |         1313 |     3092 |    79134 |
|        23 |      7 |     145 |         1290 |     2947 |    76069 |
|        24 |      7 |     146 |         1335 |     3112 |    88706 |
|        25 |      7 |     145 |         1345 |     3094 |    88927 |
|        26 |      7 |     140 |         1303 |     2891 |    79209 |
|        27 |      7 |     137 |         1266 |     2845 |    79909 |
|        28 |      7 |     141 |         1286 |     2783 |    78556 |
|        29 |      7 |     150 |         1331 |     2997 |    89027 |
|        30 |      7 |     137 |         1285 |     2894 |    80132 |
|        31 |      7 |     134 |         1278 |     2820 |    77644 |
|        32 |      7 |     133 |         1280 |     2910 |    76724 |
|        33 |      7 |     151 |         1305 |     2957 |    85802 |
|        34 |      7 |     148 |         1292 |     2871 |    81676 |
|        35 |      7 |     137 |         1262 |     2785 |    82984 |
|        36 |      7 |     143 |         1325 |     3022 |    84084 |
|        37 |      7 |     140 |         1316 |     2958 |    87324 |
|        38 |      7 |     140 |         1284 |     2894 |    90906 |
|        39 |      7 |     143 |         1295 |     2883 |    82427 |
|        40 |      7 |     140 |         1278 |     2794 |    89985 |
|        41 |      7 |     145 |         1308 |     2982 |    83639 |
|        42 |      7 |     138 |         1318 |     2919 |    93370 |
|        43 |      7 |     135 |         1289 |     2849 |    83954 |
|        44 |      7 |     142 |         1318 |     3001 |    83094 |
|        45 |      7 |     141 |         1290 |     2861 |    79682 |
|        46 |      7 |     139 |         1335 |     3086 |    95878 |
|        47 |      7 |     138 |         1286 |     2926 |    89835 |
|        48 |      7 |     139 |         1300 |     2866 |    80300 |
|        49 |      7 |     145 |         1305 |     2944 |    85805 |
|        50 |      7 |     137 |         1332 |     2932 |    90220 |
|        51 |      7 |     137 |         1302 |     2982 |    85530 |
|        52 |      7 |     130 |         1299 |     2939 |    84886 |
|        53 |      7 |     138 |         1288 |     2868 |    83240 |
|        54 |      7 |     139 |         1315 |     2932 |    87915 |
|        55 |      7 |     145 |         1334 |     3005 |    87062 |
|        56 |      7 |     142 |         1334 |     2963 |    89058 |
|        57 |      7 |     144 |         1291 |     2957 |    82605 |
|        58 |      7 |     135 |         1286 |     2859 |    83695 |
|        59 |      7 |     150 |         1391 |     3083 |    96701 |
|        60 |      7 |     147 |         1386 |     3142 |    90987 |
|        61 |      7 |     143 |         1391 |     3156 |    90586 |
|        62 |      7 |     146 |         1362 |     3054 |    88185 |
|        63 |      7 |     146 |         1361 |     3107 |    92809 |
|        64 |      7 |     144 |         1335 |     3046 |    91182 |
|        65 |      7 |     137 |         1343 |     3067 |    87398 |
|        66 |      7 |     140 |         1283 |     2965 |    77688 |
|        67 |      7 |     144 |         1337 |     3079 |    90951 |
|        68 |      7 |     143 |         1410 |     3283 |    97967 |
|        69 |      7 |     132 |         1318 |     3033 |    86410 |
|        70 |      7 |     136 |         1315 |     3004 |    84987 |
|        71 |      7 |     136 |         1338 |     2991 |    83873 |
|        72 |      7 |     135 |         1407 |     3209 |    96930 |
|        73 |      7 |     142 |         1339 |     3052 |    87531 |
|        74 |      7 |     139 |         1309 |     2999 |    85641 |
|        75 |      7 |     137 |         1328 |     2978 |    83163 |
|        76 |      7 |     143 |         1332 |     2976 |    88851 |
|        77 |      7 |     138 |         1355 |     3004 |    92161 |
|        78 |      7 |     139 |         1295 |     2825 |    81102 |
|        79 |      7 |     142 |         1365 |     2943 |    82475 |
|        80 |      7 |     142 |         1325 |     3006 |    83204 |
|        81 |      7 |     140 |         1348 |     2988 |    90168 |
|        82 |      7 |     144 |         1360 |     3006 |    86945 |
|        83 |      7 |     135 |         1347 |     2945 |    83201 |
|        84 |      7 |     144 |         1293 |     2923 |    85936 |
|        85 |      7 |     130 |         1398 |     3132 |    97663 |
|        86 |      7 |     133 |         1341 |     2930 |    86445 |
|        87 |      7 |     133 |         1355 |     2909 |    91391 |
|        88 |      7 |     140 |         1372 |     3093 |    92470 |
|        89 |      7 |     132 |         1328 |     2893 |    90545 |
|        90 |      7 |     132 |         1356 |     2915 |    92939 |
|        91 |      7 |     134 |         1342 |     2933 |    86923 |
|        92 |      7 |     142 |         1428 |     3362 |   113193 |
|        93 |      7 |     129 |         1244 |     2547 |    80832 |
|        94 |      7 |     129 |         1363 |     3005 |    96964 |
|        95 |      7 |     131 |         1335 |     2878 |    88895 |
|        96 |      7 |     126 |         1309 |     2824 |    86810 |
|        97 |      7 |     130 |         1332 |     2913 |    88839 |
|        98 |      7 |     123 |         1384 |     3037 |    98950 |
|        99 |      7 |     130 |         1325 |     2851 |   101364 |
|       100 |      7 |     138 |         1313 |     2793 |    93063 |
|       101 |      7 |     131 |         1269 |     2682 |    84407 |
|       102 |      6 |     123 |         1205 |     2383 |    71969 |

## 6. Janela proposta: semanas 77–102 contra 25–50
|   lojas_janela_atual |   lojas_base |   lojas_nos_dois |   so_na_atual |   so_na_base |
|---------------------:|-------------:|-----------------:|--------------:|-------------:|
|                  330 |          341 |              226 |           104 |          115 |

## 7. Campanhas (para explicar a base de comparação)
|   CAMPAIGN | DESCRIPTION   |   START_DAY |   END_DAY |
|-----------:|:--------------|------------:|----------:|
|         26 | TypeA         |         224 |       264 |
|         27 | TypeC         |         237 |       300 |
|         28 | TypeB         |         259 |       320 |
|         29 | TypeB         |         281 |       334 |
|         30 | TypeA         |         323 |       369 |
|          1 | TypeB         |         346 |       383 |
|          2 | TypeB         |         351 |       383 |
|          3 | TypeC         |         356 |       412 |
|          4 | TypeB         |         372 |       404 |
|          5 | TypeB         |         377 |       411 |
|          6 | TypeC         |         393 |       425 |
|          7 | TypeB         |         398 |       432 |
|          8 | TypeA         |         412 |       460 |
|          9 | TypeB         |         435 |       467 |
|         10 | TypeB         |         463 |       495 |
|         12 | TypeB         |         477 |       509 |
|         11 | TypeB         |         477 |       523 |
|         13 | TypeA         |         504 |       551 |
|         14 | TypeC         |         531 |       596 |
|         15 | TypeC         |         547 |       708 |
|         16 | TypeB         |         561 |       593 |
|         17 | TypeB         |         575 |       607 |
|         18 | TypeA         |         587 |       642 |
|         19 | TypeB         |         603 |       635 |
|         20 | TypeC         |         615 |       685 |
|         22 | TypeB         |         624 |       656 |
|         21 | TypeB         |         624 |       656 |
|         23 | TypeB         |         646 |       684 |
|         25 | TypeB         |         659 |       691 |
|         24 | TypeB         |         659 |       719 |

`causal_data` cobre:
|   sem_min |   sem_max |   linhas |
|----------:|----------:|---------:|
|         9 |       101 | 36786524 |
