# Spec — Ferramentas do servidor MCP

> Fonte única das regras de cada ferramenta. As skills (lado Claude) e o prompt do sistema do agente Groq (lado app) são escritos **a partir deste documento**. Se uma regra mudar, muda aqui primeiro.

---

## 1. Arquitetura

```
Planilha (upload) ou data/  →  ETL + relatório de qualidade  →  DuckDB (Star Schema + views de métricas)
                                                                      │
                                                         Funções Python do núcleo (src/)
                                                                      │
                                                         Servidor MCP (src/mcp_server.py)
                                                          │                         │
                                     App Streamlit (agente Groq via          Claude Desktop / Claude Code
                                     langchain-mcp-adapters, público)        (uso direto, com as skills)
```

- **Ordem de construção:** primeiro as funções Python do núcleo, testadas sem MCP. O servidor MCP só embrulha essas funções, sem lógica própria. Se o MCP der problema, o núcleo continua funcionando.
- **App publicado:** Streamlit + Groq (gratuito), chave via `st.secrets`. A criação do modelo fica isolada em `criar_agente()`, para a troca de modelo ser em um lugar só.
- **Lado Claude:** mesmo servidor MCP, usado com as skills em `.claude/skills/`.
- O glossário RAG continua sendo injetado na pergunta antes de chegar ao agente Groq.

## 2. Regras globais (valem para todas as ferramentas)

| Regra | Como é garantida | Teste |
|---|---|---|
| Conexão com o banco só leitura | `duckdb.connect(..., read_only=True)` | Tentar escrever falha |
| Só consultas de leitura | Validação no código antes de executar (ver `executar_consulta`) | DELETE, DROP, UPDATE, INSERT, CREATE, ALTER, ATTACH, COPY, PRAGMA são bloqueados; SELECT e WITH passam |
| Uma instrução por chamada | Rejeitar SQL com mais de uma instrução (`;` fora de string) | `SELECT 1; DROP TABLE x` é bloqueado |
| Limite de linhas | Padrão 20, máximo 200, aplicado no código | Retorno nunca passa do limite |
| Tempo máximo | Timeout por consulta (ex: 30 s) | Consulta longa retorna erro claro |
| Métricas vêm das views | Ferramentas de análise leem só das views `vw_*` | Teste compara número da ferramenta com a view |
| Retorno enxuto | Resumos e tabelas agregadas, nunca a base inteira | Tamanho do retorno abaixo do limite configurado |
| Erro legível | Toda falha devolve `{"erro": "...", "sugestao": "..."}`, sem stack trace | Erros esperados retornam esse formato |
| Log de toda chamada | ferramenta, parâmetros, tempo, nº de linhas, tamanho do retorno, erro (se houver) | Cada chamada gera uma linha em `logs/` |
| Rastreabilidade | Todo retorno inclui `versao_base` (hash da carga) e `janela` (semanas usadas) | Campos presentes em todo retorno |

**Guard-rail não depende de texto.** As skills e o prompt explicam as regras, mas quem impõe é o código. Toda regra da tabela acima tem um teste em `tests/`.

## 3. Ferramentas

As descrições abaixo viram as docstrings. A IA escolhe a ferramenta pela descrição, então ela precisa dizer **quando usar** e **quando não usar**.

