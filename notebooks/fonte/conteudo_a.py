"""Seções 0 a 3 do notebook: resumo, dados e qualidade, métricas e RFM. Cada item é (tipo, texto). O texto de método é fixo; todo
número do resultado é preenchido por código a partir das ferramentas do núcleo e das views."""

CELULAS = []


def md(texto):
    CELULAS.append(("md", texto.strip("\n")))


def code(texto):
    CELULAS.append(("code", texto.strip("\n")))


# ------------------------------------------------------------------------------------------------ abertura

md(r'''
# Quem são os clientes, quanto valem, quem vai parar de comprar e se o desconto muda de grupo para grupo

**Análise de clientes de varejo sobre o dataset público Dunnhumby "The Complete Journey"** (2.500 households, cerca de dois anos de compras, mais de 500 lojas).

Este notebook é a versão narrada das análises que o app (abas de análise) e o servidor MCP entregam. A regra do projeto é **nunca dois números para a mesma pergunta**:
por isso o notebook **não recalcula nada por conta própria**. Cada número vem das mesmas funções do núcleo (`segmentar_clientes`, `calcular_clv`, `prever_churn`,
`testar_desconto_entre_segmentos`) e das mesmas views do DuckDB que o chat e as abas usam. O que este documento acrescenta é o raciocínio: por que cada escolha foi feita,
o que ela custa e o que os dados **não** permitem afirmar.

**Como ler.** Cada seção abre com a decisão de negócio que a análise apoia, explica o método e as escolhas estatísticas, mostra os resultados e **fecha com o bloco "e daí?"**
(conclusão, ação recomendada, impacto estimado e limitações), o mesmo texto que abre cada aba do app. Os títulos dos gráficos dizem a conclusão.

**Para reproduzir.** O notebook lê `data/processed/dunnhumby.duckdb`, que não vai para o Git. Rode antes `venv\Scripts\python.exe baixar_dados.py` e `venv\Scripts\python.exe -m src.etl`
(cerca de 2 minutos). As saídas deste arquivo já vêm salvas, então ele pode ser lido sem rodar nada. A seção 8 lista versões, semente e comandos.
''')

code(r'''
import os
import sys
from pathlib import Path

raiz = Path.cwd() if (Path.cwd() / "config.yaml").exists() else Path.cwd().parent
sys.path.insert(0, str(raiz))
os.chdir(raiz)

import pandas as pd

from src import carga, notebook_apoio as na
from src.config import CFG
from src.ui import graficos

pd.set_option("display.max_columns", 40)
pd.set_option("display.width", 180)
pd.set_option("display.max_colwidth", 90)
cur = na.iniciar()
''')

code(r'''
# As quatro análises, pelas mesmas funções que o servidor MCP e o app usam. O resultado fica em cache por versão da base.
from src.nucleo.rfm import segmentar_clientes, coorte_retencao
from src.nucleo.clv import calcular_clv
from src.nucleo.churn import prever_churn
from src.nucleo.teste_desconto import testar_desconto_entre_segmentos

seg = segmentar_clientes()
coorte = coorte_retencao(cur)
clv = calcular_clv()
churn = prever_churn()
desc = testar_desconto_entre_segmentos()
assert all("erro" not in r for r in (seg, clv, churn, desc)), "alguma análise falhou"
versao = seg["versao_base"]
assert len({seg["versao_base"], clv["versao_base"], churn["versao_base"], desc["versao_base"]}) == 1
j = seg["janela"]
na.md(f"Base `{versao}` · janela atual: semanas {j['atual']['semanas'][0]} a {j['atual']['semanas'][1]} "
      f"({j['atual']['datas'][0]} a {j['atual']['datas'][1]}, datas arbitrárias) · base de comparação do ano anterior: semanas "
      f"{j['base']['semanas'][0]} a {j['base']['semanas'][1]} · semente {CFG['semente']}")
''')

