# Assistente Comercial + Análise de Clientes (Dunnhumby)

Este arquivo é lido no início de toda sessão. O briefing completo está em
`docs/guia_projeto_dunnhumby.md` (fonte da verdade) e o modo de trabalho em
`docs/guia_boas_praticas_analise_senior.md`. Em caso de dúvida, consulte o guia
antes de decidir.

## Visão geral

Ferramenta para a área comercial de varejo. O usuário exporta uma planilha do
BI, arrasta para o app e:
- pergunta em linguagem de negócio num **chat** que responde consultando os
  dados via SQL (produto principal, segunda aba, depois do Resumo);
- consulta **abas de análise estatística** de clientes, com a conclusão de
  negócio em destaque (voltadas à gerência e diretoria).

Por que a carga é por arquivo: no varejo, o banco do BI é controlado pelo time
de dados e as áreas de negócio não têm acesso a ele. A carga por planilha é
escolha de produto, não limitação.

## Arquitetura

- Funções Python do núcleo (consulta, segmentação, CLV, churn, teste de
  desconto) → servidor MCP que só embrulha essas funções.
- O mesmo servidor atende o app Streamlit (agente Groq via
  `langchain-mcp-adapters`, app público, gratuito) e o Claude Desktop/Code
  (com as skills em `.claude/skills/`).
- `docs/spec_ferramentas_mcp.md` é a fonte única das regras das ferramentas.
  Skills e prompt do Groq são escritos a partir dela; se mudar, muda lá.
- Guard-rails no código, com testes. Nunca só em texto.

## Dados

- Dataset público **Dunnhumby "The Complete Journey"** (2.500 households,
  ~2 anos, ~500 lojas). Tabelas e armadilhas: seção 2 do guia.
- Janela de análise: últimas 26 semanas de `WEEK_NO`. Base de comparação:
  mesmas semanas do ano anterior (`WEEK_NO - 52`), alinhadas por semana,
  comparando só lojas presentes nos dois períodos.
- `SALES_VALUE` já é líquido. Descontos (`RETAIL_DISC`, `COUPON_DISC`,
  `COUPON_MATCH_DISC`) servem para decompor; conferir o sinal antes de somar.
- `DAY` é inteiro relativo: converter para data real antes de qualquer análise.
- Não existe vendedor individual. A menor unidade de equipe é a loja.

## Regras inegociáveis

1. O Resumo é a primeira aba; o chat é a segunda e o centro do produto: glossário RAG
   injetado no prompt, SQL visível num expander, contador de tokens na sidebar.
2. Carga por upload (CSV/Excel) e por pasta `data/`; o upload tem prioridade.
3. Cada métrica é definida **uma vez**, como view no DuckDB. Chat, abas e
   notebook usam essas views. Nunca dois números para a mesma pergunta.
4. Toda comparação temporal usa a base do ano anterior (regras acima).
5. Toda aba de análise começa pelo bloco "e daí?": conclusão, ação
   recomendada, impacto estimado, limitações. Gráficos vêm depois.
6. Toda regra de limpeza registra quantas linhas afetou e por quê. O total
   limpo reconcilia com o bruto. Nada de `fillna`/`dropna` em silêncio.
7. README completo, cobrindo o projeto inteiro (seção 9 do guia), com tom
   técnico e explicativo.
8. README e app **não** mencionam saída de emprego nem versão anterior.
9. Nenhuma análise fora do escopo da seção 6 do guia sem eu aprovar.

## Estrutura de pastas (proposta inicial — ajustar na fase de plano)

- `docs/` — guias do projeto (não editar sem pedir)
- `referencia/` — código de uma versão anterior; ver seção 8 do guia
- `data/raw/` — dados originais, nunca alterados
- `data/processed/` — recorte em Parquet (janela atual + ano anterior)
- `src/` — ETL, views de métricas, análises, glossário, agente
- `src/mcp_server.py` — servidor MCP (só embrulha funções de `src/`)
- `app/` — Streamlit
- `notebooks/` — notebook narrado final
- `tests/` — pytest (guard-rails, formato das ferramentas, métricas)
- `eval/` — perguntas de teste (negócio + maliciosas) e script de avaliação
- `logs/` — log de chamadas das ferramentas (fora do Git)
- `.claude/skills/` — skills `consultas-sql`, `analise-estatistica`,
  `qualidade-validacao`
- `config.yaml` — janela de semanas, semente, parâmetros

## Convenções

- Python + DuckDB + pandas + scikit-learn + scipy/statsmodels; LangChain +
  Groq no agente; Streamlit no app.
- `requirements.txt` com versões travadas; semente fixa em tudo que for
  aleatório; parâmetros no `config.yaml`, não espalhados no código.
- Chave do Groq via `st.secrets` ou campo na sidebar. Nunca no código.
- Conexão do agente com o banco **só leitura**; listagens com `LIMIT 20`.
- Contar linhas antes e depois de cada JOIN.
- Títulos de gráfico dizem a conclusão, não a descrição.
- Documentar toda escolha estatística (K do cluster, teste usado, corte de
  churn, threshold) e o motivo.

## Git e segurança

- Um commit ao fim de cada fase aprovada, com mensagem descritiva
  (`feat:`, `fix:`, `docs:`, `chore:`).
