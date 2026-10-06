"""Cache das análises: uma análise pode chamar outra (o CLV usa o RFM) sem travar."""

import threading

from src.nucleo import cache


def rodar_com_limite(funcao, segundos=10):
    resultado, erro = [], []

    def alvo():
        try:
            resultado.append(funcao())
        except Exception as e:  # noqa: BLE001
            erro.append(e)

    t = threading.Thread(target=alvo, daemon=True)
    t.start()
    t.join(segundos)
    assert not t.is_alive(), "deadlock: o cache travou numa chamada aninhada"
    assert not erro, erro
    return resultado[0]


def test_chamada_aninhada_nao_trava():
    cache.limpar()
    interno = lambda: cache.obter("interno", lambda: 41)
    assert rodar_com_limite(lambda: cache.obter("externo", lambda: interno() + 1)) == 42


def test_valor_e_calculado_uma_vez_e_o_chamador_recebe_copia():
    cache.limpar()
    chamadas = []
    a = cache.obter("k", lambda: chamadas.append(1) or {"x": [1]})
    a["x"].append(2)
    b = cache.obter("k", lambda: chamadas.append(1) or {"x": [9]})
    assert chamadas == [1] and b == {"x": [1]}          # alterar o retorno não suja o cache


def test_limpar_apaga_tudo():
    cache.obter("z", lambda: 1)
    cache.limpar()
    assert cache.obter("z", lambda: 2) == 2
