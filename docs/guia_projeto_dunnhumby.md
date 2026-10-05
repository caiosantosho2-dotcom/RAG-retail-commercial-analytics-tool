# Guia do Projeto — Assistente Comercial + Análise de Clientes (Dunnhumby Complete Journey)

> Este documento é o briefing completo do projeto. Leia inteiro antes de gerar qualquer código.

---

## 1. Contexto e objetivo

Este é um projeto de **portfólio** de um profissional em transição de Analista Comercial/Negócios para **Cientista/Analista de Dados**, com experiência em indústria de bens de consumo (P&G) e em varejo de moda de luxo. A ideia nasceu de uma dor real do dia a dia do escritório de varejo e foi validada numa versão interna anterior. Esta versão usa um **dataset público**, para que o resultado seja 100% reproduzível e verificável por qualquer pessoa.

> ⚠️ O README e os textos do app **não devem** mencionar saída de emprego, versão anterior ou "não consegui aplicar". O foco é o problema de negócio que a ferramenta resolve.

**O problema de negócio:** no varejo, o banco de dados que alimenta o BI costuma ser controlado pelo time de dados. As áreas de negócio (comercial, e-commerce, gerência) não têm permissão de mexer nele, por segurança e para manter a base íntegra. O dia a dia dessas áreas é exportar planilhas do BI e cruzar dados à mão, ou pedir uma análise e esperar até o dia seguinte.

**A solução:** o usuário exporta a planilha do BI como já faz, arrasta para dentro do app e pergunta em linguagem de negócio. A carga por arquivo **não é uma limitação técnica, é uma escolha de produto**: funciona sem acesso ao banco, sem depender do time de dados e sem exigir que o usuário saiba SQL ou programação.

**O que o produto é:** uma ferramenta de uso diário para a área comercial. O coração dela é um **chatbot em linguagem natural do negócio**: o usuário (gerente, analista comercial) pergunta do jeito que fala no dia a dia e recebe a resposta calculada a partir do banco, sem saber SQL. Um glossário de negócio (RAG) traduz o vocabulário do usuário para as colunas corretas. Além do chat, o app oferece abas de análise estatística (segmentação, CLV, churn, teste de hipótese).

**Quem usa e para quê (dois públicos, duas ferramentas paralelas):**
- **Chatbot → consultas pontuais do dia a dia.** Comercial, e-commerce, gerência e diretoria perguntam coisas que antes viravam um pedido ao BI e voltavam no dia seguinte (cruzar bases, fazer contas simples). A intenção original era expandir até para as gerentes das lojas.
- **Abas de análise estatística → decisão.** Voltadas à gerência e diretoria: a base já "mastigada" (quem são os clientes, quanto valem, quem vai sair, por quê), para decidir sem precisar encomendar um estudo.

A interface e os textos do app devem refletir isso: o chat precisa ser simples o bastante para alguém que não é de dados; as abas de análise precisam trazer a conclusão de negócio em destaque, com o detalhe estatístico logo abaixo.

**Objetivo de posicionamento:** o projeto deve puxar atenção de recrutadores de **Ciência de Dados e Análise de Dados**. Isso não diminui o chatbot — ele é o que torna o projeto um produto útil, não um exercício. O que deve ser evitado é sofisticação de infraestrutura sem ganho para o usuário ou para a análise (ex: orquestração complexa, múltiplos agentes). Chatbot funcional + análises rigorosas é o equilíbrio certo.

---

## 2. Dataset: Dunnhumby "The Complete Journey"

Dataset real de varejo (rede de supermercados dos EUA), disponível publicamente (Kaggle: `frtgnn/dunnhumby-the-complete-journey`, também redistribuído no pacote R/Python `completejourney`). Contém ~2 anos de transações de 2.500 households (famílias/clientes) em ~500 lojas.

### Tabelas e colunas-chave