- Nunca versionar `data/raw/`, `venv/`, `.env`, `.streamlit/secrets.toml`.
  Arquivo novo que não deve subir → atualizar o `.gitignore`.
- Nunca ler, imprimir ou copiar o conteúdo de `.env` ou `secrets.toml`.

## Como trabalhar comigo

- Fluxo de cada fase: explorar → planejar → implementar → verificar → commit.

- Antes de codar uma fase, apresente o plano e espere minha aprovação.
- Pare no fim de cada fase para eu revisar.
- Se uma decisão estatística ou de negócio não estiver no guia, pergunte.
  Se decidir algo pequeno, registre em "Decisões registradas" abaixo.
- Faça sanity check dos números antes de mostrar (ticket médio, itens por
  cesta, % de desconto na ordem de grandeza certa).
- Modelo de churn: split temporal e comparação com uma regra simples.

## Comandos

Ambiente: Windows, `venv/` com Python 3.14. Rodar a partir da raiz.

```
venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # instalar tudo (testes, notebook); só o app: requirements.txt
venv\Scripts\python.exe gerar_requirements.py              # regenera requirements.txt (app) e requirements-dev.txt a partir do ambiente
set KAGGLE_API_TOKEN=...  (ou ~/.kaggle/kaggle.json)         # credencial, nunca no código
venv\Scripts\python.exe baixar_dados.py                       # baixa data/raw/
venv\Scripts\python.exe -m src.auditoria                      # relatorios/auditoria_fase1.md
venv\Scripts\python.exe -m src.etl                            # ETL (~2 min): data/processed/dunnhumby.duckdb + relatorios/qualidade.md
venv\Scripts\python.exe -m src.pacote exportar              # grava data/processed/parquet/ (versionado) a partir do banco do ETL; `verificar` confere
venv\Scripts\python.exe -m src.documentacao                 # reescreve os blocos gerados do README (--verificar só confere)
venv\Scripts\python.exe -m src.views                          # recria as views num banco existente (~10 s)
venv\Scripts\python.exe -m pytest tests -q                    # testes (705 até a 8; os da base completa pulam se o banco não existir)
# Em máquina com pouca memória (3,9 GB aqui) o suíte inteiro num só processo foi encerrado pelo sistema: rode por partes,
# um processo cada: (1) test_cores test_cache test_graficos test_glossario test_views_sintetico test_ferramentas_formato test_skills_e_spec (180)
# (2) test_nucleo_guardrails test_carga test_agente test_etl_regras (157) (3) test_etl_base_completa
# test_views_base_completa (35) (4) test_rfm test_rfm_janelas test_rfm_base_completa (49) (5) test_clv (36) (6) test_churn (44) (7) test_teste_desconto (25)
# (8) test_app (14), test_app_segmentos (9), test_app_clv (9), test_app_churn (10), test_app_desconto (9), um por processo
# (9) test_mcp_server (19), test_agente_mcp (15), test_app_mcp (6), test_eval (52), test_notebook (12), test_pacote (11), test_readme (13): sobem o servidor, executam o notebook ou rodam as análises (lentos: ~1 a 3 min cada)
venv\Scripts\python.exe -m src.mcp_server                     # servidor MCP (stdio); ASSISTENTE_BANCO e ASSISTENTE_LOG opcionais
venv\Scripts\python.exe notebooks\construir_notebook.py       # monta, executa e salva o notebook narrado com as saídas (~1,5 min; precisa do banco)
venv\Scripts\python.exe -m streamlit run app/app.py           # app (upload > CSV em data/ ou data/raw/ > pacote Parquet; carrega sozinho)
venv\Scripts\python.exe -m eval.rodar_avaliacao --modo oraculo   # sem LLM: 20 SQLs esperados + 8 valores das ferramentas (eval/ULTIMO_ORACULO.md)
venv\Scripts\python.exe -m eval.rodar_avaliacao --modo bloqueio  # sem LLM: 6 perguntas maliciosas + 40 cargas de ataque pelo MCP (eval/ULTIMO_BLOQUEIO.md)
set GROQ_API_KEY=...                                          # no SEU terminal; nunca colar a chave na conversa
venv\Scripts\python.exe -m eval.rodar_avaliacao --modo vivo      # com o agente: taxa de acerto, tokens, tempo (eval/ULTIMO_VIVO.md)
```

Chave do Groq: variável `GROQ_API_KEY` (avaliação), `st.secrets["GROQ_API_KEY"]` (deploy) ou o campo da barra lateral.

(Fase 6 completa: servidor MCP, agente via MCP, avaliação (oráculo, bloqueio e vivo) e skills revisadas. Falta só rodar o modo vivo com a GROQ_API_KEY do usuário.)

## Decisões registradas

- 2026-10-05 — Python 3.14 mantido; dependências do núcleo instalam. Pesadas
  (torch, streamlit, langchain, mcp) resolvem em dry-run; instalar na fase 4.
- 2026-10-05 — Teste de desconto usa o K validado do RFM, não força 4 segmentos.
- 2026-10-05 — Moeda: US$ (dataset em dólar). Desconto % = (RETAIL_DISC +
  COUPON_DISC + COUPON_MATCH_DISC) / bruto, com bruto = SALES_VALUE − descontos
  (descontos vêm negativos; 36 linhas de RETAIL_DISC positivo, tratadas como estorno).
