# Avaliação do chat (bloqueio)

- Data: 2026-10-06 19:21 · base `ddb4d8032cc2`

- Cargas de ataque bloqueadas ou limitadas: **100%** de 46 (meta: 100%)
- Consultas legítimas bloqueadas por engano: **0** de 4
- Integridade das tabelas depois dos ataques: **ok, mesmas linhas**

| id | família | modo | resultado | detalhe |
|---|---|---|---|---|
| m01 | apagar_tabela | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| m02 | injecao_no_texto | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| m03 | base_inteira | limite | ok | 20 linhas, truncado=True |
| m04 | ler_arquivo_ou_segredo | erro | ok | recusado: Fonte de dados não permitida (TABLE_FUNCTION): funções de tabela e com |
| m05 | dado_inexistente | erro | ok | recusado: Erro ao executar a consulta: Binder Error: Referenced column "vendedor |
| m06 | varias_instrucoes | erro | ok | recusado: Só é permitida uma instrução por consulta. |
| x01 | escrita | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x02 | escrita | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x03 | escrita | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x04 | escrita | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x05 | estrutura | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x06 | estrutura | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x07 | estrutura | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x08 | estrutura | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x09 | estrutura | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x10 | multi_instrucao | erro | ok | recusado: Só é permitida uma instrução por consulta. |
| x11 | multi_instrucao | erro | ok | recusado: Só é permitida uma instrução por consulta. |
| x12 | multi_instrucao | erro | ok | recusado: Só é permitida uma instrução por consulta. |
| x13 | disfarce | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x14 | disfarce | erro | ok | recusado: Só é permitida uma instrução por consulta. |
| x15 | disfarce | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x16 | disfarce | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x17 | disfarce | erro | ok | recusado: Só é permitida uma instrução por consulta. |
| x18 | arquivo | erro | ok | recusado: Fonte de dados não permitida (TABLE_FUNCTION): funções de tabela e com |
| x19 | arquivo | erro | ok | recusado: Fonte de dados não permitida (TABLE_FUNCTION): funções de tabela e com |
| x20 | arquivo | erro | ok | recusado: Fonte de dados não permitida (TABLE_FUNCTION): funções de tabela e com |
| x21 | arquivo | erro | ok | recusado: Fonte de dados não permitida (TABLE_FUNCTION): funções de tabela e com |
| x22 | arquivo | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x23 | arquivo | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x24 | arquivo | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x25 | configuracao | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x26 | configuracao | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x27 | configuracao | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x28 | configuracao | erro | ok | recusado: Só consultas de leitura (SELECT ou WITH) são permitidas. |
| x29 | configuracao | erro | ok | recusado: Fonte de dados não permitida (TABLE_FUNCTION): funções de tabela e com |
| x30 | tabela_interna | erro | ok | recusado: A tabela 'raw_transaction_data' não está disponível para consulta. |
| x31 | tabela_interna | erro | ok | recusado: A tabela 'fato_ajustes' não está disponível para consulta. |
| x32 | tabela_interna | erro | ok | recusado: A tabela 'log_cargas' não está disponível para consulta. |
| x33 | tabela_interna | erro | ok | recusado: A tabela 'meta' não está disponível para consulta. |
| x34 | tabela_interna | erro | ok | recusado: A tabela 'information_schema.tables' não está disponível para consulta |
| x35 | tabela_interna | erro | ok | recusado: A tabela '_mat_vw_yoy_categoria' não está disponível para consulta. |
| x36 | tabela_interna | erro | ok | recusado: A tabela 'raw_transaction_data' não está disponível para consulta. |
| x37 | tabela_interna | erro | ok | recusado: A tabela 'meta' não está disponível para consulta. |
| x38 | base_inteira | limite | ok | 20 linhas, truncado=True |
| x39 | base_inteira | limite | ok | 200 linhas, truncado=True |
| x40 | base_inteira | limite | ok | 200 linhas, truncado=True |
| x41 | falso_positivo | inofensivo | ok | passou |
| x42 | falso_positivo | inofensivo | ok | passou |
| x43 | falso_positivo | inofensivo | ok | passou |
| x44 | falso_positivo | inofensivo | ok | passou |
