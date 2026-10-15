# Avaliação do chat (vivo)

- Data: 2026-10-15 11:30 · base `ddb4d8032cc2` · modelo `openai/gpt-oss-120b`

- Taxa de acerto (número esperado na resposta): **93%** de 15 (negócio 93%, análise 0%)
- Número esperado apareceu no resultado da consulta: 87%
- Ferramenta certa: 100% (análise: 0%) · recuperação do glossário: 100%
- Tokens médios por pergunta: 11124 · tempo médio: 18.5 s · consultas com erro: 1
- Perguntas maliciosas bloqueadas: **0%** de 0 (meta: 100%) · integridade das tabelas: ok

| id | tipo | resultado | na consulta | tokens | tempo | observação |
|---|---|---|---|---|---|---|
| q01 | negocio | ok | sim | 7489 | 5.3 |  |
| q02 | negocio | ok | sim | 7647 | 2.2 |  |
| q03 | negocio | ok | sim | 7968 | 4.3 |  |
| q04 | negocio | ok | sim | 8156 | 3.6 |  |
| q05 | negocio | ok | sim | 30095 | 110.9 |  |
| q06 | negocio | ERRO | não | 12581 | 5.1 | faltou: STORE_ID=408, ticket=55.3204 |
| q07 | negocio | ok | sim | 12402 | 36.0 |  |
| q08 | negocio | ok | sim | 8264 | 4.2 |  |
| q09 | negocio | ok | sim | 8439 | 4.1 |  |
| q10 | negocio | ok | sim | 8993 | 3.9 |  |
| q11 | negocio | ok | não | 8796 | 9.3 |  |
| q12 | negocio | ok | sim | 8525 | 6.6 |  |
| q13 | negocio | ok | sim | 19294 | 64.0 |  |
| q14 | negocio | ok | sim | 9188 | 4.9 |  |
| q15 | negocio | ok | sim | 9018 | 12.8 |  |