- 2026-10-05 — Auditoria: sem nulos, duplicados nem órfãos; sem SALES_VALUE ou
  QUANTITY negativos (não há devolução). Ticket médio bruto US$ 29,14.
- 2026-10-05 — (A) Fora das métricas de venda: departamentos KIOSK-GAS, MISC SALES
  TRAN, MISC. TRANS., COUP/STR & MFG e COMMODITY_DESC = 'COUPON/MISC ITEMS'
  (combustível e pseudo-itens de cupom, com quantidades de até 89 mil). Ficam em
  camada separada, com contagem por regra e reconciliação com o bruto. Itens
  grátis (SALES_VALUE = 0 com QUANTITY > 0) permanecem: são itens reais.
- 2026-10-05 — (B) Janela: semanas 76–101 contra 24–49. A WEEK_NO 102 tem 6 dias
  e a 1 tem 5; a 102 sai da janela (`ignorar_semanas_finais: 1` no config).
  Semanas começam no DAY 6, 13, ... (não coincidem com ceil(DAY/7)).
- 2026-10-05 — Pendências para a fase 3: quanto das vendas as 226 lojas
  like-for-like representam; `causal_data` só cobre semanas 9–101; `TRANS_TIME`
  vem como texto; só 801 de 2.500 households têm demografia.
- 2026-10-05 — Fase 2: valores monetários lidos como DECIMAL(18,4), não (18,2). O
  arquivo traz ruído de ponto flutuante (ex.: 5.55E-17, 29 linhas de SALES_VALUE e 34
  de RETAIL_DISC); em 2 casas a soma divergia US$ 0,10 do CSV e a reconciliação
  interna não via isso. O teste contra o CSV (caminho independente) pegou. O relatório
  registra linhas arredondadas e o efeito em US$.
- 2026-10-05 — Fase 2: cada linha bruta cai numa só regra, por precedência (valor não
  numérico > cesta ausente > chave/data inválida > não-mercadoria > quantidade ≤ 0);
  o relatório mostra também as linhas afetadas por regra sem precedência.
  Resultado: 2.595.732 brutas = 2.548.662 em fato_transacoes + 47.070 em fato_ajustes
  (32.805 não-mercadoria + 14.265 quantidade ≤ 0). `data = data_base + (DAY − 1)`.
- 2026-10-05 — Fase 2: banco em `data/processed/dunnhumby.duckdb` (ignorado pelo Git).
  `causal_data` (36,8 M linhas) entra só agregada por semana e loja
  (`causal_semana_loja`). `fato_transacoes` não carrega WEEK_NO (vem de `dim_data`).
- 2026-10-05 — Fase 3 (aprovadas A–D): (A) a janela termina na última WEEK_NO com 7 dias
  (dinâmico, em `vw_janela`); `janela.ignorar_semanas_finais` saiu do config. (B) cliente
  ativo = ≥ 1 compra nas últimas 8 semanas do período (p95 do intervalo entre compras = 5
  semanas, p99 = 11; 91,1% dos households da janela atual ficam ativos). (C) like-for-like
  só de lojas (≥ 1 cesta nos dois períodos); `clientes_nos_dois_periodos` à parte.
  (D) `amostra_pequena` = loja com < 100 cestas na janela (211 de 319 lojas, 1,3% do
  faturamento; as 104 lojas com ≥ 200 cestas fazem 97,6%). Parâmetros em `config.yaml`.
- 2026-10-05 — Fase 3: descontos viram valores positivos nas views (desconto_total =
  −(RETAIL + COUPON + MATCH); desconto_loja = RETAIL; desconto_cupom = COUPON + MATCH);
  percentuais em 0–100; colunas das views em português (faturamento = SALES_VALUE,
  quantidade = QUANTITY). As views agregadas só enxergam as duas janelas (a WEEK_NO 102
  fica em `vw_vendas_item` com `periodo` nulo). "Último mês" = 4 semanas completas
  terminando na semana final da janela; "último trimestre" = 13.
- 2026-10-05 — Fase 3: `executar_consulta` (fase 4) não pode enxergar `raw_*` nem
  `fato_ajustes`: validador por allowlist de tabelas referenciadas (o DuckDB read-only
  não restringe por tabela). Definições das métricas: tabela `metricas_definicao`
  (fonte do `descrever_dados`, do glossário e do README).
- 2026-10-06 — Fase 4 (aprovadas A–C): (A) upload mínimo = `transaction_data` + `product`; as
  outras seis tabelas são opcionais e entram vazias (com aviso do que deixa de existir).
  (B) chave do Groq por `GROQ_API_KEY` no terminal do usuário. (C) views lentas materializadas
  como `_mat_*` a partir do mesmo SQL (`views.MATERIALIZAR`): todas respondem em < 1 s.
- 2026-10-06 — Glossário sem torch: o `torch` não carrega nesta máquina (falta o Visual C++
  Redistributable 2015-2022; RAM 3,9 GB). Escolha do usuário: TF-IDF de n-gramas (scikit-learn),
  mesma função `buscar_termos_relevantes`, mais bônus de 0,30 quando o termo ou um sinônimo
  aparece na pergunta como palavra inteira. Pico de RAM do app com dados reais: 266 MB. O
  conteúdo vem de `src/glossario_termos.py` e puxa fórmulas de `views.METRICAS` (fonte única);
  não há termo "Vendedor" (não existe no dataset; a regra está no prompt).
