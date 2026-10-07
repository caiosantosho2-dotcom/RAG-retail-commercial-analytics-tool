"""Seções 4 a 8 do notebook: CLV, risco de pausa, teste de desconto, costura final e reprodutibilidade. Cada item é (tipo, texto).
O texto de método é fixo; todo número do resultado é preenchido por código a partir das ferramentas do núcleo."""

CELULAS = []


def md(texto):
    CELULAS.append(("md", texto.strip("\n")))


def code(texto):
    CELULAS.append(("code", texto.strip("\n")))


# ------------------------------------------------------------------------------------------------ 4. CLV

md(r'''
## 4. CLV: quanto vale cada grupo

**Decisão que esta seção apoia:** quanto vale investir em cada grupo de clientes (fidelização, reativação), e onde o dinheiro de retenção rende mais?

### Método e premissas

O dataset não traz custo, então o "valor do cliente" aqui é **margem esperada nas próximas 52 semanas**, com premissas explícitas:

- **Gasto esperado.** Para cada household, o gasto médio das últimas 26 semanas vezes uma **razão futuro/passado**: quanto os clientes *do mesmo segmento* gastaram nas 52 semanas seguintes, comparado com as 26 anteriores,
  **um ano antes** (a coorte da janela-base, segmentada com o mesmo K e as mesmas regras de nome). Multiplicar o passado por 2 seria ingênuo: grupos de gasto baixo numa janela tendem a voltar ao seu nível normal
  (**regressão à média**), e grupos de gasto alto tendem a cair um pouco.
- **Margem de 25% é premissa**, não dado. O CLV escala linearmente com ela: com 20%, todos os valores caem 20%.
- **Households sem compra na janela** formam um grupo próprio ("Sem compra na janela"), estimado direto pelo que os households *análogos* gastaram depois, um ano antes. Sem isso o total ignoraria quem parou de comprar e depois voltou.
- **Intervalo de confiança de 95% por bootstrap de households** (2.000 reamostras, semente fixa), nas duas coortes. Ele mede só a variação entre households: **não** cobre a incerteza da margem nem a escolha dos segmentos.
- **Sem desconto financeiro** (taxa de juros): num horizonte de um ano ele mudaria pouco o ranking dos grupos.
- **Validação por backtest de 26 semanas:** calibra em um período, segmenta o seguinte e prevê o terceiro, que já foi observado. O horizonte de **52 semanas não tem backtest**: só existe uma transição anual observável.
''')

code(r'''
prem = clv["premissas"]
na.md(f"**Premissas desta execução.** Método: {prem['metodo']}. Horizonte de {prem['horizonte_semanas']} semanas; margem de {prem['margem'] * 100:.0f}% (**premissa**: o dataset não tem custo). "
      f"Janela atual: {prem['janela_atual']}; calibração (um ano antes): {prem['janela_calibracao']}; semanas futuras observadas na calibração: {prem['semanas_futuras_observadas']}. "
      f"Bootstrap: {prem['bootstrap']['reamostras']} reamostras, nível de {prem['bootstrap']['nivel'] * 100:.0f}%, semente {prem['bootstrap']['semente']}. {prem['grupo_sem_compra']}.")
tab = pd.DataFrame([{"Grupo": s["nome"], "Households": s["n"], "Gasto médio nas 26 semanas (US$)": s["valor_medio_janela_usd"],
                     "Razão futuro/passado": s["razao_futuro_passado"], "CLV por household (US$)": s["clv_medio"],
                     "IC 95% (US$)": f"{na.milhar(s['ic_95'][0])} a {na.milhar(s['ic_95'][1])}", "Receita esperada (US$)": s["receita_esperada_usd"],
                     "Margem esperada do grupo (US$)": s["clv_total_usd"]} for s in clv["segmentos"]])
tab.round({"Gasto médio nas 26 semanas (US$)": 0, "Razão futuro/passado": 2, "CLV por household (US$)": 0, "Receita esperada (US$)": 0, "Margem esperada do grupo (US$)": 0})
''')

code(r'''
na.grafico(graficos.grafico_clv(clv["segmentos"], na.MODO))
''')

