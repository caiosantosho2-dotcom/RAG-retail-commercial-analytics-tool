# Assistente Comercial + Análise de Clientes (Dunnhumby)

Este arquivo é lido no início de toda sessão. O briefing completo está em
`docs/guia_projeto_dunnhumby.md` (fonte da verdade) e o modo de trabalho em
`docs/guia_boas_praticas_analise_senior.md`. Em caso de dúvida, consulte o guia
antes de decidir.

## Visão geral

Ferramenta para a área comercial de varejo. O usuário exporta uma planilha do
BI, arrasta para o app e:
- pergunta em linguagem de negócio num **chat** que responde consultando os
  dados via SQL (produto principal, primeira aba);
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

1. O chat é a primeira aba: glossário RAG injetado no prompt, SQL visível num
   expander, contador de tokens na sidebar.
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
venv\Scripts\python.exe -m pip install -r requirements.txt   # instalar
set KAGGLE_API_TOKEN=...  (ou ~/.kaggle/kaggle.json)         # credencial, nunca no código
venv\Scripts\python.exe baixar_dados.py                       # baixa data/raw/
venv\Scripts\python.exe -m src.auditoria                      # relatorios/auditoria_fase1.md
```

(ETL, app, avaliação do chatbot e testes: preencher nas fases 2 a 6.)

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