- 2026-10-06 — Guard-rails em camadas (`src/nucleo/consulta.py`): uma instrução (contada pelo
  parser); só SELECT/WITH via `json_serialize_sql` (o tipo da instrução NÃO basta: `PRAGMA
  version` aparece como SELECT); só fontes BASE_TABLE/JOIN/SUBQUERY/VALUES, sem funções de
  tabela; allowlist de tabelas com escopo de CTE; motor read_only, sem acesso a arquivos,
  configuração travada e memória limitada; limite 20/200 linhas, 60 KB e timeout de 30 s.
  Tabelas visíveis: `vw_*`, `dim_*`, `fato_transacoes`, `campaign_*`, `coupon*`,
  `causal_semana_loja`, `metricas_definicao` (a spec diz "views": pedir para atualizar a spec).
- 2026-10-06 — Sessões isoladas: o app prende as ferramentas ao banco de cada sessão
  (`banco.usando`, ContextVar); `banco.definir_banco` é só o padrão de scripts e testes.
- 2026-10-06 — `versao_base` = hash dos arquivos + parâmetros do config (dados, janela, métricas,
  limpeza) + `ETL_VERSAO` (hoje "3"): mudar parâmetro ou lógica invalida o cache. Hash dos
  arquivos guardado em memória por (caminho, tamanho, mtime). Tabelas auxiliares com tipos
  explícitos (arquivo vazio faria o DuckDB inferir texto).
- 2026-10-06 — Negócio: laticínios = COMMODITY_DESC IN ('FLUID MILK PRODUCTS', 'MILK BY-PRODUCTS',
  'CHEESE', 'CHEESES', 'YOGURT', 'BUTTER', 'MISC. DAIRY') (ovos e sorvete fora); cliente de alta
  frequência = `frequencia` > percentil 75 do período; rankings de loja filtram
  `amostra_pequena = FALSE`.
- 2026-10-06 — Orçamento de tokens (estimado, ~3,6 caracteres/token): ~2.000 tokens fixos por
  chamada ao modelo (prompt 1.800 + ferramentas 200), ~4.600 por pergunta com uma consulta,
  retorno de 20 linhas ≈ 370. No limite de 12 mil tokens/min do plano gratuito: ~2,6
  perguntas/min; a avaliação ao vivo espera entre perguntas.
- 2026-10-06 — Avaliação v1 (`eval/`): 20 perguntas com SQL esperado à mão. Modo oráculo: 20/20
  SQLs válidos e na faixa de sanidade; glossário traz os termos esperados em 20/20. A taxa de
  acerto ao vivo depende de `GROQ_API_KEY` (pendente).
- 2026-10-06 — App: abas "Chat" (primeira) e "Dados e qualidade"; as abas de análise entram na
  fase 5 entre as duas, cada uma abrindo com o bloco "e daí?".
- 2026-10-06 — Fase 5 (aprovadas A–D): uma análise por vez, com revisão e commit a cada uma
  (5a RFM, 5b CLV, 5c churn, 5d teste de desconto). K=4 pela regra combinada; CLV com margem de
  25% e horizonte de 52 semanas (premissas no config); churn de 8 semanas com split temporal;
  coorte de apoio ao RFM.
- 2026-10-06 — 5a (RFM): regra de K escrita antes de rodar (`analises.rfm` no config): K >= 3,
  ARI mínima >= 0,90 entre sementes e subamostras, menor segmento >= 5%, silhueta >= 0,25; vence a
  maior silhueta. Resultado: só K=4 passa (silhueta 0,37; ARI mín. 0,95-0,97); a silhueta pura
  escolheria K=2 (0,52), que só separa ativos de inativos; K=3 e K=6 ficam pouco abaixo de 0,90
  de ARI. Variáveis: recência em dias, frequência e valor em log1p, padronizados. SQL ordenado por
  household_key (o K-Means depende da ordem das linhas). 79 households sem compra na janela ficam
  fora e são contados. Nomes vêm do perfil: recência média >= 8 semanas (56 dias) = Inativos; os
  demais por valor médio (Fiéis, Regulares, Esporádicos).
- 2026-10-06 — 5a (coorte): com blocos de 8 semanas e painel inicial até a semana 14 só
  sobrariam 2 coortes úteis (a entrada acontece nas semanas 1-20: 99,2% dos households, e só 19
  entram depois). Desvio da decisão D, justificado pelo dado: blocos de 4 semanas, coortes com
  < 30 households omitidas e contadas. Resultado: 5 coortes, retenção estável (77-82% por bloco).
  Entrada no painel não é cliente novo.
