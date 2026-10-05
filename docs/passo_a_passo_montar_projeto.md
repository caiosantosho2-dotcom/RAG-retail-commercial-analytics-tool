# Passo a passo — montar a pasta do projeto e abrir o Claude Code

Para quem está fazendo isso pela primeira vez. Feito para **Windows + VS Code** (PowerShell). Leva uns 20 a 30 minutos.

Em cada passo tem um **"Deve aparecer"**: se o que você vê for diferente disso, pare e veja a seção "Se algo der errado" no final.

---

## Antes de começar: o que precisa estar instalado

Abra o terminal do VS Code (menu **Terminal → Novo Terminal**) e rode cada linha:

```
python --version
git --version
claude --version
```

**Deve aparecer:** um número de versão em cada uma.

- Se `git` não for reconhecido: instale em git-scm.com (deixe todas as opções padrão), **feche e abra o VS Code** e teste de novo.
- Se `python` não for reconhecido: instale em python.org e marque a opção "Add Python to PATH" no instalador.
- O Claude Code você já tem instalado.

---

## Passo 1 — Criar a pasta do projeto

1. No Explorador de Arquivos do Windows, crie uma pasta, por exemplo `C:\Projetos\Assistente_Dunnhumby`.
   - Use nome **sem espaço e sem acento**. Evita problema com comandos.
2. No VS Code: **Arquivo → Abrir Pasta**, escolha essa pasta, clique em "Sim, confio nos autores".

**Deve aparecer:** o nome da pasta no topo do Explorer (barra lateral esquerda), vazia.

## Passo 2 — Criar as subpastas

No terminal do VS Code (ele já abre dentro da pasta do projeto), rode:

```
mkdir docs
mkdir referencia
mkdir .claude\skills\consultas-sql
mkdir .claude\skills\analise-estatistica
mkdir .claude\skills\qualidade-validacao
```

**Deve aparecer:** no Explorer, as pastas `docs`, `referencia` e `.claude` (com `skills` dentro e as três pastas dentro dela).

> A pasta `.claude` começa com ponto. É assim mesmo: o Claude Code procura exatamente esse nome.

## Passo 3 — Colocar cada arquivo no lugar

Baixe os arquivos que eu te enviei aqui no chat. Depois **arraste cada um para a pasta certa no Explorer do VS Code**:

| Arquivo | Vai para |
|---|---|
| `CLAUDE.md` | raiz (fora de qualquer pasta) |
| `.gitignore` | raiz (ver aviso abaixo) |
| `guia_projeto_dunnhumby.md` | `docs/` |
| `guia_boas_praticas_analise_senior.md` | `docs/` |
| `spec_ferramentas_mcp.md` | `docs/` |
| `token_counter.py` | `referencia/` |
| `glossario_rag.py` | `referencia/` |
| `teste_hipotese.py` | `referencia/` |
| `SKILL.md` da skill de SQL | `.claude/skills/consultas-sql/` |
| `SKILL.md` da skill estatística | `.claude/skills/analise-estatistica/` |
| `SKILL.md` da skill de qualidade | `.claude/skills/qualidade-validacao/` |
| `prompt_claude_code.md` | `docs/` (você só copia o texto dele no passo 7) |

**Atenção com os três `SKILL.md`:** os três têm o mesmo nome. O Windows pode baixar como `SKILL.md`, `SKILL (1).md` e `SKILL (2).md`, e fica fácil trocar. Para saber qual é qual, **abra o arquivo e olhe a linha `name:` no topo**:

- `name: consultas-sql` → vai na pasta `consultas-sql`
- `name: analise-estatistica` → vai na pasta `analise-estatistica`
- `name: qualidade-validacao` → vai na pasta `qualidade-validacao`

Depois de arrastar, **renomeie** cada um para exatamente `SKILL.md` (clique com o botão direito → Renomear).

**Aviso sobre o `.gitignore`:** o Windows às vezes baixa esse arquivo com outro nome (por exemplo `gitignore.txt`) ou esconde ele. O jeito mais seguro é criar direto no VS Code:
1. Clique com o botão direito no espaço vazio do Explorer → **Novo Arquivo**.
2. Digite exatamente `.gitignore` e Enter.
3. Cole este conteúdo e salve (Ctrl+S):

```
# Ambiente Python
venv/
.venv/
__pycache__/
*.pyc
.ipynb_checkpoints/

# Segredos (nunca versionar)
.env
.env.*
.streamlit/secrets.toml

# Dados brutos ficam fora do Git (baixados via baixar_dados.py).
# O recorte em Parquet de data/processed/ É versionado.
data/raw/
*.duckdb
*.duckdb.wal

# Logs e temporários
logs/
*.log

# Sistema e editor
.DS_Store
Thumbs.db
.vscode/
```

**Deve aparecer:** o Explorer com esta estrutura:

```
Assistente_Dunnhumby/
├── .claude/
│   └── skills/
│       ├── analise-estatistica/SKILL.md
│       ├── consultas-sql/SKILL.md
│       └── qualidade-validacao/SKILL.md
├── docs/
│   ├── guia_projeto_dunnhumby.md
│   ├── guia_boas_praticas_analise_senior.md
│   ├── spec_ferramentas_mcp.md
│   └── prompt_claude_code.md
├── referencia/
│   ├── token_counter.py
│   ├── glossario_rag.py
│   └── teste_hipotese.py
├── .gitignore
└── CLAUDE.md
```