md(r'''
### Por que os grupos de menor gasto valem mais do que o gasto passado sugere

A **razão futuro/passado** é o motor do método. Um ritmo de 1 significaria gastar nas próximas 52 semanas o mesmo ritmo das últimas 26. Os grupos de gasto baixo ficam acima disso: parte do gasto baixo numa janela
é acaso de calendário (quem comprou pouco *nessas* 26 semanas), não saída do cliente.
''')

code(r'''
com_ritmo = [s for s in clv["segmentos"] if s.get("ritmo_relativo") is not None]
na.grafico(graficos.grafico_ritmo(com_ritmo, na.MODO))
''')

md(r'''
### O método acerta? Backtest em 26 semanas

Aqui o futuro já aconteceu, então dá para comparar o previsto com o real e com uma **regra ingênua** ("repetir o último período"). Se o método não ganhasse da regra ingênua, o achado seria esse.
''')

code(r'''
bt = clv["backtest"]
na.md(f"**Calibração:** {bt['calibracao']}. **Teste:** {bt['teste']}. No total, o método errou **{na.pt(abs(bt['total']['erro_metodo_pct']))}%** (a regra ingênua, {na.pt(abs(bt['total']['erro_ingenuo_pct']))}%) e ganhou em "
      f"**{bt['segmentos_em_que_o_metodo_ganha']} de {bt['segmentos_avaliados']}** grupos. **Por household**, porém, o erro absoluto médio do método é {na.usd(bt['mae_household_metodo_usd'])} contra "
      f"{na.usd(bt['mae_household_ingenuo_usd'])} da regra ingênua: **o CLV serve como média de grupo, não como previsão de um cliente.**")
na.grafico(graficos.grafico_backtest(bt, na.MODO))
''')

code(r'''
na.e_dai(clv["e_dai"])
''')

# ------------------------------------------------------------------------------------------------ 5. churn

md(r'''
## 5. Risco de pausa ("churn"): quem vai parar de comprar

**Decisão que esta seção apoia:** quem abordar com uma ação de reativação e quem deixar em paz? Contato custa dinheiro e incomoda cliente que ia comprar de qualquer jeito.

### O que é "churn" aqui, e por que o nome engana

Varejo de supermercado **não tem contrato de cancelamento**: o cliente simplesmente deixa de aparecer. O corte tem de ser escolhido e justificado. Aqui, **churn é pausa longa: ficar 8 semanas sem comprar**.
Oito semanas (56 dias) é o mesmo limite que define "cliente ativo" e o grupo "Em pausa", e fica acima do intervalo habitual entre compras destes clientes (medido logo abaixo).

Mas a palavra "churn" sugere perda definitiva, e os dados dizem o contrário: **a maioria de quem pausa volta** (números abaixo). Por isso o texto fala em *pausa*, e a ação recomendada é *priorizar* contato, não "salvar clientes perdidos".

### Como o modelo é validado

- **Split temporal, nunca sorteio de linhas.** Um sorteio aleatório mistura semanas e deixa o modelo "ver o futuro" (o comportamento de um household na semana 80 ajuda a prever sua pausa na semana 78). O modelo treina em fotos antigas,
  o limiar de decisão é escolhido numa foto seguinte e a avaliação final usa duas fotos mais recentes, **com janelas de rótulo que não se sobrepõem**.
- **População de cada foto:** quem comprou nas últimas 8 semanas e tem pelo menos 16 semanas de histórico. Quem já está em pausa fica de fora (já aconteceu, não há o que prever) e é contado à parte.
- **Variáveis só com informação até a foto:** semanas desde a última compra, compras nas últimas 8 semanas (log), gasto nas últimas 26 semanas (log), semanas com compra nas últimas 26 e a maior pausa seguida nas últimas 26.
- **Regressão logística** padronizada e regularizada: interpretável, com poucos coeficientes cujo sinal precisa fazer sentido de negócio. O sinal de cada um é conferido contra a intuição, e **cinco variáveis em vez de dez**:
  com as dez, as variáveis eram quase colineares e "compras em 26 semanas" ganhava sinal contrário ao esperado, um artefato; com cinco, o poder de previsão é o mesmo e os sinais fazem sentido.
- **Contra uma regra simples:** "sem compra há k semanas ou mais = vai pausar", com k escolhido no treino. Se o modelo não ganhasse da regra, o achado seria esse.
- **Limiar de alerta** escolhido pelo maior F1 na foto de validação, e **intervalo de confiança** da diferença de AUC por bootstrap **de households** (o mesmo household aparece em mais de uma foto).
''')