| Tabela | Conteúdo | Colunas principais |
|---|---|---|
| `transaction_data` | Uma linha por item comprado | `household_key`, `BASKET_ID`, `DAY`, `PRODUCT_ID`, `QUANTITY`, `SALES_VALUE`, `STORE_ID`, `RETAIL_DISC`, `COUPON_DISC`, `COUPON_MATCH_DISC`, `WEEK_NO`, `TRANS_TIME` |
| `product` | Catálogo de produtos | `PRODUCT_ID`, `DEPARTMENT`, `COMMODITY_DESC`, `SUB_COMMODITY_DESC`, `MANUFACTURER`, `BRAND`, `CURR_SIZE_OF_PRODUCT` |
| `hh_demographic` | Demografia (só parte dos households tem) | `household_key`, `AGE_DESC`, `MARITAL_STATUS_CODE`, `INCOME_DESC`, `HOMEOWNER_DESC`, `HOUSEHOLD_SIZE_DESC`, `KID_CATEGORY_DESC` |
| `campaign_table` | Quais campanhas cada household recebeu | `household_key`, `CAMPAIGN`, `DESCRIPTION` |
| `campaign_desc` | Datas de cada campanha | `CAMPAIGN`, `DESCRIPTION`, `START_DAY`, `END_DAY` |
| `coupon` | Cupons de cada campanha | `COUPON_UPC`, `PRODUCT_ID`, `CAMPAIGN` |
| `coupon_redempt` | Resgates de cupom | `household_key`, `DAY`, `COUPON_UPC`, `CAMPAIGN` |
| `causal_data` | Se o produto estava em display/mailer numa semana/loja | `PRODUCT_ID`, `STORE_ID`, `WEEK_NO`, `display`, `mailer` |

### Pontos de atenção ao carregar os dados
- `SALES_VALUE` já é o valor recebido pelo varejista **depois** de cupom e desconto de fidelidade — não é o preço de tabela. Faturamento líquido real = `SALES_VALUE` (não precisa subtrair `RETAIL_DISC`/`COUPON_DISC` de novo; esses campos existem para você DECOMPOR o desconto, não para recalcular o líquido).
- `DAY` é um inteiro relativo (dia 1 a ~711), não uma data de calendário — vai precisar converter para uma data real (`data_referencia = data_base + DAY dias`, escolhendo uma data-base arbitrária, ex: 2016-01-01) antes de qualquer análise de recência/cohort.
- `household_key` é o identificador de cliente estável ao longo de todo o dataset (ao contrário do Olist, aqui não existe a armadilha de ID que muda por pedido).
- Nem todo household tem linha em `hh_demographic` — não faça INNER JOIN com essa tabela como padrão (perderia households), trate demografia como enriquecimento opcional.

### Recorte temporal e base de comparação
- **Janela de análise:** as últimas ~26 semanas de `WEEK_NO` (não o calendário real). Justificar no artigo como "simulação de janela de análise recente", já que o dataset é histórico (2016-2018).
- **Base de comparação (ano anterior):** as mesmas 26 semanas do ano anterior (`WEEK_NO - 52`). Comparação ano contra ano é essencial no varejo: número sem base não mostra se houve crescimento, queda ou efeito de ação.
- **Alinhar por semana, não por data**, para manter a mesma mistura de dias da semana. Sinalizar feriados que mudam de data entre os anos.
- **Like-for-like:** comparar só lojas (e, quando fizer sentido, households) presentes nos dois períodos. Reportar quantas lojas ficaram de fora e por quê.
- **Explicar a base:** usar `campaign_desc`, `coupon_redempt` e `causal_data` (display/mailer) para identificar se a base do ano anterior estava inflada ou deprimida por alguma ação. A variação ano contra ano sempre vem acompanhada dessa explicação.
- Conferir antes se o período de base está completo (as primeiras semanas do dataset podem ter volume menor por entrada de households no painel).
- O recorte salvo no repositório (Parquet em `data/`) precisa cobrir **as duas janelas** (atual + ano anterior), não só os últimos 6 meses.