md(r'''
## 0. Resumo executivo

As quatro análises formam **uma narrativa só, nesta ordem**: quem são os clientes (RFM), quanto cada grupo vale (CLV), o que vai acontecer com cada grupo (risco de pausa)
e por que os grupos se comportam de forma diferente no desconto (teste de hipótese). A tabela abaixo traz a decisão que cada uma apoia e a conclusão, no texto devolvido pela própria ferramenta.
''')

code(r'''
resumo = [("1. RFM + K-Means", "Quais clientes merecem tratamento diferente?", seg),
          ("2. CLV", "Quanto vale investir em cada grupo?", clv),
          ("3. Risco de pausa (churn)", "Quem abordar com reativação e quem deixar em paz?", churn),
          ("4. Teste de desconto", "A política de desconto deve variar por segmento?", desc)]
for nome, decisao, r in resumo:
    na.md(f"**{nome}**  \n*Decisão que apoia:* {decisao}  \n*Conclusão:* {r['e_dai']['conclusao']}")
''')

# ------------------------------------------------------------------------------------------------ 1. dados

md(r'''
## 1. Dados e qualidade

**Decisão que esta seção apoia:** posso confiar nos números que vêm depois? Antes de qualquer análise, a base passa por auditoria, limpeza documentada e reconciliação com o arquivo bruto.

### O dataset

| Tabela | O que é uma linha | Papel aqui |
|---|---|---|
| `transaction_data` | um item vendido numa cesta (household, loja, produto, dia, valor, descontos) | base de tudo |
| `product` | um produto (departamento, categoria, marca, fabricante) | dimensão de produto |
| `hh_demographic` | demografia de um household | opcional: só parte dos households tem |
| `campaign_desc`, `campaign_table`, `coupon`, `coupon_redempt` | campanhas, households-alvo, cupons e resgates | contexto de ações (chat) |
| `causal_data` | produto em display ou mailer por semana e loja | contexto de ações, agregado por semana e loja (36,8 milhões de linhas) |

**Decisões que valem para o resto do notebook**

- **Janela de análise:** as últimas 26 semanas de `WEEK_NO` que têm 7 dias completos. **Base de comparação:** as mesmas semanas um ano antes (`WEEK_NO - 52`), alinhadas por semana, só com lojas presentes nos dois períodos.
- **`SALES_VALUE` já é líquido** (depois de cupom e desconto de fidelidade). Os descontos (`RETAIL_DISC`, `COUPON_DISC`, `COUPON_MATCH_DISC`) vêm negativos e servem para decompor: o valor bruto é o líquido menos os descontos.
- **`DAY` é um inteiro relativo.** Foi convertido para data com uma data-base arbitrária: **feriados e sazonalidade por data não são confiáveis**; compara-se por semana alinhada.
- **Não existe vendedor individual.** A menor unidade de equipe é a loja.
- **Moeda: US$.** O dataset é americano.
''')

code(r'''
rel = carga.relatorio(raiz / CFG["banco"]["arquivo"])
arquivos = na.tabela(rel["arquivos"], {"tabela": "Tabela", "arquivo": "Arquivo", "tamanho_bytes": "MB", "md5": "MD5"})
arquivos["MB"] = (arquivos["MB"] / 1e6).round(1)
arquivos["MD5"] = arquivos["MD5"].str[:12]
na.md(f"Carga de {rel['data_carga'][:10]} · versão da base `{rel['versao_base']}` (hash dos arquivos + parâmetros do `config.yaml` + versão do ETL)")
arquivos
''')

md(r'''
### Limpeza: cada regra diz quantas linhas afetou e por quê

Nada de `fillna`/`dropna` em silêncio. Cada linha bruta cai **numa só regra**, pela ordem de precedência (valor não numérico, cesta ausente, chave ou data inválida, não-mercadoria, quantidade ≤ 0),
para que a soma das partes reconcilie com o total. Itens grátis (`SALES_VALUE = 0` com `QUANTITY > 0`) **ficam**: são itens reais.
''')