code(r'''
ret = churn["retorno_apos_pausa"]
pausa = churn["ja_em_pausa"]
p95, p99 = cur.execute("""WITH g AS (SELECT WEEK_NO - LAG(WEEK_NO) OVER (PARTITION BY household_key ORDER BY WEEK_NO) AS intervalo FROM vw_cliente_semana)
                          SELECT quantile_cont(intervalo, 0.95), quantile_cont(intervalo, 0.99) FROM g WHERE intervalo IS NOT NULL""").fetchone()
na.md(f"**Por que 8 semanas.** O intervalo entre duas semanas com compra do mesmo household tem p95 de {na.pt(p95, 0)} semanas e p99 de {na.pt(p99, 0)}: oito semanas fica acima do que quase todos fazem "
      "entre uma compra e outra, sem ser tão longo a ponto de só pegar quem já saiu.")
na.md(f"**Pausa não é saída.** Das {na.milhar(ret['pausas_observadas'])} pausas observadas nas fotos, **{na.pt(ret['taxa_pct'], 0)}% voltaram a comprar em até {ret['janela_semanas']} semanas** "
      f"(entre {na.pt(ret['minimo_por_foto_pct'], 0)}% e {na.pt(ret['maximo_por_foto_pct'], 0)}% conforme a foto). **Definição usada:** {churn['definicao_churn']}")
na.md(f"**Fora da previsão:** {na.milhar(pausa['households'])} households já estão em pausa hoje ("
      + ", ".join(f"{k}: {na.milhar(v)}" for k, v in pausa["por_segmento"].items()) + ").")
''')

code(r'''
import numpy as np
from statsmodels.stats.outliers_influence import variance_inflation_factor
from src.nucleo import churn as nucleo_churn

fim = seg["janela"]["atual"]["semanas"][1]
plano = nucleo_churn.fotos_do_plano(fim)
painel = nucleo_churn.carregar_painel(cur, fim)
h = CFG["analises"]["churn"]["horizonte_semanas"]
na.md(f"**Plano de fotos (semanas):** treino {plano['treino'][0]} a {plano['treino'][-1]} a cada {CFG['analises']['churn']['treino_passo_semanas']} (rótulos até a semana {plano['treino'][-1] + h}); "
      f"validação {plano['validacao']} (rótulos {plano['validacao'] + 1} a {plano['validacao'] + h}); teste {plano['teste'][0]} e {plano['teste'][1]} "
      f"(rótulos {plano['teste'][0] + 1} a {plano['teste'][0] + h} e {plano['teste'][1] + 1} a {plano['teste'][1] + h}). Nenhum rótulo se sobrepõe à foto seguinte; o código recusa um plano que se sobreponha.")
X = np.vstack([nucleo_churn.fotografar(painel, T, com_rotulo=False)[0] for T in plano["treino"]])
Xz = np.column_stack([np.ones(len(X)), (X - X.mean(axis=0)) / X.std(axis=0)])
vif = pd.DataFrame({"Variável": [nucleo_churn.LEITURA[v] for v in nucleo_churn.VARIAVEIS],
                    "VIF": [variance_inflation_factor(Xz, i + 1) for i in range(X.shape[1])]}).round(1)
na.md(f"**Colinearidade entre as {len(nucleo_churn.VARIAVEIS)} variáveis (VIF nas {na.milhar(len(X))} linhas de treino).** Valores acima de 5 a 10 indicam variáveis que se explicam entre si; aqui o maior é {na.pt(vif['VIF'].max(), 1)}. "
      "Há colinearidade residual: o coeficiente de cada variável deve ser lido como o da variável dominante do grupo, e o conjunto, como associação, não como causa.")
vif
''')

md(r'''
### O modelo ganha da regra simples?
''')