Confira com calma, arquivo por arquivo. Esse é o passo em que mais acontece erro de pasta.

## Passo 4 — Criar o ambiente Python isolado

No terminal:

```
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Deve aparecer:** `(venv)` no início da linha do terminal.

> O `venv` é uma "caixa" só deste projeto para as bibliotecas Python. Assim, instalar coisa aqui não bagunça o resto do computador.

Se der erro dizendo que "a execução de scripts foi desabilitada neste sistema", rode isto uma vez e tente o comando de ativar de novo:

```
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Passo 5 — Iniciar o Git

O Git é o "histórico" do projeto: cada commit é um ponto de salvamento para onde você pode voltar se algo der errado.

Se for a primeira vez que usa Git neste computador, diga quem você é (uma vez só):

```
git config --global user.name "Seu Nome"
git config --global user.email "seu-email@exemplo.com"
```

Depois:

```
git init
git status
```

**Deve aparecer:** uma lista de arquivos em vermelho ("Untracked files"). **Confira que `venv/` NÃO aparece na lista.** Se aparecer, o `.gitignore` não está funcionando (veja "Se algo der errado").

Agora o primeiro commit:

```
git add .
git commit -m "chore: estrutura inicial e guias do projeto"
```

**Deve aparecer:** uma mensagem dizendo quantos arquivos foram adicionados.

## Passo 6 — Abrir o Claude Code no modo de planejamento

Ainda no terminal, na raiz do projeto:

```
claude --permission-mode plan
```

- O modo de planejamento faz o Claude **ler e propor, sem alterar nada**. É o que você quer na primeira sessão.
- `Shift+Tab` alterna entre os modos de permissão. Se quiser conferir em qual está, olhe o indicador na parte de baixo da tela.
- Se for a primeira vez, ele pode pedir para você entrar na sua conta. Siga o que aparecer na tela.

## Passo 7 — Colar o prompt

1. Abra `docs/prompt_claude_code.md` no VS Code.
2. Copie **só o texto da seção "Texto para colar"** (a partir de "Vou construir com você um projeto de portfólio completo...").
3. Cole no Claude Code e dê Enter.

**Deve acontecer:** o Claude lê os arquivos e devolve um plano, com a estrutura de pastas proposta e as dúvidas dele. **Não deve** escrever código ainda.

## Passo 8 — Revisar o plano antes de aprovar

Esse é o passo mais importante de todos. Leia o plano com calma:

- Ele entendeu o projeto? (O chat como produto central, carga por planilha, comparação com o ano anterior.)
- As fases fazem sentido e param no fim de cada uma?
- Respondeu as dúvidas dele? Se o plano pedir algo que não está nos guias, decida e **peça para ele registrar a decisão** em "Decisões registradas" no `CLAUDE.md`.
- Se algo do plano te incomodar, diga em português normal ("não quero X, quero Y") e peça um plano novo.

Só aprove quando o plano estiver como você quer. Depois de cada fase terminada, ele deve parar para você revisar e só então fazer o commit.

## Durante o projeto

- **Trocou de fase?** Digite `/clear` para começar a conversa limpa. O que importa fica registrado no `CLAUDE.md`, não na conversa.
- **Quer ver as skills carregadas?** Digite `/skills`.
- **Fechou o terminal e quer continuar?** Abra o terminal na pasta do projeto, ative o ambiente (`.\venv\Scripts\Activate.ps1`) e rode `claude` de novo.
- **Algo quebrou e você quer voltar?** `git log --oneline` mostra os pontos de salvamento. Peça ao Claude para ajudar a voltar, em vez de apagar arquivos na mão.

---

## Se algo der errado

| Sintoma | O que fazer |
|---|---|
| `git` / `python` / `claude` "não é reconhecido" | Feche e abra o VS Code. Se continuar, reinstale e confirme a opção de adicionar ao PATH |
| `venv/` aparece em `git status` | O `.gitignore` está com nome errado ou na pasta errada. Ele precisa se chamar exatamente `.gitignore` e estar na raiz |
| Arquivo `.gitignore.txt` | O Windows escondeu a extensão. No Explorador: Exibir → Mostrar → **Extensões de nomes de arquivos**, e renomeie |
| Erro ao ativar o venv (scripts desabilitados) | Rode o `Set-ExecutionPolicy` do passo 4 |
| `/skills` não mostra as três skills | Confira que cada `SKILL.md` está dentro da pasta com o nome da skill, dentro de `.claude/skills/` |
| O Claude Code começou a escrever código antes de eu aprovar | Você não está no modo de planejamento. Pare (Esc), `Shift+Tab` até o modo de planejamento, ou reabra com `claude --permission-mode plan` |
| Subiu uma chave de API sem querer | Troque a chave imediatamente no site do Groq. Apagar o arquivo depois não basta: o Git guarda o histórico |

---

## Checklist final antes de colar o prompt

- [ ] Estrutura de pastas igual à do passo 3
- [ ] Os três `SKILL.md` nas pastas certas (conferi pelo `name:`)
- [ ] `.gitignore` na raiz, com esse nome exato
- [ ] `(venv)` aparecendo no terminal
- [ ] `git status` não mostra `venv/`
- [ ] Primeiro commit feito
- [ ] Claude Code aberto no modo de planejamento

---

## Depois deste passo a passo

O dia a dia de trabalho (o que abrir, o que digitar e o que conferir em cada fase) está em `rotina_de_trabalho.md`. Coloque na pasta `docs/` junto com os outros.