code(r'''
regras = na.tabela(rel["regras"], {"regra": "Regra", "descricao": "O que filtra", "linhas_afetadas": "Linhas afetadas (sem precedência)",
                                   "linhas_atribuidas": "Linhas atribuídas", "valor_atribuido_usd": "Valor atribuído (US$)"},
                   {"valor_atribuido_usd": 2})
regras[["Regra", "O que filtra", "Linhas afetadas (sem precedência)", "Linhas atribuídas", "Valor atribuído (US$)"]]
''')

code(r'''
rc = rel["reconciliacao"]
assert rc["ok"] and rc["linhas_brutas"] == rc["linhas_limpas"] + rc["linhas_ajustes"]
assert abs(rc["vendas_brutas_usd"] - rc["vendas_limpas_usd"] - rc["vendas_ajustes_usd"]) < 0.01
na.md(f"""**Reconciliação com o bruto.**  \n
- Linhas: {na.milhar(rc['linhas_brutas'])} brutas = **{na.milhar(rc['linhas_limpas'])}** em vendas limpas + **{na.milhar(rc['linhas_ajustes'])}** em ajustes (não-mercadoria e quantidade ≤ 0, guardadas à parte).
- Valor: {na.usd(rc['vendas_brutas_usd'])} brutos = {na.usd(rc['vendas_limpas_usd'])} limpos + {na.usd(rc['vendas_ajustes_usd'])} em ajustes.
- Por semana: **{rc['semanas_conferidas']} semanas conferidas, {rc['semanas_divergentes']} divergentes** (maior diferença semanal: {na.usd(rc['maior_diferenca_semanal_usd'], 2)}; tolerância {na.usd(rc['tolerancia_usd'], 2)}).""")
''')

code(r'''
# O que a auditoria procurou e o que encontrou. Tudo aqui vem do relatório de qualidade gerado pelo ETL.
conv = pd.DataFrame(rel["conversao_numerica"]).T[["ausentes", "nao_numericos", "arredondadas", "efeito_arredondamento_usd"]]
conv = conv[(conv != 0).any(axis=1)]
sem_demografia = cur.execute("SELECT COUNT(*) FILTER (WHERE NOT tem_demografia), COUNT(*) FROM dim_household").fetchone()
na.md(f"""- **Nulos:** {sum(rel['nulos_por_coluna'].values())} em todas as colunas de `transaction_data`. **Duplicados:** {sum(rel['duplicados'].values())} (chave de produto, órfãos, repetições na cesta e linhas idênticas).
- **Ruído de ponto flutuante no arquivo:** {int(conv.loc['SALES_VALUE', 'arredondadas'])} linhas de `SALES_VALUE` e {int(conv.loc['RETAIL_DISC', 'arredondadas'])} de `RETAIL_DISC` trazem valores como `5,55E-17`.
  Os valores monetários são lidos com **4 casas decimais**: com 2, a soma divergia US$ 0,10 do CSV. O efeito do arredondamento que sobra é de {na.usd(abs(conv['efeito_arredondamento_usd'].sum()), 4)}.
- **Casos mantidos de propósito:** {na.milhar(rel['casos_mantidos']['itens_gratis_sales_zero_qtd_positiva'])} itens grátis e {rel['casos_mantidos']['retail_disc_positivo_estorno']} linhas de desconto de loja positivo (estorno).
- **Households sem demografia:** {na.milhar(sem_demografia[0])} de {na.milhar(sem_demografia[1])} ({na.pt(100 * sem_demografia[0] / sem_demografia[1], 0)}%). Por isso nenhuma análise usa demografia.""")
pd.DataFrame(rel["joins"]).rename(columns={"join": "Junção", "antes": "Linhas antes", "depois": "Linhas depois", "ok": "Sem multiplicar linhas?"})
''')