---

## 3. Mapeamento conceitual: One Up → Dunnhumby

| Conceito na One Up | Equivalente aqui | Observação |
|---|---|---|
| Cliente | `household_key` | Estável, sem armadilha de ID |
| Loja/filial (`equipe_id`) | `STORE_ID` | ~500 lojas |
| Vendedora/funcionário (`funcionario_id`) | **Não existe** | Checkout de supermercado, sem atendimento individual — remover essa dimensão do projeto |
| Produto/SKU | `PRODUCT_ID` | Sem conceito de "coleção" — usar `DEPARTMENT`/`COMMODITY_DESC` como substituto de categoria |
| Desconto | `RETAIL_DISC` + `COUPON_DISC` + `COUPON_MATCH_DISC` | Existe de verdade — o teste de hipótese pode voltar a ser sobre desconto, como na One Up original |
| Faturamento líquido | `SALES_VALUE` | Já é líquido, não precisa recalcular |
| Cupom/campanha | `campaign_table`, `coupon`, `coupon_redempt` | Dimensão nova, não existia na One Up — pode virar enriquecimento da análise de desconto |

---

## 4. Modelagem: Star Schema a construir

Seguir o mesmo padrão usado na One Up (DuckDB, tabelas `fato_*`/`dim_*`), adaptado:

- **`dim_household`**: `household_key` + campos de `hh_demographic` (LEFT JOIN, nem todos têm)
- **`dim_produto`**: `PRODUCT_ID`, `DEPARTMENT`, `COMMODITY_DESC`, `SUB_COMMODITY_DESC`, `MANUFACTURER`, `BRAND`
- **`dim_loja`**: `STORE_ID` (distinct de `transaction_data`)
- **`dim_data`**: calendário derivado de `DAY` (data real, dia da semana, semana, mês)
- **`fato_transacoes`**: uma linha por item de cesta — `household_key`, `BASKET_ID`, `data_id`, `STORE_ID`, `PRODUCT_ID`, `QUANTITY`, `SALES_VALUE`, `RETAIL_DISC`, `COUPON_DISC`, `COUPON_MATCH_DISC`

---

## 5. O chatbot (componente central do app)

### Como funciona
1. Usuário carrega os dados (ver "Carga de dados" abaixo)
2. ETL monta o Star Schema no DuckDB
3. Usuário pergunta em linguagem natural no chat
4. Antes de ir ao LLM, a pergunta passa pelo glossário RAG, que injeta no prompt as definições de negócio relevantes (injeção direta no input, não como tool do agente — é determinístico e economiza tokens)
5. O agente (LangChain + Groq) escolhe uma ferramenta do servidor MCP: `executar_consulta` para perguntas pontuais em SQL, ou as ferramentas de análise (segmentação, CLV, churn, teste de desconto). Responde em linguagem natural
6. Contador de tokens na sidebar mostra o consumo por resposta e por sessão

### Arquitetura com MCP (detalhes em `docs/spec_ferramentas_mcp.md`)
- As funções do núcleo (consulta, segmentação, CLV, churn, teste de desconto) são construídas e testadas primeiro, como Python comum. O servidor MCP só embrulha essas funções, sem lógica própria.
- O **mesmo servidor MCP** atende dois clientes:
  - **App Streamlit publicado:** agente Groq (gratuito), carregando as ferramentas via `langchain-mcp-adapters`. Groq porque o app é público e um modelo pago cobraria cada pergunta de cada visitante. A criação do modelo fica isolada em `criar_agente()`, para a troca ser em um lugar só.
  - **Claude Desktop / Claude Code:** uso direto como analista, com as skills em `.claude/skills/`.
