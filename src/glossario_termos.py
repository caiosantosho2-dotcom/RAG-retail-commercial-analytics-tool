"""Conteúdo do glossário de negócio (RAG): o vocabulário do usuário traduzido para as views e colunas.

Duas fontes, sem duplicar fórmula:
- termos de métrica: a definição e a fórmula vêm de `views.METRICAS` (fonte única); aqui entram só
  os sinônimos que o usuário usa e um complemento de uso;
- termos de vocabulário (loja, categoria, laticínios, campanha ...): texto próprio.
Nada aqui fala em vendedor: não existe vendedor individual neste dataset.
"""

from src.views import METRICAS

_METRICAS = {nome: (definicao, formula, view) for nome, definicao, formula, view in METRICAS}

# Termos de métrica: (termo, sinônimos, chave em views.METRICAS, complemento de uso)
_TERMOS_DE_METRICA = [
    ("Faturamento", "vendas, receita, venda líquida, vendeu, vendido, quanto vendeu, SALES_VALUE", "faturamento",
     "Já é líquido de desconto: não subtraia desconto de novo."),
    ("Desconto total", "desconto, promoção, abatimento, quanto de desconto", "desconto_total",
     "Valor positivo em US$. Descontos originais vêm negativos; a view já inverte o sinal."),
    ("Desconto de loja", "desconto de fidelidade, cartão fidelidade, RETAIL_DISC, desconto da loja", "desconto_loja", ""),
    ("Desconto de cupom", "cupom, desconto de cupom, COUPON_DISC, cupom casado", "desconto_cupom", ""),
    ("Valor bruto", "preço de tabela, venda sem desconto, antes do desconto", "valor_bruto", ""),
    ("Percentual de desconto", "% de desconto, taxa de desconto, quanto % de desconto", "pct_desconto",
     "Sai em 0 a 100. Agregue somando desconto_total e valor_bruto antes de dividir, nunca tirando média de percentuais."),
    ("Cesta", "ida à loja, compra, transação, visita, basket, BASKET_ID, número de compras", "cestas",
     "Em vw_vendas_item conte COUNT(DISTINCT BASKET_ID); nas views agregadas some a coluna cestas."),
    ("Itens", "unidades, quantidade vendida, volume, QUANTITY", "itens", ""),
    ("Ticket médio", "valor médio da cesta, gasto por ida, gasto médio por compra", "ticket_medio",
     "Some faturamento e cestas antes de dividir."),
    ("Itens por cesta", "unidades por cesta, tamanho da cesta, produtos por compra", "itens_por_cesta", ""),
    ("Clientes", "household, família, domicílio, consumidor, quantos clientes, base de clientes", "clientes",
     "A chave é household_key."),
    ("Idas por cliente", "frequência de compra, quantas vezes cada cliente comprou, idas à loja por cliente",
     "idas_por_cliente", ""),
    ("Cliente ativo", "clientes ativos, base ativa, quem ainda compra", "cliente_ativo", ""),
    ("Recência", "há quanto tempo comprou, dias desde a última compra, última compra", "recencia_dias", ""),
    ("Frequência do cliente", "número de compras do cliente, quantas compras por cliente", "frequencia_cliente", ""),
    ("Valor do cliente", "gasto do cliente, quanto o cliente gastou, valor monetário", "valor_cliente", ""),
    ("Janela atual", "período atual, últimas 26 semanas, período de análise, agora", "janela_atual",
     "Datas e semanas exatas em vw_janela."),
    ("Ano anterior", "ano passado, mesmo período do ano passado, base de comparação, YoY, contra o ano passado",
     "base_ano_anterior", "Para comparar use as views vw_yoy_*; elas já alinham as semanas e as lojas."),
    ("Semana alinhada", "semana correspondente, alinhar semanas", "semana_alinhada", ""),
    ("Like-for-like", "mesmas lojas, lojas comparáveis, base comparável, loja nova, lojas novas, loja fechada, só existem, não existiam", "like_for_like",
     "Diga quantas lojas ficaram de fora (vw_yoy_resumo)."),
    ("Variação contra o ano anterior", "crescimento, queda, cresceu, caiu, evolução, variação, delta, contra o ano passado",
     "variacao_ano_anterior", "Use vw_yoy_resumo (total), vw_yoy_loja (por loja) ou vw_yoy_categoria (por categoria e marca)."),
    ("Árvore de vendas", "por que caiu, por que cresceu, menos clientes, menos idas, menos gasto por ida, o que explica a variação",
     "arvore_de_vendas", "As colunas var_clientes_pct, var_idas_por_cliente_pct e var_ticket_pct estão em vw_yoy_resumo "
                         "(total) e, por loja, em vw_yoy_loja (clientes, cestas e ticket)."),
    ("Penetração", "penetração da categoria, quantos clientes compram a categoria, alcance, share de clientes",
     "penetracao", "Para um período que não seja a janela inteira (trimestre, mês), calcule direto em vw_vendas_item: "
                   "clientes distintos que compraram a categoria dividido pelos clientes distintos com qualquer compra."),
    ("Marca própria", "private label, marca nacional, marca da loja, Private, National, BRAND", "marca_propria", ""),
    ("Último mês", "mês passado, últimas 4 semanas, últimos 30 dias, mês mais recente", "ultimo_mes",
     "Filtre vw_metricas_loja_semana ou vw_vendas_item por semana_alinhada >= semana_ini_ultimo_mes de vw_janela, com periodo = 'atual'."),
    ("Último trimestre", "trimestre passado, últimas 13 semanas, últimos 3 meses", "ultimo_trimestre",
     "Filtre por semana_alinhada >= semana_ini_ultimo_trimestre de vw_janela, com periodo = 'atual'."),
    ("Amostra pequena", "loja pequena, poucos dados, número instável, loja com pouca venda", "amostra_pequena",
     "Avise o usuário quando a loja consultada tiver amostra_pequena = TRUE."),
]