code(r'''
m, b = churn["modelo"], churn["baseline"]
comparacao = pd.DataFrame({"Medida": ["AUC", "AUC-PR (a prevalência é pequena)", "Precisão (alertas que se confirmam)", "Recall (pausas que o alerta pega)", "F1", "Alertas disparados"],
                           "Modelo": [m["auc"], m["auc_pr"], m["precisao"], m["recall"], m["f1"], m["alertas"]],
                           "Regra simples": [b["auc"], b["auc_pr"], b["precisao"], b["recall"], b["f1"], b["alertas"]]}).round(3)
lo, hi = churn["diferenca_auc_ic"]
mc = churn["matriz_confusao"]
na.md(f"{churn['baseline_descricao']}. **Prevalência de pausas no teste: {na.pt(churn['prevalencia_pct']['teste'])}%** (por isso a acurácia seria enganosa: um modelo que nunca alerta acertaria {na.pt(100 - churn['prevalencia_pct']['teste'])}%). "
      f"A diferença de AUC é de **{na.pt(churn['diferenca_auc'], 3)}** (IC de 95% por household: {na.pt(lo, 3)} a {na.pt(hi, 3)}), com o limiar {na.pt(churn['limiar'], 2)} escolhido na validação. "
      f"Matriz de confusão do modelo no teste: {na.milhar(mc['modelo']['tp'])} verdadeiros positivos, {na.milhar(mc['modelo']['fp'])} falsos positivos, {na.milhar(mc['modelo']['fn'])} falsos negativos e {na.milhar(mc['modelo']['tn'])} verdadeiros negativos.")
comparacao
''')

code(r'''
na.grafico(graficos.grafico_limiar(churn["curva_limiar"], na.MODO))
''')

md(r'''
### As probabilidades são confiáveis? E o que pesa no risco?

A **calibração** compara o risco previsto com a frequência observada por decil de risco: se o modelo diz 30%, tem de acontecer em cerca de 30% dos casos, senão a probabilidade não serve para calcular quanto dinheiro está em jogo.
Os **fatores** são odds ratios por desvio-padrão: abaixo de 1 reduzem o risco, acima de 1 aumentam. São **associação, não causa**.
''')

code(r'''
na.grafico(graficos.grafico_calibracao(churn["calibracao"], na.MODO))
na.grafico(graficos.grafico_fatores(churn["principais_fatores"], na.MODO))
''')

md(r'''
### Onde estão as pausas, e onde está o dinheiro

O risco se concentra em quem compra pouco. Mas o **valor em risco** (risco × gasto semanal × 8 semanas) pesa o quanto cada cliente gasta, e isso muda quem é a prioridade.
''')

code(r'''
risco = graficos.tabela_risco(churn["risco_por_segmento"])
na.grafico(graficos.grafico_risco(churn["risco_por_segmento"], churn["horizonte_semanas"], na.MODO))
risco.rename(columns={"segmento": "Segmento", "households": "Households", "risco_medio_pct": "Risco médio (%)", "pausas_esperadas": "Pausas esperadas",
                      "pct_das_pausas": "% das pausas", "alertas": "Em alerta hoje", "valor_em_risco_usd": "Valor em risco (US$)",
                      "pct_do_valor_em_risco": "% do valor em risco"}).round(1)
''')

code(r'''
na.e_dai(churn["e_dai"])
''')

# ------------------------------------------------------------------------------------------------ 6. desconto

md(r'''
## 6. Teste de hipótese: o desconto muda de um segmento para outro?

**Decisão que esta seção apoia:** a política de desconto deve variar por segmento? Se os grupos recebem descontos muito diferentes, vale perguntar por quê; se recebem o mesmo, não há o que ajustar por grupo.

**Hipótese escrita antes de rodar:** os segmentos recebem desconto **parecido**. O desconto vem sobretudo do cartão de fidelidade e de cupons, que são generalistas.

### Método e escolhas estatísticas

- **Variável:** % de desconto de cada household na janela atual = 100 × soma do desconto ÷ soma do valor bruto (a mesma definição das views). Os quatro segmentos do RFM são os grupos.
- **Teste não paramétrico.** O teste de Shapiro-Wilk, por grupo, mostra se o % de desconto é normal. Se não for, ANOVA não se justifica e usa-se **Kruskal-Wallis**, que compara as distribuições sem supor normalidade.
- **Post-hoc só se o teste geral for significativo:** Mann-Whitney par a par com **correção de Holm** para as seis comparações (sem a correção, a chance de um falso positivo em seis testes passa de 26%).
- **Significância não basta.** Com mais de 2.400 households, quase qualquer diferença vira "significativa". Por isso o veredito exige também **tamanho de efeito** (eta² do Kruskal-Wallis) e a diferença de medianas com
  **intervalo de confiança por bootstrap**. Regra escrita antes de rodar (`analises.teste_desconto` no `config.yaml`): *relevante* se eta² ≥ 1% **ou** se algum par tem diferença de medianas ≥ 1 ponto percentual com IC que exclui zero;
  *desprezível* se é significativo mas não passa disso; *sem diferença detectável* se p ≥ 0,05.
- **Sensibilidade.** O % de desconto de quem comprou poucas vezes vem de poucas cestas e varia muito. O teste é repetido **só com households de 5 ou mais compras**: se o veredito mudar, o resultado depende desse ruído.
- As funções do teste (normalidade, Kruskal-Wallis, post-hoc) são genéricas (recebem os nomes das colunas) e ficam em `src/teste_hipotese.py`; um teste confere o código-fonte delas. O que é específico deste projeto é só a preparação dos dados.
''')

