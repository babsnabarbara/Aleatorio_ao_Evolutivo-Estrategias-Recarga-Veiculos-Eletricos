"""
Registro central de estratégias -- substitui o `approachFiles` dict de
main.py (que fazia os.system("python3 findingX.py ...")) por uma chamada
direta em processo, com a mesma assinatura para todo approach.
"""
from __future__ import annotations

from station_strategies import (
    greedy_strategy,
    greedy_voronoi_strategy,
    pseudorandom_strategy,
    random_strategy,
)
from station_strategies.base import StationStrategy

REGISTRY: dict[str, StationStrategy] = {
    "random": random_strategy.select_charging_points,
    "pseudorandom": pseudorandom_strategy.select_charging_points,
    "greedy": greedy_strategy.select_charging_points,
    "greedyvoronoi": greedy_voronoi_strategy.select_charging_points,
}


def get_strategy(approach: str) -> StationStrategy:
    try:
        return REGISTRY[approach]
    except KeyError:
        raise ValueError(
            f"Approach '{approach}' desconhecido. Opções: {sorted(REGISTRY)}"
        ) from None