### 3.1 `descrever_dados(detalhe: str | None = None)`
- **Descrição:** "Mostra as tabelas e views disponíveis, as métricas, a janela de análise, a base de comparação do ano anterior e as limitações da base. Use antes de escrever uma consulta ou quando não souber qual coluna ou métrica usar. Sem argumento devolve a lista curta; passe em `detalhe` o nome de uma view, tabela ou métrica para ver as colunas (com tipo) ou a definição e a fórmula."
- **Entrada:** `detalhe` (opcional): nome de uma view, tabela ou métrica. `"tudo"` devolve o catálogo completo (uso do app para montar o prompt).
- **Saída sem argumento (lista curta, ~7 KB):** `views` e `tabelas` (nome, descrição de uma frase), `metricas` (nome, view de origem), `janela_atual`, `janela_ano_anterior`, `limitacoes`, `versao_base`, `janela`. Com `detalhe` de view ou tabela: colunas com tipo e as métricas daquela view; de métrica: definição de negócio, fórmula e view de origem. Com `"tudo"` (~21 KB): views com colunas e todas as métricas com definição e fórmula.
- **Por que curta por padrão:** o catálogo completo custa cerca de 6 mil tokens, metade do limite por minuto do plano gratuito; a lista curta custa cerca de 2 mil e o detalhe de uma view, menos de 1 mil.
- **Nunca:** devolver linhas de dados, nem descrever tabelas fora da lista permitida (`detalhe` desconhecido vira `{erro, sugestao}` com as opções).

### 3.2 `executar_consulta(sql: str, limite: int = 20)`
- **Descrição:** "Executa uma consulta SQL de leitura nas views e dimensões do projeto e devolve o resultado. Use para perguntas pontuais (vendas de uma loja, ticket médio, comparação com o ano anterior). Não use para segmentação, CLV, churn ou testes estatísticos: para isso existem ferramentas próprias."
- **Entrada:** `sql` (uma instrução SELECT ou WITH); `limite` (1 a 200).
- **Saída:** `colunas`, `linhas` (até o limite), `total_linhas`, `truncado` (bool), `limite_aplicado`, `sql_executado`, `versao_base`, `janela`; `aviso` quando o retorno é reduzido pelo limite de tamanho; `aviso_periodo` quando a consulta usa uma fonte de histórico (`vw_vendas_item`, `vw_metricas_*`, `coupon_redempt`, `campaign_*` etc.) sem filtrar período (heurística sobre o texto do SQL): o resultado cobre todo o histórico, e a resposta deve dizer isso. `janela` é a referência do projeto, não o filtro da consulta.
- **Tabelas visíveis:** `vw_*`, `dim_*`, `fato_transacoes`, `campaign_*`, `coupon*`, `causal_semana_loja` e `metricas_definicao`. Ficam de fora `raw_*`, `fato_ajustes`, `log_cargas`, `meta` e `_mat_*` (allowlist no código).
- **Nunca:** executar escrita, mais de uma instrução, ou retornar mais que o limite.
- **Pronto quando:** passa nos testes de guard-rail e acerta as perguntas de consulta do conjunto de avaliação.

### 3.3 `segmentar_clientes(n_clusters: int | None = None)`
- **Descrição:** "Segmenta os households por RFM com K-Means e devolve o perfil, o tamanho e a parcela do faturamento (pct_faturamento) de cada segmento. Use para 'quem são os clientes', 'quais segmentos existem', 'que parcela do faturamento vem de cada grupo' ou antes de comparar segmentos. Se n_clusters não for informado, o K é escolhido pela regra combinada (silhueta, estabilidade e tamanho dos segmentos)."
- **Saída:** `k_usado`, `metodo_escolha_k`, `silhueta`, `segmentos` (nome, nº de households, R/F/V médios, % do faturamento), `estabilidade` (concordância entre sementes), `excluidos` (quantos e por quê), `e_dai`, `versao_base`.
- **Regras:** nomes dos segmentos vêm do perfil real; nenhum segmento sem nome; semente fixa; resultado cacheado por `versao_base`.
- **Nunca:** devolver a lista completa de households.

### 3.4 `calcular_clv(segmento: str | None = None)`
- **Descrição:** "Estima o valor do cliente (CLV) por segmento RFM, com intervalo de confiança. Use para 'quanto vale cada grupo de clientes', 'margem esperada', 'valor esperado de um cliente' ou 'quanto vale um cliente'. Chame sem argumentos, com as premissas do projeto (margem de 25% e horizonte de 52 semanas), e declare-as na resposta; não peça a fórmula da margem ao usuário."
- **Saída:** por segmento: `clv_medio`, `ic_95`, `n`, `premissas` (horizonte, margem assumida, método); `e_dai`; `versao_base`.
- **Regras:** premissas sempre explícitas no retorno; IC via bootstrap.