- 2026-10-06 — 5a (visual, skill dataviz): gráficos em Altair, `src/ui/` (cores, gráficos,
  componentes, aba). Paleta de referência validada pelo porte Python do validador (`src/ui/cores.py`;
  reproduz os números da skill: CVD adjacente 9,1/8,4 e visão normal 19,6/19,3); não há Node na
  máquina. Emphasis (cinza + um destaque) em vez de várias cores; sequencial de um matiz no
  heatmap, invertido no modo escuro; título = conclusão; versão em tabela de cada gráfico. Aba
  abre com o bloco "e daí?". Nova view `vw_cliente_semana` (histórico por household e semana);
  `ETL_VERSAO` = "4".
- 2026-10-06 — 5b (correção da 5a, aprovada A e C): o grupo "Inativos" passa a se chamar **"Em pausa"** e a
  frase "já são perdas" saiu dos textos. Motivo: dos 246 households com 56 dias ou mais sem comprar no fim da
  janela base, 85% voltaram a comprar em 26 semanas e 97% em 52; dos 116 sem compra na janela base, 107 voltaram.
  A ação do grupo passou a ser "reativar".
- 2026-10-06 — 5b (CLV, aprovada B): método = margem x gasto médio das últimas 26 semanas x razão (gasto nas 52
  semanas seguintes / gasto nas 26 anteriores) do mesmo segmento um ano antes (coorte da janela base, mesmo K e
  mesmas regras de nome). Margem 25% e horizonte de 52 semanas são PREMISSAS (`analises.clv` no config; o
  horizonte precisa ser igual ao deslocamento do ano anterior). Households sem compra na janela formam o grupo
  "Sem compra na janela", estimado direto pelo gasto médio dos análogos do ano anterior; o total cobre os 2.500.
  IC de 95% por bootstrap de households (2.000 reamostras, semente 42) nas duas coortes. Resultado: CLV por
  household Fiéis US$ 820, Regulares US$ 326, Esporádicos US$ 135, Em pausa US$ 103, Sem compra US$ 99; total
  US$ 1,10 M de margem (US$ 4,41 M de receita) em 52 semanas.
- 2026-10-06 — 5b (backtest de 26 semanas): calibra em 24-49 -> 50-75, segmenta 50-75 e prevê 76-101. O método
  errou 2,9% no total (regra ingênua "repetir o último período": 4,0%) e ganhou nos 5 grupos; por household o erro
  absoluto médio é igual ao da regra ingênua (US$ 321 contra US$ 317): o CLV vale como média de grupo, não como
  previsão individual. O horizonte de 52 semanas não tem backtest (só uma transição observável).
- 2026-10-06 — 5b (RFM por janela): `rfm.base_rfm` calcula R, F e V de qualquer janela a partir de
  `vw_cliente_semana` (coluna nova `ultima_data`); um teste exige resultado idêntico a `vw_metricas_cliente` nas
  janelas atual e base. `rfm.ajustar_segmentos` é o ajuste único (K fixo, perfil, nomes). `ETL_VERSAO` = "5".
- 2026-10-06 — 5b (bug): o `cache.obter` travava (deadlock) quando uma análise chamava outra, porque o trava era
  um `Lock`; trocado por `RLock`, com teste de chamada aninhada. Lição: o `calcular_clv` chama o RFM por dentro.
- 2026-10-06 — 5b (visual): três gráficos novos (CLV com IC, ritmo de gasto com referência em 1, backtest método x
  ingênua). O Vega-Lite funde as escalas de camadas com campos diferentes e perde a ordem dos grupos: todas as
  camadas de um gráfico usam o mesmo campo no eixo. Rótulos de barras negativas ficam fora da ponta.
- 2026-10-06 — 5c (churn, aprovadas A-D): `prever_churn` mantém o nome da spec, mas o texto e a aba falam em **pausa longa
  (churn de 8 semanas)**: dos households que passam 8 semanas sem comprar, 72% a 85% (80% no total, 1.338 pausas) voltam em
  até 18 semanas. 8 semanas = 56 dias, o mesmo limite de "cliente ativo" e de "Em pausa". População: comprou nas últimas 8
  semanas e tem >= 16 semanas de histórico; os 297 households já em pausa ficam fora e são reportados à parte.
- 2026-10-06 — 5c (validação): fotos temporais como deslocamentos de `semana_fim_atual` (config `analises.churn`): treino
  T=30,34,...,66 (rótulos até a 74), validação T=77 (define o limiar por F1 máximo), teste T=85 e 93 (rótulos 86-93 e
  94-101, sem sobreposição). Regra simples "sem compra há k semanas" (k=4, escolhido no treino) sempre ao lado do modelo.
  Resultado no teste: AUC 0,853 contra 0,738, IC95% da diferença [0,089; 0,150] (bootstrap por household), AUC-PR 0,272
  contra 0,177 (prevalência 6,4%); limiar 0,17: precisão 0,29, recall 0,48. Calibração boa por decil (decil de maior risco:
  previsto 31,1%, observado 29,6%). A precisão por alerta é modesta (29%).
- 2026-10-06 — 5c (variáveis): 5 (recência em semanas, compras 8s, valor 26s, semanas com compra 26s, maior pausa 26s).
  Com as 10 testadas o VIF chegava a 24,6 e "compras 26s" ganhava sinal positivo (artefato de colinearidade); com 5 o
  AUC é igual (0,853), o VIF cai para 7,2 e os cinco sinais fazem sentido de negócio (constância é o maior protetor, OR
  0,49 por desvio-padrão). Tendência, % de desconto, ticket e tempo no painel não acrescentam AUC.
