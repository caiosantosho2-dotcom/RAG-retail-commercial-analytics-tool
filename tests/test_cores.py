"""Cores dos gráficos: o porte do validador reproduz os números da skill e toda paleta usada passa nos dois modos."""

import pytest

from src.ui import cores


def test_porte_do_validador_reproduz_os_numeros_documentados_da_paleta_oficial():
    claro = cores.validar(cores.CATEGORICA["claro"], "claro", "#fcfcfb")
    escuro = cores.validar(cores.CATEGORICA["escuro"], "escuro", "#1a1a19")
    assert claro["ok"] and escuro["ok"]
    assert claro["verificacoes"]["separacao_daltonismo"][1]["pior_delta_e"] == 9.1       # documentado: 9,1 claro / 8,4 escuro
    assert escuro["verificacoes"]["separacao_daltonismo"][1]["pior_delta_e"] == 8.4
    assert claro["verificacoes"]["visao_normal"][1]["pior_delta_e"] == 19.6              # documentado: 19,6 / 19,3
    assert escuro["verificacoes"]["visao_normal"][1]["pior_delta_e"] == 19.3


def test_contraste_wcag_de_referencia():
    assert cores.contraste("#000000", "#ffffff") == pytest.approx(21.0)
    assert cores.contraste("#ffffff", "#ffffff") == pytest.approx(1.0)


def test_o_validador_reprova_uma_paleta_ruim():
    ruim = cores.validar(["#2a78d6", "#2b79d7", "#2c7ad8"], "claro")        # três azuis quase iguais
    assert ruim["ok"] is False and ruim["verificacoes"]["visao_normal"][0] == "falha"
    cinza = cores.validar(["#999999", "#2a78d6"], "claro")
    assert cinza["verificacoes"]["piso_de_croma"][0] == "falha"             # cinza não faz trabalho de identidade


@pytest.mark.parametrize("modo", ["claro", "escuro"])
def test_quatro_primeiros_slots_passam_na_superficie_do_streamlit(modo):
    r = cores.validar(cores.CATEGORICA[modo][:4], modo)       # superfície padrão: a do Streamlit
    assert r["ok"], r
    assert r["verificacoes"]["separacao_daltonismo"][0] == "ok"


@pytest.mark.parametrize("modo", ["claro", "escuro"])
def test_destaque_e_cinza_se_distinguem_e_tem_contraste(modo):
    sup = cores.SUPERFICIE[modo]
    assert cores.contraste(cores.DESTAQUE[modo], sup) >= 3 and cores.contraste(cores.CINZA[modo], sup) >= 3
    assert cores.delta_e(cores.DESTAQUE[modo], cores.CINZA[modo]) >= cores.PISO_VISAO_NORMAL
    assert min(cores.delta_e(cores.DESTAQUE[modo], cores.CINZA[modo], t) for t in ("protan", "deutan")) >= cores.CVD_ALVO


@pytest.mark.parametrize("modo", ["claro", "escuro"])
def test_rampa_sequencial_e_monotona_e_o_escuro_inverte_a_ancora(modo):
    rampa = cores.rampa_sequencial(modo)
    v = cores.validar_rampa_sequencial(rampa, modo)
    assert v["monotona"] and v["contraste_do_extremo_mais_visivel"] >= 3
    # claro: valor baixo = passo claro; escuro: valor baixo = passo escuro (se aproxima da superfície)
    assert (cores.oklch(rampa[0])[0] > cores.oklch(rampa[-1])[0]) == (modo == "claro")


def test_modo_atual_sem_contexto_e_claro():
    assert cores.modo_atual() == "claro"


def test_dados_dos_slots_sao_os_da_paleta_documentada():
    assert cores.CATEGORICA["claro"][:3] == ["#2a78d6", "#eb6834", "#1baf7a"]
    assert cores.CATEGORICA["escuro"][:3] == ["#3987e5", "#d95926", "#199e70"]
    assert len(cores.CATEGORICA["claro"]) == len(cores.CATEGORICA["escuro"]) == 8