- **A spec é a fonte única das regras.** As skills (lado Claude) e o prompt do sistema do Groq (lado app) são escritos a partir dela.
- **Guard-rails ficam no código**, com testes: conexão só leitura, só SELECT/WITH, uma instrução por consulta, limite de linhas, timeout. Texto em skill ou prompt explica a regra, mas não garante.
- Toda chamada de ferramenta gera log (ferramenta, parâmetros, tempo, linhas, tamanho do retorno, erro).

### Exemplos de perguntas que o chat deve responder bem
Adaptadas ao Dunnhumby (não existe vendedor individual neste dataset — a loja é a menor unidade de equipe):
- "Quanto a loja 367 vendeu de laticínios no último mês?"
- "Qual loja teve o maior ticket médio nas últimas 4 semanas?"
- "Quantos clientes compraram na loja 367 no último mês?"
- "Qual departamento teve mais desconto de cupom?"
- "Quais os 5 produtos mais vendidos da categoria X?"

Crie um conjunto de ~15 perguntas como essas para usar como teste de qualidade do chatbot (pergunta + qual regra/coluna a query correta deve usar).

Incluir no teste perguntas no estilo de gerente de categoria de indústria de bens de consumo (P&G, Unilever), que é a bagagem do autor:
- "A venda da loja 367 caiu contra o ano passado por menos clientes, menos idas à loja ou menos gasto por ida?" (árvore de vendas)
- "Quanto a marca própria cresceu em laticínios contra o mesmo período do ano passado?" (`BRAND` = Private vs National)
- "Qual a penetração da categoria X nos households no último trimestre?" (households que compraram / households ativos)
- "Quais produtos são mais comprados pelos clientes de alta frequência?"
- "Qual departamento concentra 80% do faturamento?" (curva ABC)
- "Quantos households resgataram cupom da campanha X e quanto gastaram?"

### Regras de negócio que o prompt do agente precisa conter (reescrever do zero para este dataset)
- Faturamento = `SALES_VALUE` (já líquido)
- Ticket médio = faturamento / COUNT(DISTINCT `BASKET_ID`)
- Itens por cesta = SUM(`QUANTITY`) / COUNT(DISTINCT `BASKET_ID`)
- Desconto total = `RETAIL_DISC` + `COUPON_DISC` + `COUPON_MATCH_DISC` (verificar o sinal desses campos no dado real antes de somar — podem vir negativos)
- "Loja", "unidade", "filial" → `STORE_ID`
- "Categoria", "seção" → `DEPARTMENT` / `COMMODITY_DESC`, sempre com ILIKE para tolerar variação de escrita
- "Último mês" → relativo à data máxima da base, não à data de hoje
- Listagens de registros individuais: sempre LIMIT 20 (controle de tokens)
- Nunca responder só com SQL; sempre executar e responder em texto

### Carga de dados — os dois caminhos
- **Arrastar/subir arquivo** numa janela do Streamlit (jeito preferido do usuário no dia a dia). Aceitar CSV e Excel, que é o formato que sai do BI
- **Ler direto de uma pasta padrão** (`data/`) — se a pasta tiver os arquivos, o app carrega sozinho ao abrir, sem precisar de upload
- Se os dois existirem, o upload tem prioridade sobre a pasta
- A tela de carga precisa ser óbvia para quem não é de dados: instrução curta, mensagem clara se faltar coluna ou o arquivo vier no formato errado, e um resumo do que foi carregado (período, linhas, lojas, households)
- Não conectar direto em banco de produção: a carga por arquivo é a proposta do produto (ver seção 1)

### Publicação (para outra pessoa conseguir usar a partir do GitHub)
- Deploy no **Streamlit Community Cloud** apontando para o repositório
- O dataset completo é grande demais para versionar no GitHub (limite de 100 MB por arquivo). Solução: salvar no repositório um recorte em **Parquet** com as duas janelas (últimos 6 meses + mesmas semanas do ano anterior) dentro de `data/`, e incluir um script `baixar_dados.py` para quem quiser a base completa
- A chave da API do Groq entra por `st.secrets` no deploy (nunca no código) ou pelo campo na sidebar