# Termos de vocabulário: (termo, texto completo)
_TERMOS_DE_VOCABULARIO = [
    ("Loja (também: unidade, filial, ponto de venda, store)",
     "Identificada por STORE_ID. Não existe vendedor individual: a loja é a menor unidade de equipe. "
     "Os números por loja usam vw_metricas_loja_semana. Em rankings de lojas, filtre amostra_pequena = FALSE "
     "(ou avise): lojas com poucas cestas distorcem médias como o ticket."),
    ("Categoria (também: seção, departamento, commodity, linha de produto, grupo)",
     "DEPARTMENT é o nível amplo (GROCERY, MEAT, PRODUCE, DRUG GM, DELI ...) e COMMODITY_DESC o nível de categoria "
     "(SOFT DRINKS, CHEESE, FLUID MILK PRODUCTS ...). Filtre texto com ILIKE '%...%' para tolerar a escrita. "
     "Dados por loja e categoria: vw_metricas_loja_depto_semana."),
    ("Produto (também: item, SKU, artigo, ranking de produtos, mais vendidos)",
     "PRODUCT_ID, com COMMODITY_DESC, SUB_COMMODITY_DESC, BRAND e MANUFACTURER em dim_produto. Para rankings some "
     "faturamento ou quantidade em vw_vendas_item por PRODUCT_ID e junte dim_produto; liste no máximo 20."),
    ("Laticínios (também: lácteos, dairy, leite e queijo)",
     "Não é um departamento. Use COMMODITY_DESC IN ('FLUID MILK PRODUCTS', 'MILK BY-PRODUCTS', 'CHEESE', 'CHEESES', "
     "'YOGURT', 'BUTTER', 'MISC. DAIRY'). Ovos e sorvete ficam de fora."),
    ("Cliente de alta frequência (também: clientes fiéis, quem compra mais vezes)",
     "Household com frequencia acima do percentil 75 em vw_metricas_cliente no período. Use "
     "quantile_cont(frequencia, 0.75) para achar o corte."),
    ("Campanha (também: ação promocional, mailer de campanha, resgate de cupom)",
     "campaign_desc traz CAMPAIGN, DESCRIPTION (TypeA, TypeB, TypeC), START_DAY e END_DAY; campaign_table, os households "
     "que receberam; coupon_redempt, os resgates (household_key, DAY, CAMPAIGN). Para o gasto de quem resgatou, junte "
     "os households de coupon_redempt com vw_vendas_item. Resumo por período: vw_contexto_periodo."),
    ("Display e mailer (também: exposição, encarte, material de ponto de venda)",
     "causal_semana_loja traz, por semana e loja, quantas linhas produto-loja estavam em display (linhas_display) e em "
     "mailer (linhas_mailer). Só cobre as semanas 9 a 101."),
    ("Curva ABC (também: concentração, Pareto, 80% do faturamento, quem concentra as vendas)",
     "Agregue por categoria e calcule o acumulado: SUM(faturamento) OVER (ORDER BY faturamento DESC) dividido por "
     "SUM(SUM(faturamento)) OVER (); o grupo A é quem fecha 80%."),
    ("Demografia (também: renda, idade, perfil do cliente, estado civil, filhos)",
     "dim_household traz AGE_DESC, INCOME_DESC, HOMEOWNER_DESC, HOUSEHOLD_SIZE_DESC e KID_CATEGORY_DESC, mas só para "
     "uma parte dos households (tem_demografia). Use LEFT JOIN e diga a cobertura."),
    ("Data relativa (também: hoje, ontem, este mês, esta semana, recentemente)",
     "Sempre relativo ao fim dos dados (vw_janela.data_fim_atual), nunca à data de hoje. As datas reais são arbitrárias; "
     "prefira semanas (semana_alinhada)."),
    ("Moeda (também: dólar, reais, R$, valor em dinheiro)",
     "Todos os valores estão em dólares (US$)."),
    ("Devolução (também: estorno, troca, cancelamento)",
     "Não há devoluções nesta base: não existe valor ou quantidade negativos. Combustível e pseudo-itens de cupom ficam "
     "fora das vendas."),
    ("Segmentação, CLV, churn e teste de desconto (também: RFM, valor do cliente ao longo da vida, risco de saída, perfil de cliente)",
     "Não são consultas SQL: são análises estatísticas das abas de análise. Não tente reproduzi-las com SQL."),
]


def _montar() -> list[dict]:
    itens = []
    for termo, sinonimos, chave, extra in _TERMOS_DE_METRICA:
        definicao, formula, view = _METRICAS[chave]
        texto = f"{definicao} Fórmula: {formula}. View: {view}."
        itens.append({"termo": f"{termo} (também: {sinonimos})", "definicao": f"{texto} {extra}".strip()})
    itens += [{"termo": t, "definicao": d} for t, d in _TERMOS_DE_VOCABULARIO]
    return itens


GLOSSARIO = _montar()