- 2026-10-06 — 5c (achado de negócio): o risco se concentra em quem gasta pouco: Fiéis 0,6%, Regulares 4,5%, Esporádicos
  22,9% (pausas esperadas 5, 44, 87). As pausas se concentram nos Esporádicos (64%), mas o faturamento em risco está nos
  Regulares (56% de US$ 12,7 mil em 8 semanas, 1,9% do período). O "e daí?" diz as duas coisas.
- 2026-10-06 — 5c (visual e lições): quatro gráficos (risco por segmento, precisão x recall por limiar, calibração,
  fatores em odds ratio). Rótulos dos eixos numéricos agora em formato brasileiro (`_eixo_pt`: o Vega usa o americano e
  o Streamlit não expõe o locale). Texto: nunca usar `.replace(",", ".")` em frase inteira para formatar milhar (troca
  também a vírgula decimal): formatar o milhar à parte. No painel sintético as 5 variáveis são quase colineares
  (correlação até 0,96), então só a dominante tem sinal garantido nos testes; os 5 sinais são testados na base real.
- 2026-10-06 — 5d (aprovadas A-C): hipótese escrita antes de rodar: os segmentos recebem desconto parecido. Kruskal-Wallis (Shapiro
  rejeita normalidade nos 4 grupos), post-hoc Mann-Whitney + Holm só se o geral for significativo, IC bootstrap das diferenças de
  mediana (2.000 reamostras, semente fixa, sem ajuste de Holm, dito na aba). As 3 funções estatísticas estão em
  `src/teste_hipotese.py`, cópia sem alteração da referência (um teste compara o código-fonte). Parâmetros em `analises.teste_desconto`.
- 2026-10-06 — 5d (veredito): significância não basta com ~2.400 households. Três vereditos: sem diferença detectável (p >= 0,05),
  diferença desprezível (significativa, mas eta² < 1% e nenhum par com >= 1 pp e IC fora de zero) e diferença relevante. Resultado:
  KW H = 11,68, p = 0,0085, eta² = 0,0036 (0,4% da variação) -> **desprezível**; maior diferença de mediana 1,25 pp (Regulares x
  Em pausa) com IC que inclui zero; só Esporádicos x Regulares passa no Holm (0,89 pp). Sensibilidade com >= 5 compras (2.138
  households): p = 0,52, eta² ~ 0 -> a significância vinha do ruído de medir desconto em poucas compras (Esporádicos e Em pausa têm
  desvio-padrão de 8 a 9 pp contra 4,9 nos Fiéis).
- 2026-10-06 — 5d (consistência com a 5a): o "desconto médio" por segmento da aba RFM passou a seguir a definição oficial (soma do
  desconto / soma do valor bruto; `carregar_base` e `base_rfm` trazem `desconto_total` e `valor_bruto`), em vez da média do % por
  household ponderada pelo líquido. Taxas ponderadas por segmento agora: Fiéis 15,5%, Regulares 16,2%, Esporádicos 16,7%, Em pausa
  16,2% (taxa geral 15,7%). Impacto: igualar todos à menor taxa cortaria US$ 5,6 mil (1,4%) dos US$ 400 mil de desconto, supondo
  demanda constante. Fora do escopo (D, não aprovado): separar desconto de loja e de cupom por segmento.
- 2026-10-06 — Fase 6 (aprovadas A-C): 6a servidor MCP em `src/mcp_server.py` (FastMCP, stdio, pacote `mcp` 1.30). Só embrulha as 6
  funções do núcleo (teste exige identidade das funções e ausência de duckdb/pandas/sklearn no módulo); descrição e parâmetros
  vêm do docstring e da assinatura. Banco por `ASSISTENTE_BANCO` e log por `ASSISTENTE_LOG`; stdout é só do protocolo. O resultado sai em JSON
  compacto (o FastMCP indentaria com 2 espaços e gastaria tokens do plano gratuito). Erros de guard-rail seguem sendo dados
  (`{erro, sugestao}`, `isError` falso). Pelo MCP, na base real: descrever 0,2 s / 21 KB, segmentar 8,3 s, CLV 1,0 s, churn 8,6 s,
  desconto 0,6 s (cada 5 a 9 KB). Atenção: `descrever_dados` devolve ~21 KB (~6 mil tokens), pesado para o limite de 12 mil tokens/min.
- 2026-10-06 — 6b (agente via MCP): `src/cliente_mcp.py` (`ServidorMCP`) abre um processo `src.mcp_server` por sessão do app, preso ao
  banco dela (`ASSISTENTE_BANCO`), e entrega ao agente as 6 ferramentas pelo `langchain-mcp-adapters` (`load_mcp_tools`), com uma
  entrada síncrona (a sessão stdio vive num laço asyncio numa thread de fundo, aberta e fechada pela mesma tarefa). O catálogo do
  prompt também vem do servidor (`descrever_dados` -> `compactar_catalogo`). O servidor abre na primeira pergunta, fecha ao
  recarregar a base e se encerra sozinho após 20 min sem uso (`agente.mcp_ocioso_minutos`: aba abandonada não acumula memória).
  Se não subir, o chat usa as funções do núcleo direto e a barra lateral avisa ("modo direto"). Subida: ~6 s com cache de disco
  quente (~30 s na primeira vez). Prompt: as 4 ferramentas de análise passam a ser chamadas pelo agente (antes dizia "veja as abas"),
  respondendo com conclusão, ação e a principal limitação do `e_dai`.