---

## 6. Escopo analítico travado (não abrir de novo sem justificativa forte)

### As 4 análises núcleo — formam uma narrativa única, nesta ordem
1. **RFM + K-Means** (validar K por método do cotovelo ou silhueta, não escolher no chute) → "quem são os clientes"
2. **CLV (Customer Lifetime Value)**, consumindo os segmentos do RFM → "quanto cada grupo vale"
3. **Modelo preditivo de recompra/churn** (regressão logística, interpretável, com split treino/teste, matriz de confusão, AUC) → "o que vai acontecer com cada grupo"
4. **Teste de hipótese**: desconto (`RETAIL_DISC + COUPON_DISC`, como % do valor bruto) difere entre os 4 segmentos RFM? Kruskal-Wallis (todos os grupos) + post-hoc Mann-Whitney com correção de Holm se significativo → "por que os grupos se comportam diferente"

### Análises de apoio (não são pilares, não recebem o mesmo nível de profundidade)
- **Cohort Analysis** (retenção por coorte de entrada, mês a mês): vira um heatmap dentro da seção de RFM, não uma seção própria
- **Market Basket Analysis** (regras de associação entre produtos): fica fora do artigo principal, vira "Parte 2"/artigo bônus separado

---

## 7. Limpeza de dados e padrões de qualidade

### 7.1 Lógica de limpeza (herdada da versão One Up, adaptada)

A versão anterior seguia estas regras, que devem ser mantidas no espírito, traduzidas para o Dunnhumby:

| Regra na One Up | Por quê | Equivalente no Dunnhumby |
|---|---|---|
| Colunas numéricas convertidas com `to_numeric(errors='coerce')` | Planilha vinda do BI tinha texto misturado em coluna numérica | Mesma conversão em `QUANTITY`, `SALES_VALUE` e descontos. **Melhoria:** registrar quantas linhas foram convertidas ou zeradas, em vez de só aplicar `fillna(0)` em silêncio |
| Linhas com data inválida descartadas | Sem data não entra em recência nem em cohort | Converter `DAY` em data real; descartar e contar linhas que falharem |
| Venda válida = `nota IS NOT NULL` | Linhas sem nota não eram transação concluída | Venda válida = `BASKET_ID` presente e `QUANTITY > 0` |
| Faturamento negativo = devolução, tratado à parte | Devolução não é venda e distorce média | Investigar `SALES_VALUE <= 0` e `QUANTITY <= 0`; separar como devolução/ajuste, não misturar com venda |
| Cliente com valor líquido ≤ 0 fora do RFM | Devolução maior que compra não é perfil de cliente, é caso à parte | Mesmo critério no RFM, com a contagem de excluídos documentada |
| Dimensão de produto com chave única (`ROW_NUMBER` sobre SKU+tamanho) | Evitar explosão de linhas no JOIN | Conferir se `PRODUCT_ID` é único em `product` antes do JOIN; se não for, deduplicar |
| `COUNT(*)` em vez de `COUNT(nota)` ao contar linhas sem nota | `COUNT(coluna)` ignora nulos e subconta | Mesma regra |
| Texto com `ILIKE '%...%'` | Tolerar variação de escrita em categoria/coleção | Mesmo padrão em `DEPARTMENT`/`COMMODITY_DESC` |
| Hash MD5 do arquivo + tabela `log_cargas` | Saber qual versão da base gerou cada resultado | Manter: hash + data da carga + nome do arquivo |
| Desconto em % do bruto com `NULLIF(..., 0)` | Evitar divisão por zero | Manter; verificar antes o sinal das colunas de desconto (podem vir negativas) |

