# Rotina de trabalho — o que você faz e digita, do começo ao fim

Este guia começa **depois** que a pasta está montada e o primeiro plano foi aprovado (passo a passo anterior). É o que você repete a cada dia de trabalho e a cada fase.

Princípio: **você decide, o Claude executa.** Seu papel é aprovar o plano, conferir o resultado e mandar fazer o commit. Nunca aceite algo que você não entendeu: pergunte antes.

---

## Parte 1 — Abrir uma sessão (sempre igual)

1. Abra o VS Code → **Arquivo → Abrir Pasta Recente** → escolha o projeto.
2. Abra o terminal: **Terminal → Novo Terminal**.
3. Ative o ambiente Python:
   ```
   .\venv\Scripts\Activate.ps1
   ```
   Deve aparecer `(venv)` no começo da linha.
4. Veja em que pé está o Git:
   ```
   git status
   ```
   - "nothing to commit, working tree clean" = tudo salvo, pode seguir.
   - Lista de arquivos modificados = sobrou trabalho da sessão anterior. Peça pro Claude explicar o que é antes de continuar.
5. Abra o Claude Code:
   ```
   claude --permission-mode plan
   ```
6. **Primeira mensagem de toda sessão nova** (copie e cole):
   ```
   Leia o CLAUDE.md, principalmente "Comandos" e "Decisões registradas". Me diga em que fase estamos, o que já foi feito e qual é o próximo passo. Não altere nada ainda.
   ```

> Existe também `claude -c`, que continua a última conversa daquela pasta. Mas conversa longa pesa e perde qualidade. Prefira começar limpo com a mensagem acima: o que importa está registrado no `CLAUDE.md`.

---

## Parte 2 — O ciclo de cada fase (5 passos)

### Passo 1 — Pedir o plano da fase
Ainda no modo de planejamento:
```
Vamos começar a Fase [N]: [nome da fase]. Me apresente o plano detalhado: o que você vai criar, quais arquivos, quais decisões precisam de mim e como vamos verificar que ficou certo. Não escreva código ainda.
```

### Passo 2 — Ler o plano e decidir
- Faltou algo? Sobrou algo? Está de acordo com o guia?
- Ele fez perguntas? **Responda cada uma.** Se for decisão sua, peça: *"Registre essa decisão em 'Decisões registradas' do CLAUDE.md."*
- Não gostou de algo? Diga em português normal: *"Não quero X, quero Y. Refaça o plano."*
- Gostou:
  ```
  Plano aprovado. Pode implementar a Fase [N]. Pare no final para eu revisar, sem fazer commit ainda.
  ```
  O Claude normalmente pergunta se pode sair do modo de planejamento e seguir. Se aparecer a opção de **aprovar cada edição manualmente**, escolha essa enquanto você está aprendendo.

### Passo 3 — Acompanhar a implementação
O Claude vai pedir permissão para criar arquivos e rodar comandos. Regras simples:
- **Leia o que ele pede antes de aceitar.** Não entendeu um comando? Digite *"O que esse comando faz?"* antes de aceitar.
- **Nunca aceite** nada que mexa no `.env` ou no `secrets.toml`, apague arquivos fora do esperado, ou faça `git push`.
- Se ele sair do plano ou começar a fazer algo que você não pediu, aperte `Esc` e diga: *"Pare. Isso não estava no plano."*

### Passo 4 — Revisar o resultado
Quando ele parar, peça:
```
Rode as verificações desta fase e me mostre os resultados. Depois me explique o que você fez como se eu fosse um analista comercial, sem jargão.
```
E confira com **três perguntas**:
1. Rodou sem erro?
2. Os números fazem sentido de negócio? (ticket médio de supermercado em dezenas de dólares, não milhares)
3. Cada decisão importante foi registrada?

Algo estranho? Aponte: *"Isso não bate com a seção [X] do guia. Releia e corrija."*

### Passo 5 — Commit e fase seguinte
Só depois de aprovar:
```
Fase [N] aprovada. Faça o commit com uma mensagem descritiva e atualize "Comandos" e "Decisões registradas" no CLAUDE.md.
```
Confira no terminal:
```
git log --oneline
```
Deve aparecer o commit novo no topo. Depois digite `/clear` e comece a próxima fase pelo passo 1.

---

## Parte 3 — As fases e o que você confere em cada uma

| Fase | O que o Claude entrega | O que você confere |
|---|---|---|
| 1. Setup e auditoria | Ambiente pronto, dados baixados em `data/raw/`, relatório da auditoria | Dados **não** aparecem no `git status`. A auditoria apontou negativos, zeros, linhas estranhas? Você entendeu cada achado? |
| 2. ETL e qualidade | Star Schema no DuckDB + relatório de qualidade | Cada regra de limpeza diz quantas linhas afetou e por quê. O total limpo bate com o bruto |
| 3. Views de métricas | Uma view por métrica, com a definição | Ticket médio, itens por cesta e % de desconto na ordem de grandeza certa. Cada métrica tem definição de negócio escrita |
| 4. Chatbot | App com chat, glossário, upload e pasta, SQL visível | Você arrasta um arquivo, pergunta, e a resposta vem com a query. Perguntas de teste com taxa de acerto |
| 5. Análises (uma por vez) | RFM + K-Means → CLV → churn → teste de desconto | Cada uma tem o bloco "e daí?" no topo. K justificado. Churn comparado com regra simples. **Pare e revise após cada análise** |
| 6. Servidor MCP | Ferramentas, testes de guard-rail, log, avaliação | `pytest` passando. Perguntas maliciosas 100% bloqueadas. Números da avaliação registrados |
| 7. Notebook | Narrativa do início ao fim | Roda inteiro, do zero, sem erro. Cada escolha estatística explicada |
| 8. README e deploy | README completo, app publicado, Parquet no repositório | README cobre o projeto inteiro. Sem chave nem dado bruto no GitHub. O link do app abre |

---

## Parte 4 — Mensagens prontas para situações comuns

**Pedir explicação**
```
Explique isso de outro jeito, com um exemplo de varejo. Não entendi [o que não entendeu].
```

**Quando a decisão é sua**
```
Decisão: [o que você decidiu]. Motivo: [por quê]. Registre em "Decisões registradas" do CLAUDE.md e siga o plano com isso.
```

**Quando ele errar**
```
Isso está errado porque [motivo]. Releia a seção [X] do guia e corrija. Depois me explique o que causou o erro.
```

**Quando ele quiser incluir algo fora do escopo**
```
Isso está fora do escopo da seção 6 do guia. Não faça. Anote como ideia futura no final do CLAUDE.md.
```

**Quando travar ou a conversa ficar confusa**
```
/clear
```
e recomece com a mensagem da Parte 1, passo 6.

**Antes de encerrar o dia**
```
Atualize "Comandos" e "Decisões registradas" no CLAUDE.md com o estado atual e o próximo passo. Se houver algo aprovado sem commit, me avise.
```

---

## Parte 5 — Um hábito que vale ouro: o diário de bordo

Crie um arquivo simples fora do código (pode ser `docs/diario_de_bordo.md`) e, sempre que o Claude errar e **você** perceber, anote em 3 linhas:
- o que ele fez
- o que estava errado
- como você percebeu

Isso vira o material mais forte do artigo ("onde a IA errou e como eu peguei") e mostra, em entrevista, que é você quem valida. Tentar lembrar depois sai fraco: anote na hora.