### 3.5 `prever_churn(segmento: str | None = None)`
- **Descrição:** "Mostra o risco de churn por segmento e o desempenho do modelo contra uma regra simples. Use para 'quem vai parar de comprar' ou 'qual segmento está em risco'."
- **Saída:** `definicao_churn`, `periodo_treino`, `periodo_teste`, `auc_modelo`, `auc_baseline`, `precisao_recall_classe_churn`, `matriz_confusao`, `principais_fatores` (coeficientes com sinal e interpretação), `risco_por_segmento`, `e_dai`, `versao_base`.
- **Regras:** split temporal; baseline sempre reportado; se o modelo não ganhar do baseline, o `e_dai` diz isso.

### 3.6 `testar_desconto_entre_segmentos()`
- **Descrição:** "Testa se o percentual de desconto difere entre os segmentos RFM (Kruskal-Wallis e comparações par a par com correção de Holm). Use para 'os segmentos recebem desconto diferente?'. Mostra diferença entre grupos, não efeito causal do desconto."
- **Saída:** `normalidade_por_grupo`, `kruskal_wallis` (H, p-valor, eta²), `post_hoc` (pares, medianas, p ajustado), `ic_diferencas` (bootstrap), `e_dai`, `versao_base`.
- **Regras:** post-hoc só roda se o teste geral for significativo; `e_dai.limitacoes` sempre deixa claro que não é efeito causal.

### Formato do bloco `e_dai` (ferramentas de análise)
```json
{"conclusao": "...", "evidencia": "...", "acao_recomendada": "...", "impacto_estimado": "...", "limitacoes": "...", "detalhes_tecnicos": ["...", "..."]}
```
- `conclusao`: uma frase curta (até ~15 palavras), em linguagem de negócio, sem estatística. É o título do bloco no app e a primeira frase da resposta do chat.
- `evidencia`: 1 ou 2 frases com os números de negócio que sustentam a conclusão (e o aviso, quando o modelo não supera a regra simples).
- `acao_recomendada`, `impacto_estimado`, `limitacoes`: como antes.
- `detalhes_tecnicos`: lista de frases com a estatística (AUC, p-valor, eta², IC, limiar, precisão/recall, robustez). O app mostra num expander fechado; nada da estatística some, só sai do título.

## 4. Avaliação

- **Conjunto de perguntas** (`eval/perguntas.yaml`): 15 a 20 perguntas de negócio, cada uma com a ferramenta esperada e a resposta esperada (calculada com SQL escrito à mão), mais 5 perguntas maliciosas (pedir para apagar tabela, injetar comando no texto da pergunta, pedir a base inteira).
- **Script** (`eval/rodar_avaliacao.py`) reporta:
  - taxa de acerto (número dentro da tolerância);
  - taxa de escolha da ferramenta certa;
  - tokens e tempo médios por pergunta;
  - taxa de bloqueio nas perguntas maliciosas (meta: 100%).
- Rodar sempre que mudar prompt, glossário, views, descrições das ferramentas ou skills.

## 5. Critério de "pronto" do servidor MCP

- [ ] Todas as funções do núcleo testadas sem MCP
- [ ] Testes de guard-rail passando (`pytest`)
- [ ] Cada ferramenta devolve o formato desta spec (teste de formato)
- [ ] Nenhum retorno passa do limite de linhas ou de tamanho
- [ ] Log gerado para toda chamada
- [ ] Avaliação rodada e números registrados no README
- [ ] App Streamlit e Claude Desktop/Code usando o mesmo servidor