code(r'''
VEREDITO = {"sem_diferenca_detectavel": "sem diferença detectável", "diferenca_desprezivel": "diferença desprezível", "diferenca_relevante": "diferença relevante"}
norm = na.tabela(desc["normalidade_por_grupo"], {"segmento": "Segmento", "n": "Households", "shapiro_p_valor": "p-valor (Shapiro-Wilk)", "normal_a_5pct": "Normal a 5%?"})
na.md(f"**Normalidade:** {int((~norm['Normal a 5%?']).sum())} dos {len(norm)} grupos rejeitam a normalidade, então o teste não paramétrico se justifica.")
norm
''')

code(r'''
na.grafico(graficos.grafico_distribuicao(desc["grupos"], desc["veredito"], desc["impacto"]["taxa_geral_pct"], na.MODO))
''')

code(r'''
kw = desc["kruskal_wallis"]
na.md(f"**Kruskal-Wallis:** H = {na.pt(kw['estatistica_H'], 2)}, p = {na.pt(kw['p_valor'], 4)}, **eta² = {na.pt(kw['eta_quadrado_aprox'], 4)}** ({na.pt(100 * kw['eta_quadrado_aprox'], 1)}% da variação), "
      f"{kw['n_grupos_testados']} grupos e {na.milhar(kw['n_total_observacoes'])} households. **Veredito pela regra escrita antes:** {VEREDITO[desc['veredito']]}.")
if desc["post_hoc_executado"]:
    ph = na.tabela(desc["post_hoc"], {"grupo_1": "Grupo 1", "grupo_2": "Grupo 2", "mediana_1": "Mediana 1 (%)", "mediana_2": "Mediana 2 (%)", "p_valor_bruto": "p bruto",
                                      "p_valor_ajustado": "p ajustado (Holm)", "significativo_5pct": "Significativo a 5%?"})
    na.md("**Comparações par a par (Mann-Whitney com correção de Holm)** — o teste geral foi significativo, então o post-hoc roda:")
else:
    ph = None
    na.md(f"Post-hoc não executado: {desc['post_hoc_motivo']}.")
ph.round({"p bruto": 4}) if ph is not None else None
''')

code(r'''
na.grafico(graficos.grafico_pares(desc["ic_diferencas"], CFG["analises"]["teste_desconto"]["diferenca_relevante_pp"], na.MODO))
''')

md(r'''
### O resultado depende de quem comprou pouco?
''')

code(r'''
s = desc["sensibilidade"]
na.md(f"Com {na.milhar(s['households'])} households de {s['minimo_compras']} ou mais compras (de {na.milhar(desc['households'])}): p = {na.pt(s['kruskal_wallis']['p_valor'], 4)}, "
      f"eta² = {na.pt(max(0.0, s['kruskal_wallis']['eta_quadrado_aprox']), 4)}, veredito **{VEREDITO[s['veredito']]}**. "
      "Quando a significância some ao tirar o ruído de poucas cestas, a diferença do teste completo não é uma política diferente por segmento.")
na.grafico(graficos.grafico_sensibilidade(desc["grupos"], s["grupos"], s["minimo_compras"], s["kruskal_wallis"]["p_valor"], s["veredito"], na.MODO))
''')

code(r'''
na.e_dai(desc["e_dai"])
''')