Produzir um **relatório de qualidade dos dados** (seção no notebook e expander no app), com: linhas brutas, linhas descartadas por motivo, nulos por coluna, duplicados, casos de devolução, households sem demografia, e o total por semana batendo com o arquivo bruto. Cada decisão de limpeza deve vir com a quantidade de linhas afetada e o motivo.

### 7.2 Definição única de cada métrica
Faturamento, ticket médio, itens por cesta, % de desconto, cliente ativo e janela de "último mês" são definidos **uma vez**, como views no DuckDB (ex: `vw_metricas_cesta`, `vw_metricas_cliente`). O prompt do agente, o glossário e o notebook consomem essas views, sem recalcular a fórmula por conta própria. Objetivo: o chat e as abas de análise nunca podem dar dois números diferentes para a mesma pergunta.

### 7.3 Teste de qualidade do chatbot
- Conjunto de ~20 perguntas de negócio, cada uma com a resposta esperada calculada por SQL escrito à mão
- Script que roda todas contra o agente e reporta a taxa de acerto (número bate dentro de uma tolerância) e quais erraram
- Rodar sempre que o prompt, o glossário ou as views mudarem
- No app, cada resposta do chat mostra a query SQL usada num expander recolhido, para o usuário poder conferir

### 7.4 Validação do modelo de churn
- Split **temporal**: treinar com um período e testar no período seguinte (nunca sorteio aleatório de linhas, que vaza o futuro para o treino)
- Definir churn explicitamente, com a justificativa do corte (ex: sem compra em N semanas)
- Comparar com um baseline simples ("não comprou nas últimas N semanas = vai sair"). Se o modelo não ganhar do baseline, reportar isso como achado
- Reportar AUC, precisão/recall na classe minoritária e matriz de confusão; checar desbalanceamento

### 7.5 Toda análise termina em "e daí?"
Cada seção de análise (no notebook e nas abas do app) fecha com um bloco fixo:
- **Conclusão:** o que os dados mostram, numa frase
- **Ação recomendada:** o que a gerência deveria fazer com isso
- **Impacto estimado:** tamanho do efeito em R$ ou % (não só p-valor)
- **Limitações:** o que o dado não permite afirmar

No app, esse bloco aparece **no topo** de cada aba, antes dos gráficos e tabelas. A diretoria lê a conclusão primeiro e desce para o detalhe só se quiser.

---

## 8. Código reaproveitável de uma versão anterior (não escrever de novo)

Uma versão anterior deste projeto (sobre a base da One Up) já validou e testou três módulos que são **agnósticos de schema** e podem ser copiados diretamente:

- **`token_counter.py`** — callback de contagem de tokens do LangChain/Groq. Copiar sem alteração.
- **`teste_hipotese.py`**, funções `testar_normalidade_por_grupo`, `teste_kruskal_wallis`, `post_hoc_pairwise_mannwhitney` — recebem nomes de coluna como parâmetro, funcionam com qualquer variável. Copiar sem alteração. Só a função de **preparação dos dados** (que buscava desconto na base antiga) precisa ser reescrita para a query do Dunnhumby.
- **`glossario_rag.py`**, funções `_carregar_modelo`, `_construir_indice`, `buscar_termos_relevantes` — mecanismo de busca vetorial. Copiar sem alteração. Só o **conteúdo** da lista `GLOSSARIO` precisa ser reescrito com termos do Dunnhumby (household, cesta/basket, desconto de cupom vs. de loja, department/commodity, etc. — e remover qualquer menção a "vendedora/filial", que não existe aqui).

Esses três arquivos, comentados com o que reaproveitar e o que reescrever, devem estar anexados junto com este guia.

**Não tente reaproveitar:** a função de ETL/ingestão da versão anterior (schema totalmente diferente), o texto de `INSTRUCOES_SISTEMA` do agente (regras de negócio da One Up não se aplicam aqui), a query de RFM antiga (schema diferente).

---

## 9. Entregáveis esperados