- 2026-10-06 — 6b (testes e memória): `tests/conftest.py` fecha os servidores abertos dentro de cada teste (cada AppTest com pergunta
  abre um processo de ~150-250 MB; sem isso a suíte esgota a RAM de 3,9 GB). Lição: o relógio de ociosidade começa quando o servidor
  fica pronto, não quando é criado (a subida leva mais que o limite dos testes).
- 2026-10-06 — 6c (formato das ferramentas, `tests/test_ferramentas_formato.py`, 39 testes): cada ferramenta confere os campos de saída da
  spec, o `e_dai` (4 blocos, sem placeholder), `versao_base` e `janela`, tamanho máximo (consulta 60 KB; análises 16 KB; descrever 30 KB),
  JSON válido, erro legível (`{erro, sugestao}`) para parâmetro inválido e para base ausente, uma linha de log por chamada (inclusive as
  com erro) e resultado repetível com o cache limpo. Achado e corrigido: `segmentar_clientes(n_clusters=1)` devolvia o erro sem
  `versao_base` nem `janela`; a spec pede os dois em todo retorno, agora vêm. Docstring de `executar_consulta` diz "views e dimensões".
- 2026-10-06 — 6d (avaliação completa, `eval/`): 34 perguntas em 3 arquivos (negócio 20, análise 8 `a01-a08`, maliciosas 6 `m01-m06`) + 40
  cargas de ataque (`ataques.yaml`). Perguntas de análise: o valor esperado vem da própria função (decisão A), lido por caminho
  (`segmentos[0].clv_medio`) e preso a uma faixa de sanidade; os testes recalculam alguns por SQL/pandas. Três modos: `oraculo` (28/28),
  `bloqueio` (sem LLM, tudo pelo servidor MCP: 46 cargas recusadas ou limitadas = 100%, 0 de 4 consultas legítimas bloqueadas por engano,
  tabelas com as mesmas linhas antes e depois) e `vivo` (agente via MCP; maliciosa vale pelo resultado: nada perigoso executou com
  sucesso, nada de `gsk_`/`GROQ_API_KEY=` na resposta, nada passou do limite; m05 exige dizer que não existe vendedor). Sem `GROQ_API_KEY`
  o modo vivo continua pendente: não há taxa de acerto do modelo, só do oráculo e do bloqueio. Spec corrigida (aprovada, item B): tabelas
  visíveis, `limite_aplicado`/`aviso`/`janela` e regra combinada de K.
- 2026-10-06 — 6e (descrever_dados enxuto, aprovado pelo usuário): `descrever_dados(detalhe=None)`. Sem argumento devolve a lista curta (views e
  tabelas com descrição de uma frase, métricas só com nome e view de origem, janela, limitações): 6,7 KB contra 20,9 KB (~2 mil tokens
  contra ~6 mil). `detalhe="vw_x"` ou tabela traz as colunas com tipo e as métricas da view (~3 KB); `detalhe="ticket_medio"` traz
  definição e fórmula; `detalhe="tudo"` é o catálogo completo, que o app usa uma vez para montar o prompt (o agente lê o catálogo pelo
  servidor MCP). `detalhe` desconhecido ou de tabela interna vira `{erro, sugestao}` com as opções permitidas; o texto nunca vira SQL.
- 2026-10-06 — 6e (skills e spec): os 3 `SKILL.md` foram reescritos a partir do que foi decidido (regra combinada de K, "Em pausa", CLV com
  margem como premissa, churn = pausa de 8 semanas, veredito do teste de desconto, bloqueios do código, modos da avaliação) e ganharam a
  tabela "qual ferramenta usar". `tests/test_skills_e_spec.py` (24 testes, sem banco): a spec lista exatamente as 6 ferramentas do servidor,
  o docstring de cada uma começa pela descrição da spec (achou drift: "correção de Holm"), toda ferramenta aparece nas skills e no prompt,
  números das skills batem com o `config.yaml` e frases já substituídas não voltam. Spec: `descrever_dados` atualizada (entrada, saída
  curta, custo em tokens).
- 2026-10-07 — Fase 7 (notebook narrado, aprovadas A-D): `notebooks/analise_clientes_dunnhumby.ipynb` (60 células, 3,8 MB, com as saídas salvas para ler
  no GitHub sem rodar). Fonte editável em `notebooks/fonte/conteudo_a.py` e `conteudo_b.py`; `notebooks/construir_notebook.py` monta, executa com
  `nbclient` e salva. O notebook **não recalcula nada**: chama as mesmas funções do núcleo e as mesmas views; os números dos textos de resultado
  são preenchidos por código (f-strings), o texto fixo só explica método e escolhas. Seções: 0 resumo, 1 dados e qualidade, 2 métricas (conferência
  por segundo caminho direto na tabela de fatos: diferença 0,0000), 3 RFM, 4 CLV, 5 risco de pausa (com VIF das 5 variáveis calculado no próprio
  notebook, maior 7,2, e o p95/p99 do intervalo entre compras para justificar as 8 semanas), 6 teste de desconto, 7 costura (tabela que junta as 4
  análises por segmento, ações e o que não dá para afirmar), 8 reprodutibilidade (sobe o servidor MCP e confirma que as 4 análises dão exatamente os
  mesmos números pelo servidor e no notebook). Cada análise abre com "Decisão que esta seção apoia" e fecha com o bloco "e daí?" (texto da própria
  ferramenta). Nenhum texto afirma "hipótese escrita antes" onde não foi (só no teste de desconto e na regra de K).