code(r'''
na.e_dai({
    "conclusao": (f"A base reconcilia com o arquivo bruto ao centavo, semana a semana ({rc['semanas_conferidas']} semanas, {rc['semanas_divergentes']} divergentes), sem nulos, "
                  f"sem duplicados e sem junção que multiplique linhas. {na.milhar(rc['linhas_ajustes'])} linhas ({na.pt(100 * rc['linhas_ajustes'] / rc['linhas_brutas'])}%) ficam fora das vendas, com motivo e valor."),
    "acao_recomendada": "Usar a base como está. Quem trouxer outra exportação do BI deve rodar o ETL e conferir a reconciliação antes de olhar qualquer número.",
    "impacto_estimado": (f"As linhas fora das vendas somam {na.usd(rc['vendas_ajustes_usd'])} ({na.pt(100 * rc['vendas_ajustes_usd'] / rc['vendas_brutas_usd'])}% do valor bruto), "
                         "quase todo combustível e pseudo-itens de cupom: incluí-las inflaria ticket e faturamento."),
    "limitacoes": ("É um painel de 2.500 households, não o cliente médio do varejista; só parte tem demografia; as datas reais são arbitrárias; "
                   "não há devolução registrada, então 'valor líquido ≤ 0' nunca ocorre; o período é histórico e as datas reais são arbitrárias."),
})
''')

# ------------------------------------------------------------------------------------------------ 2. métricas

md(r'''
## 2. Métricas: definidas uma vez, conferidas por um segundo caminho

**Decisão que esta seção apoia:** o chat, as abas e este notebook dão o mesmo número para a mesma pergunta? Cada métrica é uma **view do DuckDB**, com a definição de negócio guardada na
tabela `metricas_definicao`. Nenhuma outra parte do projeto recalcula faturamento, ticket ou desconto por conta própria.
''')

code(r'''
metricas = cur.execute("SELECT metrica AS Métrica, definicao AS Definição, formula AS Fórmula, view_origem AS View FROM metricas_definicao").df()
metricas
''')

md(r'''
### Sanity check de ordem de grandeza e segundo caminho

Antes de mostrar qualquer número, confere-se (1) a **ordem de grandeza** de negócio (ticket de supermercado na casa de dezenas de dólares, itens por cesta na casa de dezenas, desconto na casa de 15%) e
(2) o resultado por um **caminho independente**: o mesmo número recalculado direto da tabela de fatos, sem passar pelas views de métricas.
''')

code(r'''
via_view = cur.execute("""SELECT SUM(faturamento) / COUNT(*) AS ticket, SUM(itens) / COUNT(*) AS itens_por_cesta,
                                 100.0 * SUM(desconto_total) / SUM(valor_bruto) AS pct_desconto, SUM(faturamento) AS faturamento
                          FROM vw_metricas_cesta WHERE periodo = 'atual'""").fetchone()
ini, fim = cur.execute("SELECT semana_ini_atual, semana_fim_atual FROM vw_janela").fetchone()
direto = cur.execute("""SELECT SUM(f.SALES_VALUE) / COUNT(DISTINCT f.BASKET_ID) AS ticket,
                               -100.0 * SUM(f.RETAIL_DISC + f.COUPON_DISC + f.COUPON_MATCH_DISC) /
                                 (SUM(f.SALES_VALUE) - SUM(f.RETAIL_DISC + f.COUPON_DISC + f.COUPON_MATCH_DISC)) AS pct_desconto,
                               SUM(f.SALES_VALUE) AS faturamento
                        FROM fato_transacoes f JOIN dim_data d ON d.data_id = f.data_id WHERE d.WEEK_NO BETWEEN ? AND ?""", [ini, fim]).fetchone()
conferencia = pd.DataFrame({"Métrica": ["Ticket médio (US$)", "% de desconto sobre o valor bruto", "Faturamento da janela (US$)"],
                            "Pela view": [via_view[0], via_view[2], via_view[3]], "Direto da tabela de fatos": [direto[0], direto[1], direto[2]]})
conferencia["Diferença"] = (conferencia["Pela view"].astype(float) - conferencia["Direto da tabela de fatos"].astype(float)).round(4)
assert conferencia["Diferença"].abs().max() < 0.01, "view e cálculo direto divergem"
assert 15 < float(via_view[0]) < 60 and 5 < float(via_view[1]) < 30 and 5 < float(via_view[2]) < 30
conferencia.round(4)
''')

