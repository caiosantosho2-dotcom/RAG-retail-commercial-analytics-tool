# Prompt para o Claude Code

## Antes de abrir o Claude Code (você faz, uma vez só)

1. Crie a pasta do projeto e abra ela no VS Code.
2. Coloque os arquivos no lugar:
   - raiz: `CLAUDE.md` e `.gitignore`
   - `docs/`: `guia_projeto_dunnhumby.md`, `guia_boas_praticas_analise_senior.md`, `spec_ferramentas_mcp.md`
   - `.claude/skills/`: as pastas `consultas-sql`, `analise-estatistica` e `qualidade-validacao`, cada uma com seu `SKILL.md`
   - `referencia/`: `token_counter.py`, `glossario_rag.py`, `teste_hipotese.py`
3. No terminal, na raiz do projeto:
   ```
   git init
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   git add .
   git commit -m "chore: estrutura inicial e guias do projeto"
   ```
4. Confira que o `.gitignore` está na raiz **antes** do primeiro commit (ele impede que dados brutos, `venv` e chaves de API subam pro GitHub).
5. Rode `claude --permission-mode plan` na raiz do projeto (abre já no modo de planejamento; `Shift+Tab` alterna entre os modos) e cole o texto abaixo.

Passo a passo detalhado, para quem está fazendo isso pela primeira vez: `passo_a_passo_montar_projeto.md`.

**Durante o projeto:** use `/clear` ao trocar de fase, para começar a fase nova sem o histórico da anterior (o que importa fica no `CLAUDE.md` e em "Decisões registradas"). Quando o plano aparecer, `Ctrl+G` abre ele no editor para você ajustar antes de aprovar.

## Texto para colar

---

Vou construir com você um projeto de portfólio completo. Antes de escrever qualquer código, leia com atenção estes arquivos:

- `docs/guia_projeto_dunnhumby.md` — o briefing completo: problema de negócio, dataset, modelagem, chatbot, escopo analítico, limpeza, padrões de qualidade e entregáveis. **É a fonte da verdade do projeto.**
- `docs/guia_boas_praticas_analise_senior.md` — o modo de trabalho que quero seguir em toda análise.
- `docs/spec_ferramentas_mcp.md` — o contrato de cada ferramenta do servidor MCP: entradas, saídas, guard-rails, avaliação e critério de pronto.
- `.claude/skills/` — três skills (`consultas-sql`, `analise-estatistica`, `qualidade-validacao`) com as boas práticas de cada tipo de tarefa. Use-as enquanto constrói.
- `referencia/token_counter.py`, `referencia/glossario_rag.py`, `referencia/teste_hipotese.py` — código já testado de uma versão anterior. A seção 8 do guia diz exatamente o que reaproveitar como está e o que reescrever.

## Em uma frase

Uma ferramenta para a área comercial de varejo: o usuário arrasta a planilha que exporta do BI, faz perguntas em linguagem de negócio num chat (que responde consultando os dados via SQL) e consulta abas de análise estatística de clientes com a conclusão de negócio em destaque. Tudo sobre o dataset público Dunnhumby "The Complete Journey".

## O que é inegociável

1. **O chat é a primeira aba e o centro do produto.** Linguagem de negócio, glossário RAG injetado no prompt, query SQL visível num expander, contador de tokens na sidebar.
2. **Carga por arquivo (upload) e por pasta `data/`**, com upload tendo prioridade. Isso é proposta de produto, não limitação (seção 1 do guia).
3. **Cada métrica é definida uma única vez** (views no DuckDB), e o chat, as abas e o notebook usam essas mesmas views. Nunca dois números diferentes para a mesma pergunta.
4. **Comparação com o ano anterior**: janela das últimas 26 semanas contra as mesmas semanas do ano anterior, alinhadas por semana e comparando as mesmas lojas.
5. **Toda aba de análise começa pelo bloco "e daí?"**: conclusão, ação recomendada, impacto estimado e limitações, antes dos gráficos.
6. **Limpeza documentada**: cada regra com quantas linhas afetou e por quê, e o total limpo reconciliado com o bruto.
7. **README completo**, cobrindo a estrutura inteira do projeto, conforme a seção 9 do guia. Técnico e explicativo, sem tom de post de rede social.
8. **Nada no README ou no app menciona saída de emprego ou versão anterior.** O foco é o problema de negócio.
9. **Núcleo primeiro, MCP depois.** As funções Python são construídas e testadas sem MCP; o servidor MCP só as embrulha. O mesmo servidor atende o app (Groq) e o Claude Desktop/Code.
10. **Guard-rails no código, com testes.** Só leitura, só SELECT/WITH, uma instrução, limite de linhas, timeout. Se a spec e algum outro arquivo divergirem, vale a spec.

## Como quero trabalhar

- **Primeiro o plano, depois o código.** Leia tudo e me devolva: (a) seu entendimento do projeto em poucos parágrafos, (b) a estrutura de pastas proposta, (c) o plano em fases, (d) suas dúvidas e qualquer ponto do guia que pareça contraditório ou ambíguo. Espere minha aprovação antes de codar.
- **Construa por fases e pare no fim de cada uma** para eu revisar. Ordem sugerida:
  1. Setup do ambiente, download dos dados, auditoria inicial da base (granularidade, chaves, nulos, negativos, linhas estranhas como combustível ou valor zero, semanas iniciais incompletas)
  2. ETL + Star Schema + relatório de qualidade dos dados
  3. Views de métricas (definição única)
  4. Chatbot (glossário, agente com consulta SQL, carga por upload/pasta) + primeira versão do conjunto de teste com taxa de acerto
  5. Análises, uma por vez, como funções Python testadas: RFM + K-Means (com K validado e cohort de apoio) → CLV → modelo de churn (validação temporal + baseline) → teste de hipótese
  6. Servidor MCP embrulhando as funções + testes de guard-rail e de formato + log de chamadas + agente do app usando o MCP via `langchain-mcp-adapters` + avaliação completa (incluindo perguntas maliciosas)
  7. Notebook narrado
  8. README, deploy no Streamlit Community Cloud, recorte em Parquet para o repositório
- **Quando uma escolha estatística ou de negócio não estiver no guia, pergunte em vez de decidir sozinho.** Se decidir algo pequeno, registre a decisão e o motivo.
- **Priorize rigor sobre volume.** Uma análise validada vale mais que várias soltas. Não adicione análises fora do escopo da seção 6.
- **Faça sanity check dos números** antes de me mostrar (ordem de grandeza de ticket médio, itens por cesta, desconto).
- Reprodutível: `requirements.txt` com versões travadas, semente fixa, parâmetros em `config.yaml`. Chave da API do Groq via `st.secrets` ou campo na sidebar, nunca no código.
- **Git:** o repositório já foi iniciado e tem um `.gitignore`. Ao fim de cada fase que eu aprovar, faça um commit com mensagem descritiva (padrão Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`). Nunca faça commit de `data/raw/`, `venv/`, `.env` ou `.streamlit/secrets.toml`; se algum arquivo novo precisar ficar fora, atualize o `.gitignore`.
- **Verificação:** cada fase entrega um jeito de conferir o próprio trabalho (script de checagem do ETL, relatório de qualidade, conjunto de teste do chatbot, testes das funções de métrica). Rode antes de me mostrar.
- **Memória do projeto:** mantenha as seções "Comandos" e "Decisões registradas" do `CLAUDE.md` atualizadas ao fim de cada fase.

Comece lendo os arquivos e me devolvendo o plano.