1. **App Streamlit publicado** — o produto principal. Aba de chat (linguagem natural + glossário + contador de tokens) como primeira aba, seguida das abas de análise (RFM/clustering com cohort de apoio, CLV, churn, teste de hipótese). Carga por upload ou pasta, deploy no Streamlit Community Cloud.
1b. **Servidor MCP + spec + 3 skills** — ferramentas conforme `docs/spec_ferramentas_mcp.md`, testes de guard-rail (`pytest`), avaliação com perguntas de negócio e perguntas maliciosas, skills `consultas-sql`, `analise-estatistica` e `qualidade-validacao`.
2. **Notebook Jupyter narrado** — mesmas análises estatísticas, com o raciocínio e as escolhas metodológicas explicadas em texto. É onde o recrutador de Ciência de Dados vai conferir o rigor.
3. **README do repositório, completo** — é o documento de entrada do projeto e deve cobrir a estrutura inteira, não só uma área (nem só análise de dados, nem só varejo, nem só IA). Seções mínimas:
   - **O problema de negócio** e por que a carga é por planilha exportada do BI (seção 1)
   - **O que o app faz**, com prints: chat e abas de análise
   - **Arquitetura**: diagrama do fluxo planilha → ETL → Star Schema no DuckDB → views de métricas → funções do núcleo → servidor MCP → app Streamlit (Groq) e Claude Desktop/Code (skills); por que Groq no app público
   - **Guard-rails e avaliação**: regras impostas no código, testes, e os números da avaliação (acerto, ferramenta certa, tokens e tempo médios, bloqueio de perguntas maliciosas)
   - **Dados**: o dataset, as tabelas usadas, a janela de análise e a base de comparação do ano anterior
   - **Limpeza e qualidade**: regras aplicadas e o resumo do relatório de qualidade
   - **Definição das métricas** (tabela com nome, definição de negócio e fórmula)
   - **O chatbot**: como funciona, exemplos de perguntas, taxa de acerto no conjunto de teste
   - **As análises**: para cada uma, a pergunta de negócio, o método, as escolhas estatísticas e o bloco "e daí?"
   - **Como rodar local** (passo a passo) e **link do app publicado**
   - **Estrutura de pastas** do repositório
   - **Limitações** do dataset e da abordagem
   - **Implementado vs. roadmap** (Market Basket no roadmap)
   - Tom técnico e explicativo, sem linguagem de post. O tom de divulgação fica para o artigo, que será escrito à parte.
4. Ao final, um **artigo para LinkedIn** será escrito com base nos achados — não gerar esse texto agora.

---

## 10. Instruções diretas de execução

### Pré-trabalho e fluxo de trabalho com o Claude Code
- O repositório já começa com `git init`, `.gitignore` e um commit inicial com os guias.
- Fluxo de cada fase: **explorar → planejar → implementar → commit**. Planejar no modo de planejamento, esperar aprovação, implementar, verificar e só então fazer o commit.
- Um commit por fase aprovada, com mensagem descritiva (Conventional Commits). Isso permite voltar a um ponto bom se algo sair errado.
- Segredos nunca no código nem no Git: chave do Groq via `st.secrets` (deploy) ou campo na sidebar (local); `.env` e `.streamlit/secrets.toml` no `.gitignore`.
- Ambiente isolado (`venv`) e `requirements.txt` com versões travadas desde a primeira fase.
- Cada fase entrega um jeito de verificar o próprio resultado antes de ir para a próxima.
- `CLAUDE.md` é a memória do projeto: manter "Comandos" e "Decisões registradas" atualizados.

### Regras de análise