code(r'''
yoy = cur.execute("SELECT * FROM vw_yoy_resumo").df()
y = yoy.iloc[0]
na.md(f"**Contra o ano anterior (mesmas semanas, só as {int(y['lojas_like_for_like'])} lojas presentes nos dois períodos, que fazem {na.pt(y['pct_vendas_atual_em_lfl'])}% das vendas atuais):** "
      f"faturamento {na.pt(y['var_faturamento_pct'])}%, clientes {na.pt(y['var_clientes_pct'])}%, idas por cliente {na.pt(y['var_idas_por_cliente_pct'])}% e ticket {na.pt(y['var_ticket_pct'])}%. "
      "O faturamento sobe porque o ticket cresce mais do que as idas por cliente caem. "
      f"{int(y['lojas_lfl_amostra_pequena'])} dessas lojas têm menos de 100 cestas na janela (`amostra_pequena`): o painel é pequeno, então variações por loja ou categoria pequena são instáveis.")
yoy.round(3)
''')

code(r'''
na.e_dai({
    "conclusao": (f"As métricas batem entre a view e o cálculo direto (diferença máxima {conferencia['Diferença'].abs().max():.4f}) e ficam na ordem de grandeza certa: "
                  f"ticket de {na.usd(float(via_view[0]), 2)}, {na.pt(float(via_view[1]))} itens por cesta e {na.pt(float(via_view[2]))}% de desconto sobre o valor bruto."),
    "acao_recomendada": "Tratar as views como a única fonte de métrica: qualquer relatório novo deve consultá-las, não recalcular a fórmula.",
    "impacto_estimado": f"Faturamento da janela de {na.usd(float(via_view[3]))} e variação de {na.pt(y['var_faturamento_pct'])}% contra o ano anterior nas mesmas lojas.",
    "limitacoes": ("A comparação com o ano anterior usa só as lojas presentes nos dois períodos; o crescimento de todas as lojas inclui lojas que não existem nos dois. "
                   "O % de desconto é soma do desconto sobre soma do valor bruto, nunca média de percentuais."),
})
''')

# ------------------------------------------------------------------------------------------------ 3. RFM

md(r'''
## 3. RFM + K-Means: quem são os clientes

**Decisão que esta seção apoia:** quais clientes merecem tratamento diferente (fidelizar, reativar, deixar em paz) e quais não?

**Critério escrito antes de rodar.** Clientes de varejo raramente formam grupos naturalmente separados; é comum haver um contínuo, com poucos clientes de alto valor e uma cauda longa. Por isso o que decide se
os grupos valem a pena é se eles são **estáveis** (aparecem de novo com outras sementes e outras amostras), e não se são bonitos num gráfico. A regra de escolha do K, abaixo, foi fixada antes de olhar os resultados.

### Método e escolhas estatísticas

- **Variáveis.** **R**ecência (dias desde a última compra até o fim da janela), **F**requência (número de cestas) e **V**alor (faturamento líquido na janela). Frequência e valor entram em **`log1p`**,
  porque têm cauda longa: sem a transformação, poucos clientes enormes decidiriam sozinhos onde ficam os centros dos grupos. Depois, tudo é **padronizado** (média 0, desvio 1), para nenhuma variável pesar mais só pela unidade.
- **Quem entra.** Households com compra na janela atual. Os que não compraram nada na janela **ficam fora** da segmentação (são contados, e voltam como grupo próprio no CLV). Households com valor líquido ≤ 0 também sairiam, com a contagem registrada.
- **K-Means** com semente fixa e várias inicializações. A consulta ordena por `household_key`: o K-Means depende da ordem das linhas, e sem isso o resultado mudaria de uma execução para outra.
- **Como o K é escolhido: uma regra escrita antes de rodar** (parâmetros em `config.yaml`, seção `analises.rfm`), nunca um controle deslizante e nunca "o que ficou bonito":
  1. **K ≥ 3.** K=2 costuma ter a maior silhueta, mas só separa quem comprou há pouco de quem não comprou, o que a recência já diz.
  2. **Estabilidade:** índice de Rand ajustado (ARI) mínimo de 0,90 entre sementes diferentes **e** entre subamostras de 80% dos clientes.
  3. **Nenhum segmento com menos de 5%** dos households.
  4. **Silhueta ≥ 0,25**, para haver estrutura minimamente visível.
  5. Entre os K que passam em tudo, **vence a maior silhueta**.
- **Nomes dos segmentos** vêm do perfil real de cada grupo (recência média acima de 56 dias = "Em pausa"; os demais, por valor médio), nunca de uma lista fixa por ordem do cluster.
''')