# ------------------------------------------------------------------------------------------------ 7. costura

md(r'''
## 7. Costura: a narrativa das quatro análises

As quatro análises respondem perguntas em sequência: **quem são** (RFM), **quanto valem** (CLV), **o que vai acontecer** (risco de pausa) e **por que diferem** (desconto). A tabela junta o que cada uma diz sobre cada segmento.
Células vazias são esperadas: "Em pausa" e "Sem compra" já pausaram, então não entram na previsão de pausa; "Sem compra na janela" não é segmento do RFM.
''')

code(r'''
base = pd.DataFrame({"Segmento": [s["nome"] for s in seg["segmentos"]] + ["Sem compra na janela"]})
rfm_ = pd.DataFrame([{"Segmento": s["nome"], "Households": s["households"], "% do faturamento": s["pct_faturamento"]} for s in seg["segmentos"]])
clv_ = pd.DataFrame([{"Segmento": s["nome"], "CLV por household (US$)": s["clv_medio"], "Margem esperada (US$)": s["clv_total_usd"]} for s in clv["segmentos"]])
risco_ = pd.DataFrame([{"Segmento": s["nome"], "Risco de pausa em 8 semanas (%)": s["risco_medio_pct"], "Valor em risco (US$)": s["valor_em_risco_usd"]} for s in churn["risco_por_segmento"]])
desc_ = pd.DataFrame([{"Segmento": g["segmento"], "Mediana de desconto (%)": g["mediana_pct"], "Taxa ponderada (%)": g["taxa_ponderada_pct"]} for g in desc["grupos"]])
costura = base
for parte in (rfm_, clv_, risco_, desc_):
    costura = costura.merge(parte, on="Segmento", how="left")
casas = {"Households": 0, "% do faturamento": 1, "CLV por household (US$)": 0, "Margem esperada (US$)": 0, "Risco de pausa em 8 semanas (%)": 1,
         "Valor em risco (US$)": 0, "Mediana de desconto (%)": 1, "Taxa ponderada (%)": 1}
costura = costura.astype(object)
for coluna, n in casas.items():
    costura[coluna] = costura[coluna].map(lambda v: "" if pd.isna(v) else (int(round(v)) if n == 0 else round(float(v), n)))
costura
''')

code(r'''
fieis, regulares, esporadicos = seg["segmentos"][0], seg["segmentos"][1], seg["segmentos"][2]
r_por = {s["nome"]: s for s in churn["risco_por_segmento"]}
clv_por = {s["nome"]: s for s in clv["segmentos"]}
total_vr = sum(s["valor_em_risco_usd"] for s in churn["risco_por_segmento"])
na.md(f"""**O que as quatro análises dizem juntas**

1. **Poucos clientes carregam o negócio.** Os {fieis['nome']} são {na.pt(fieis['pct_households'], 0)}% dos households e fazem {na.pt(fieis['pct_faturamento'], 0)}% do faturamento; cada um vale cerca de {na.usd(clv_por[fieis['nome']]['clv_medio'])} de margem esperada em 52 semanas.
2. **O risco de pausa está onde o cliente vale menos; o dinheiro em risco está no meio.** Os {esporadicos['nome']} têm {na.pt(r_por[esporadicos['nome']]['risco_medio_pct'], 1)}% de risco, mas os {regulares['nome']} concentram
   {na.pt(100 * r_por[regulares['nome']]['valor_em_risco_usd'] / total_vr, 0)}% do valor em risco ({na.usd(r_por[regulares['nome']]['valor_em_risco_usd'])} em 8 semanas), porque são muitos e gastam bem mais.
3. **A maioria das pausas é temporária** ({na.pt(churn['retorno_apos_pausa']['taxa_pct'], 0)}% voltam em {churn['retorno_apos_pausa']['janela_semanas']} semanas): reativação deve ser barata e seletiva, não uma campanha para todos.
4. **O desconto não explica a diferença entre os grupos.** Os segmentos recebem desconto praticamente igual ({VEREDITO[desc['veredito']]}); portanto, não há base nestes dados para uma política de desconto por segmento.
   Isto *não* diz que o desconto não influencia a compra: o teste compara grupos, não mede o efeito de dar desconto.""")
''')

