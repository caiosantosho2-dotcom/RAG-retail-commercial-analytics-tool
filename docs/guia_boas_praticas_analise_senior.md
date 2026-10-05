# Como um sênior conduz uma análise de dados de varejo

Guia de referência: o passo a passo, as perguntas que se faz à base e os pontos de atenção. Escrito para análises de cliente/venda como a do projeto, mas vale para quase qualquer análise de negócio.

A ideia central: **um júnior entrega respostas; um sênior entrega respostas em que dá para confiar e que levam a uma decisão.** Quase tudo abaixo serve a isso.

---

## Passo 1 — Entender a pergunta antes de abrir os dados

Antes de qualquer query, o sênior responde por escrito:

- **Qual decisão essa análise vai apoiar?** Se ninguém vai decidir nada com o resultado, a análise provavelmente não precisa existir.
- **Quem vai usar e como?** Diretoria quer conclusão e impacto; analista quer detalhe e método.
- **O que seria um resultado surpreendente?** Escrever a hipótese antes protege contra "achar" qualquer coisa depois.
- **Qual o nível de precisão necessário?** Uma estimativa com margem de 10% às vezes basta. Gastar uma semana por uma casa decimal a mais é desperdício.

## Passo 2 — Conhecer a base (as perguntas que sempre se faz)

**Granularidade e cobertura**
- O que é uma linha desta tabela? (um item, uma cesta, um cliente, um dia?)
- Qual o período coberto? Tem buraco de datas? O primeiro e o último mês estão completos?
- A base é toda a população ou uma amostra? Quem ficou de fora? (No Dunnhumby, são 2.500 households "frequentes" — não é o cliente médio do varejista.)

**Chaves e relações**
- Qual a chave única de cada tabela? Ela é realmente única?
- Os JOINs multiplicam linhas? (Conferir a contagem antes e depois de cada JOIN.)
- Existem registros órfãos (venda de produto que não está no cadastro)?

**Valores**
- Nulos: quantos, em quais colunas, e o nulo significa "zero" ou "desconhecido"? São coisas diferentes.
- Negativos e zeros: são devolução, estorno, ajuste ou erro?
- Outliers: são erro de digitação ou cliente real de alto valor? No varejo de luxo, o outlier muitas vezes é o cliente mais importante — não se descarta sem investigar.
- Duplicados: a mesma transação aparece duas vezes?

**Significado de negócio**
- O que cada coluna significa de verdade? (`SALES_VALUE` já é líquido de desconto? Desconto vem positivo ou negativo?)
- Quem gera esse dado e em que processo? Dado de caixa, de cadastro e de CRM têm tipos de erro diferentes.

## Passo 3 — Limpar e documentar cada decisão

- Toda regra de limpeza vem com **quantas linhas afetou e por quê**.
- Nunca "consertar em silêncio" (ex: `fillna(0)` sem registrar quantos nulos havia).
- Manter os dados brutos intocados; a limpeza gera uma nova camada.
- **Reconciliar:** o total limpo bate com o total bruto menos o que foi removido de propósito? Se não bate, tem erro no meio.

## Passo 4 — Definir as métricas uma única vez

- Cada métrica (ticket médio, cliente ativo, churn) tem **uma** definição escrita e **um** lugar no código.
- Escrever a definição em linguagem de negócio junto com a fórmula. "Cliente ativo = comprou pelo menos uma vez nas últimas 8 semanas."
- Checar se a definição bate com a que a empresa já usa. Um número "certo" com definição diferente da do financeiro vira briga em reunião.

## Passo 5 — Análise exploratória antes de qualquer modelo

- Olhar distribuições, não só médias. Médias escondem cauda longa.
- Quebrar os números por tempo, loja e categoria: o padrão geral se mantém em cada pedaço?
- Procurar sazonalidade e eventos (feriados, campanhas) que possam explicar o que parece padrão.
- Anotar hipóteses que aparecerem, para testar depois de forma formal.

## Passo 6 — Modelar e testar com rigor

- **Começar pelo baseline mais simples** (média, regra de negócio). Modelo sofisticado que não ganha do simples não tem valor.
- **Validar do jeito que o modelo vai ser usado:** se ele vai prever o futuro, testar no futuro (split temporal).
- **Olhar tamanho do efeito, não só p-valor.** Com muitos dados, qualquer diferença minúscula dá "significativa".
- **Corrigir para múltiplas comparações** quando testar muitos pares ou muitas hipóteses.
- **Testar estabilidade:** se mudar a semente, o recorte ou um parâmetro, o resultado se mantém?
- Documentar cada escolha (por que este teste, por que este K, por que este corte).

## Passo 7 — Checar os próprios resultados antes de mostrar

- **Sanity check:** o número faz sentido de negócio? Um ticket médio de R$ 3.000 num supermercado é sinal de erro.
- **Conferir por outro caminho:** calcular o mesmo número de duas formas diferentes (SQL e pandas, por exemplo).
- **Correlação não é causa:** "clientes que recebem mais desconto compram mais" não prova que o desconto fez eles comprarem.
- **Viés de sobrevivência e de seleção:** quem ficou fora da base poderia mudar a conclusão?
- **Pedir para alguém revisar** uma query ou um gráfico importante. Sênior não é quem não erra; é quem cria jeitos de pegar o erro.

## Passo 8 — Comunicar: todo resultado termina em "e daí?"

Estrutura fixa para cada achado:
1. **Conclusão** em uma frase, em linguagem de negócio
2. **Ação recomendada**
3. **Impacto estimado** (em R$, %, clientes)
4. **Nível de confiança e limitações**

Regras de apresentação:
- Conclusão primeiro, método depois. Quem quiser detalhe desce.
- Um gráfico, uma mensagem. O título do gráfico diz a conclusão ("Clientes Fiéis recebem 2x mais desconto"), não a descrição ("Desconto por segmento").
- Mostrar incerteza (intervalo de confiança, margem) quando ela mudar a decisão.
- Dizer o que a análise **não** mostra antes que alguém tire a conclusão errada.

## Passo 9 — Deixar reprodutível e seguro

- Qualquer pessoa roda o projeto e chega no mesmo número (semente fixa, versões travadas, parâmetros num arquivo de configuração).
- Versionar os dados de entrada (hash do arquivo, data da carga).
- Nunca colocar chave de API, senha ou dado pessoal no código ou no GitHub.
- Em ferramenta com LLM: acesso ao banco **só leitura**, limite de linhas por consulta, e mostrar ao usuário a query que gerou a resposta.
- Registrar uso (quem perguntou o quê, quando) desde o primeiro dia, para medir adoção e achar perguntas que o sistema erra.

---

## Checklist rápido antes de entregar qualquer análise

- [ ] Sei qual decisão isto apoia
- [ ] Sei o que é uma linha de cada tabela e confirmei as chaves
- [ ] Contei linhas antes e depois de cada JOIN
- [ ] Documentei cada limpeza com quantidade e motivo
- [ ] O total limpo reconcilia com o bruto
- [ ] Cada métrica tem uma definição escrita e um lugar no código
- [ ] Comparei o modelo com um baseline simples
- [ ] Validei do jeito que vai ser usado (temporal, se for prever o futuro)
- [ ] Reportei tamanho do efeito, não só p-valor
- [ ] Fiz sanity check de negócio nos números finais
- [ ] Cada achado tem conclusão, ação, impacto e limitação
- [ ] Alguém consegue rodar e chegar no mesmo número