- Priorize rigor estatístico sobre volume de código. Uma análise com validação (IC via bootstrap, K validado, split treino/teste correto) vale mais que cinco análises soltas.
- Sempre que uma escolha estatística for feita (K do cluster, teste paramétrico vs. não-paramétrico, threshold de classificação), documente o porquê no notebook — isso é parte do valor do portfólio, não só o resultado final.
- Nomear os segmentos de cliente com base no perfil real dos dados (olhar a tabela de perfil por cluster antes de nomear), não usar nomes genéricos fixos sem checar se batem.
- Qualquer limitação do dataset (ex: sem vendedora individual, período histórico 2016-2018) deve ser declarada explicitamente no README/notebook, não escondida.

---

## 11. Boas práticas sênior: o que a versão anterior tinha e o que faltava

O arquivo `guia_boas_praticas_analise_senior.md` (anexo) define o modo de trabalho do projeto. Abaixo, a comparação com o código da versão One Up, para deixar claro o que manter e o que corrigir nesta versão.

| Prática | Versão anterior | O que fazer agora |
|---|---|---|
| Saber a decisão que cada análise apoia | ❌ Análises sem pergunta de negócio escrita | Cada seção do notebook e cada aba do app começa com a decisão que apoia |
| Conferir granularidade e chaves | ⚠️ `dim_produto` com `ROW_NUMBER` evitava explosão de JOIN, mas sem conferência de contagem | Contar linhas antes e depois de cada JOIN no ETL e registrar no relatório de qualidade |
| Limpeza documentada | ❌ `fillna(0)` e `dropna` em silêncio | Registrar quantas linhas cada regra afetou (seção 7.1) |
| Reconciliação com o bruto | ❌ Não existia | Total por semana da base limpa vs. bruta, no relatório de qualidade |
| Métrica com definição única | ❌ Fórmulas repetidas no prompt, no glossário e no código | Views no DuckDB consumidas por tudo (seção 7.2) |
| Nomes de segmento vindos do dado | ❌ Lista fixa de nomes ordenada por valor; gerou um "Segmento 5" sem nome | Nomear olhando o perfil real de cada cluster; nenhum cluster sem nome |
| K do K-Means justificado | ❌ Slider manual | Cotovelo e/ou silhueta, com o gráfico no notebook |
| Estabilidade dos clusters | ⚠️ Semente fixa (bom), mas sem teste de estabilidade | Rodar com outras sementes/recortes e reportar se os segmentos se mantêm |
| Tamanho de efeito | ✅ Eta² já era reportado no Kruskal-Wallis | Manter; adicionar intervalo de confiança via bootstrap nas diferenças principais |
| Correção para múltiplas comparações | ✅ Holm no post-hoc | Manter |
| Baseline e validação temporal | ❌ Não havia modelo preditivo | Seção 7.4 |
| Sanity check de negócio | ❌ Não sistematizado | Checar ordem de grandeza de ticket médio, itens por cesta e desconto antes de publicar qualquer número |
| Títulos de gráfico com a conclusão | ❌ Títulos descritivos ("Dispersão dos clientes") | Título diz o achado; descrição vai no eixo/legenda |
| Bloco "e daí?" | ❌ Não existia | Seção 7.5, no topo de cada aba |
| Banco só leitura para o LLM | ✅ Conexão Singleton `read_only` | Manter |
| Limite de linhas nas consultas do agente | ❌ Discutido, não implementado | Regra no prompt + `LIMIT` padrão |
| Mostrar a query ao usuário | ❌ Não existia | Expander com o SQL em cada resposta |
| Teste de qualidade do chatbot | ❌ Não existia | Seção 7.3 |
| Registro de uso | ⚠️ Só contagem de tokens | Log de pergunta, horário, query gerada e se deu erro (para medir adoção e achar perguntas que o sistema erra) |
| Chave de API | ⚠️ Campo na sidebar | Manter o campo para uso local; no deploy, `st.secrets` |
| Reprodutível em um comando | ❌ Sem versões travadas nem configuração central | `requirements.txt` com versões, semente fixa, janela de 6 meses e parâmetros num `config.yaml` |
| Versionamento dos dados | ✅ Hash MD5 + `log_cargas` | Manter |