md(r'''
### Ações, em ordem de prioridade

1. **Proteger os Fiéis:** monitorar queda de frequência (a constância de compra é o sinal que mais protege contra a pausa) antes de qualquer outra ação.
2. **Priorizar a reativação pelos Regulares em alerta**, onde está o maior valor em risco, e depois pelos Esporádicos, onde o risco é maior mas o valor por cliente é baixo. Usar o limiar do modelo para decidir quantos contatar:
   o gráfico de precisão e recall mostra a troca.
3. **Não diferenciar desconto por segmento** com base nestes dados; se a margem for o problema, olhar o desconto como um todo ou por categoria.

### O que estes dados não permitem afirmar

- **Nada é causal.** Segmentos descrevem comportamento; fatores do modelo são associação; a diferença de desconto entre grupos não mede o efeito do desconto sobre a compra.
- **Painel pequeno e frequente.** São 2.500 households que compram com regularidade, não o cliente médio do varejista. Resultados por loja ou categoria pequena são instáveis.
- **A margem é uma premissa** (25%): o CLV em dólares muda proporcionalmente; o ranking entre grupos, não.
- **Uma só janela de 26 semanas** e um só ano de comparação; as datas reais são arbitrárias, então sazonalidade por data não é medida.
- **O horizonte de 52 semanas do CLV não tem backtest**, e o CLV não serve como previsão por cliente.
- **Precisão por alerta modesta** no risco de pausa: o modelo ordena bem (AUC), mas a maioria dos alertas não se confirma; ele serve para priorizar, não para decidir sozinho.
- **Desconto de loja (cartão) e de cupom estão somados.** Separá-los é um próximo passo possível.

### Próximos passos possíveis

- Separar o desconto de loja do de cupom por segmento.
- Repetir as análises em outra janela e verificar se os segmentos e o risco se mantêm.
- Substituir a margem de 25% pela margem real por categoria, se o varejista a fornecer.
- *Market Basket* (associação entre produtos) ficou de fora de propósito: é uma análise à parte, não um pilar desta narrativa.
''')

# ------------------------------------------------------------------------------------------------ 8. reprodutibilidade

md(r'''
## 8. Reprodutibilidade

Um comando por etapa, semente fixa em tudo que é aleatório e parâmetros num único `config.yaml`. A célula abaixo ainda faz uma conferência final: **sobe o servidor MCP** (o mesmo que atende o app e o Claude Desktop)
e confirma que as quatro análises dão **exatamente os mesmos números** pelo servidor e aqui no notebook.
''')

code(r'''
from src.cliente_mcp import ServidorMCP

servidor = ServidorMCP(caminho_banco=raiz / CFG["banco"]["arquivo"])
try:
    via_mcp = {nome: servidor.chamar(nome) for nome in ("segmentar_clientes", "calcular_clv", "prever_churn", "testar_desconto_entre_segmentos")}
finally:
    servidor.fechar()
aqui = {"segmentar_clientes": seg, "calcular_clv": clv, "prever_churn": churn, "testar_desconto_entre_segmentos": desc}
import json
iguais = {n: json.loads(json.dumps(aqui[n], ensure_ascii=False, default=str)) == via_mcp[n] for n in aqui}
assert all(iguais.values()), f"notebook e servidor MCP divergem: {iguais}"
na.md("**Notebook e servidor MCP dão o mesmo resultado, campo a campo:** " + ", ".join(f"`{n}` ✓" for n in iguais) + f" (base `{versao}`).")
''')

code(r'''
na.md("**Versões das bibliotecas que determinam os números:** " + ", ".join(f"{p} {v}" for p, v in na.versoes().items()) + f". Python {sys.version.split()[0]}. Semente: {CFG['semente']}.")
na.md("""```
venv\\Scripts\\python.exe -m pip install -r requirements.txt     # versões travadas
venv\\Scripts\\python.exe baixar_dados.py                         # baixa data/raw/ (precisa de credencial do Kaggle)
venv\\Scripts\\python.exe -m src.etl                              # ETL: data/processed/dunnhumby.duckdb + relatorios/qualidade.md (~2 min)
venv\\Scripts\\python.exe notebooks\\construir_notebook.py          # reexecuta este notebook e salva com as saídas
venv\\Scripts\\python.exe -m pytest tests -q                      # testes (em partes: veja o CLAUDE.md)
```""")
''')