- 2026-10-07 — Fase 7 (gráficos e pacotes): os gráficos são os de `src/ui/graficos.py` (nenhum Altair reescrito), mostrados por `src/notebook_apoio.py` em
  formato duplo: PNG (o GitHub e o HTML não executam Vega) + especificação Vega-Lite (interativa no Jupyter). Exige `vl-convert-python` (travado no
  `requirements.txt`, junto com `nbclient`, `ipykernel`, `nbconvert`). O notebook lê o banco local (`data/processed/dunnhumby.duckdb`, fora do Git):
  quem clonar roda o ETL antes; o arquivo salvo já tem as saídas. `tests/test_notebook.py` (11): estrutura, saídas sem erro, arquivo salvo confere com as
  ferramentas de hoje (avisa se ficar velho) e execução do zero reproduz exatamente os mesmos textos e números.
- 2026-10-07 — Fase 7 (bug do cliente MCP): dentro do Jupyter o `ServidorMCP` não subia porque `sys.stderr` do kernel não tem descritor de arquivo; o
  erro do subprocesso agora vai para `os.devnull` (`errlog`). Isso também tira o log do servidor do console do app.
- 2026-10-07 — Fase 8 (aprovadas A-F; C = sem prints de interface, só os gráficos do notebook; D = rodar o modo vivo antes de publicar):
  (A) pacote de dados em Parquet com o **histórico inteiro**, não o recorte de duas janelas do guia (`data/processed/parquet/`, 18,3 MB, versionado):
  o risco de pausa usa o histórico desde a semana 5, o CLV calibra um ano antes e a coorte usa a primeira compra, então só as duas janelas mudaria
  os números. `src/pacote.py` (`exportar`, `verificar`, `carregar_pacote`); `carga.carregar` ganhou a terceira origem (upload > CSV nas pastas > pacote).
  O manifesto guarda o MD5 dos CSV de origem: a `versao_base` do banco do pacote é a mesma do ETL enquanto parâmetros e `ETL_VERSAO` não mudarem
  (`etl.versao_de_md5s`); se mudarem, o pacote fica velho e a carga recusa com a instrução de regerar. Teste: o banco do pacote é igual ao do ETL em
  tabelas, views e nas 4 análises, campo a campo. Medido: carga do pacote 11,7 s, banco de 44 MB, 117 MB de RAM.
- 2026-10-07 — Fase 8 (dependências e nuvem, aprovada B; Python 3.13 no deploy): `requirements.txt` agora é só o do app e do servidor MCP (89 pacotes,
  fecho das dependências diretas, `pywin32` só com marcador de Windows); `requirements-dev.txt` traz o resto (`-r requirements.txt`). Ambos gerados por
  `gerar_requirements.py`. Verificado sem acesso à nuvem: os 87 pacotes de Linux têm wheel em cp313 e cp312 (`pip download --platform manylinux`),
  sem conflito nem dependência faltando sob os marcadores de Linux; o código parseia com a gramática 3.12. Teste: tudo o que `app/` e `src/` importam
  está no requirements do app. Sessão fria simulada (cópia sem `data/raw` nem banco): abertura 49 s (carga + 4 análises), app 344 MB (pico 631 MB no
  Windows), primeira pergunta 12,7 s, servidor MCP +238 MB (total ~600 MB). Cabem poucas sessões de chat no plano de ~1 GB.
- 2026-10-07 — Fase 8 (servidor MCP logo depois do clone): sem `ASSISTENTE_BANCO` e sem o banco do ETL, `mcp_server.garantir_banco` constrói o banco do pacote
  (~12 s na primeira vez). `ServidorMCP` e o servidor não importam duckdb diretamente.
- 2026-10-07 — Fase 8 (README, aprovada E): `README.md` com as 15 seções do guia; oito blocos entre `<!-- gerado:NOME -->` são reescritos por
  `python -m src.documentacao` (qualidade, métricas de `views.METRICAS`, resumos de `eval/ULTIMO_*.md`, estrutura de pastas e o "e daí?" das 4 análises, que vem
  das ferramentas). `tests/test_readme.py` (13): seções, links e imagens, blocos em dia com as ferramentas de hoje, nada de "versão anterior" ou saída de emprego
  (regra 8) no README, app, src e notebook, e números fixos do texto batem com o `config.yaml`. Os PNG do README são os do notebook (`notebooks/imagens/`,
  extraídos por `construir_notebook.py`). Sem taxa de acerto do modelo no README enquanto `eval/ULTIMO_VIVO.md` não existir ("ainda não medido").
  O endereço do app publicado fica como lembrete no topo até a publicação. Termos de uso do dataset: conferência do usuário (seção 15 do README).
