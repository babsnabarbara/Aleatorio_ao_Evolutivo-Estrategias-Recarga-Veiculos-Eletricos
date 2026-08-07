"""
Garante que as malhas de quadrantes (input/lanesInEachQuadrant/*.xml)
existem antes de station_strategies (greedy, pseudorandom) tentarem lê-las
-- gera todas as 5 automaticamente, sob demanda, se faltarem, em vez de
exigir que você rode `python3 quadrants.py` manualmente antes.

Usado por station_strategies/greedy_strategy.py e
station_strategies/pseudorandom_strategy.py.
"""
from __future__ import annotations

import config


def ensure_quadrants(cs_amount: int) -> None:
    """
    Confere se input/lanesInEachQuadrant/<cs_amount>quadrants.xml existe;
    se não existir, chama quadrants.generate_all_quadrants() (que gera as
    5 malhas de uma vez -- 9, 16, 25, 36, 49 -- do jeito que sempre foi
    gerado) e confere de novo. Se ainda faltar depois disso, o
    `cs_amount` pedido não faz parte do grid suportado (ex: um valor fora
    de 9/16/25/36/49), e a função levanta um erro claro em vez de tentar
    gerar de novo à toa.
    """
    target = config.LANES_IN_EACH_QUADRANT_DIR / f"{cs_amount}quadrants.xml"
    if target.exists():
        return

    import quadrants  # import tardio -- só quando realmente precisa gerar
    quadrants.generate_all_quadrants()

    if not target.exists():
        raise FileNotFoundError(
            f"{target} continua não existindo mesmo depois de rodar "
            f"quadrants.py -- cs_amount={cs_amount} provavelmente não é um "
            f"dos tamanhos gerados (9, 16, 25, 36, 49). Confira "
            f"config.STATIONS_AMOUNTS."
        )
