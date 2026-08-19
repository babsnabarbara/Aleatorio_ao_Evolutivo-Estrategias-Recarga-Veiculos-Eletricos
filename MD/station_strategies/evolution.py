"""
Cache em disco da seleção de estações por
(approach, repetition, cs_amount, max_vehicles_per_cs) -- usado pelas 3
estratégias com seed (random, pseudorandom, greedyvoronoi) pra não
recalcular a seleção toda vez que uma combinação diferente de
minutes/percentage passar pela mesma (cs_amount, repetition,
max_vehicles_per_cs).

Cada arquivo é INDEPENDENTE (não existe cadeia/cascata entre cs_amounts
diferentes) -- as 3 estratégias sorteiam do zero pra cada cs_amount, por
decisão explícita.

FIX: max_vehicles_per_cs entrou na chave depois de um bug real encontrado
em teste -- antes, rodar a MESMA (approach, repetition, cs_amount) duas
vezes com max_vehicles_per_cs diferente reaproveitava silenciosamente a
seleção calculada sob a restrição de capacidade ANTIGA, porque o arquivo
de cache nunca diferenciava isso. Isso é especialmente importante agora
que max_vehicles_per_cs também filtra candidatos por comprimento de lane
em random/pseudorandom/greedyvoronoi (ver graph_utils.has_min_capacity) --
antes, só pseudorandom usava esse valor pra decidir a seleção, então o
impacto do bug era menor (mas ainda existia).
"""
from __future__ import annotations

import config
import io_utils


def _stage_file(approach: str, repetition: int, cs_amount: int, max_vehicles_per_cs: int):
    return (
        config.station_evolution_dir(approach, repetition)
        / f"{cs_amount}stations_{max_vehicles_per_cs}mvpc.xml"
    )


def load_stage(approach: str, repetition: int, cs_amount: int,
                max_vehicles_per_cs: int) -> set[str] | None:
    """Carrega a seleção já persistida para essa combinação, ou None se
    ainda não foi calculada."""
    path = _stage_file(approach, repetition, cs_amount, max_vehicles_per_cs)
    if not path.exists():
        return None
    return io_utils.read_selected_lanes_file(path)


def save_stage(approach: str, repetition: int, cs_amount: int,
                max_vehicles_per_cs: int, stations: set[str]) -> None:
    path = _stage_file(approach, repetition, cs_amount, max_vehicles_per_cs)
    io_utils.write_selected_lanes_file_to(path, stations)