code(r'''
cfg_rfm = CFG["analises"]["rfm"]
avaliacao = graficos.tabela_k(seg["avaliacao_k"], seg["k_usado"], cfg_rfm)
na.md(f"**Regra aplicada.** {seg['metodo_escolha_k']}")
avaliacao.drop(columns=["tamanhos"]).rename(columns={
    "k": "K", "silhueta": "Silhueta", "inercia": "Inércia (cotovelo)", "ari_sementes_min": "ARI mín. (sementes)", "ari_sementes_mediana": "ARI mediana (sementes)",
    "ari_subamostras_min": "ARI mín. (subamostras)", "ari_subamostras_mediana": "ARI mediana (subamostras)", "menor_segmento_pct": "Menor segmento (%)",
    "passou_na_regra": "Passou na regra?", "estado": "Resultado"}).round(3)
''')

code(r'''
na.grafico(graficos.grafico_k(seg["avaliacao_k"], seg["k_usado"], cfg_rfm, na.MODO))
''')

code(r'''
est = seg["estabilidade"]
na.md(f"**Estabilidade do K = {seg['k_usado']}:** ARI mínimo de {na.pt(est['ari_sementes_min'], 3)} entre {est['sementes']} sementes e de {na.pt(est['ari_subamostras_min'], 3)} entre "
      f"{est['subamostras']} subamostras de {int(est['fracao_subamostra'] * 100)}% dos clientes (1 = os mesmos grupos). A silhueta é {na.pt(seg['silhueta'], 2)}: "
      "há estrutura, mas **moderada**. Os segmentos são uma divisão útil de um contínuo, não ilhas separadas.")
perfil = na.tabela(seg["segmentos"], {"nome": "Segmento", "households": "Households", "pct_households": "% dos households", "recencia_media_dias": "Recência média (dias)",
                                      "frequencia_media": "Compras (média)", "valor_medio_usd": "Valor médio (US$)", "ticket_medio_usd": "Ticket médio (US$)",
                                      "pct_faturamento": "% do faturamento", "desconto_medio_pct": "Desconto (% do bruto)"},
                   {"pct_households": 1, "recencia_media_dias": 0, "frequencia_media": 1, "valor_medio_usd": 0, "ticket_medio_usd": 2, "pct_faturamento": 1, "desconto_medio_pct": 1})
perfil[["Segmento", "Households", "% dos households", "Recência média (dias)", "Compras (média)", "Valor médio (US$)", "Ticket médio (US$)", "% do faturamento", "Desconto (% do bruto)"]]
''')

code(r'''
na.grafico(graficos.grafico_segmentos(seg["segmentos"], na.MODO))
''')

md(r'''
### Households que ficam fora e retenção por coorte (análise de apoio)

A **coorte** é um apoio ao RFM, não um pilar: mostra se quem entrou no painel em momentos diferentes se comporta de forma parecida. Blocos de 4 semanas, coortes com menos de 30 households omitidas.
Ressalva importante: **entrada no painel não é cliente novo**. Quase todos os households aparecem nas primeiras 20 semanas do arquivo, então "coorte" aqui descreve a entrada no painel, não a aquisição de clientes.
''')

code(r'''
na.md("**Fora da segmentação:** " + "; ".join(f"{na.milhar(e['households'])} households — {e['motivo']}" for e in seg["excluidos"]) + ".")
na.grafico(graficos.grafico_coorte(coorte["coortes"], na.MODO))
na.md(f"*{coorte['limitacao']}*")
''')

code(r'''
na.e_dai(seg["e_dai"])
''')
