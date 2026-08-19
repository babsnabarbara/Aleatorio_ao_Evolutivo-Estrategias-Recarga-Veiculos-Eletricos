"""
Approach 'random' -- substitui findingRandom.py::findValidChargingPoints.

Sorteia trincas de <connection> aleatórias; uma trinca é aceita como
candidata se as 3 formarem um ciclo alcançável no grafo. A lane do meio da
trinca vira o id da estação ("<edge>_<fromLane>").

REVERTIDO para o comportamento original, por decisão explícita (mesmo
padrão de `pseudorandom` e `greedyvoronoi`): cada `cs_amount` sorteia do
zero, de forma independente -- 5 seleções aleatórias por tamanho de
estação (uma por repetição), sem relação entre um `cs_amount` e outro.
Não há mais crescimento incremental em NENHUM dos 3 approaches com seed
(só `random` ainda tinha; agora os 3 se comportam igual).

Por isso a seed usada aqui inclui `cs_amount` na chave
(StationSeedRegistry.apply(repetition, cs_amount)) -- cada tamanho sorteia
do zero, mas ainda determinística e cacheada (mesma seleção reaproveitada
entre `minutes`/`percentage` diferentes de uma mesma (cs_amount,
repetition)).
"""
from __future__ import annotations

import random

import networkx as nx

import graph_utils
import io_utils
from sim_job import SimJob
from station_strategies import evolution


def _forms_cycle(graph: nx.DiGraph, a: str, b: str, c: str) -> bool:
    return (
        nx.has_path(graph, a, b)
        and nx.has_path(graph, b, c)
        and nx.has_path(graph, c, a)
    )


def _build(cs_amount: int, graph: nx.DiGraph, max_vehicles_per_cs: int) -> set:
    connections = graph_utils.list_connections()
    if len(connections) < 3:
        raise ValueError("net.xml tem menos de 3 <connection> -- impossível formar trincas")

    lane_lengths = graph_utils.lane_lengths()
    veh_length = io_utils.vehicle_length("soulEV65")

    chosen: set = set()
    max_attempts = max(cs_amount, 1) * 2000
    attempts = 0
    while len(chosen) < cs_amount and attempts < max_attempts:
        attempts += 1
        c1, c2, c3 = random.sample(connections, 3)
        edges = (c1["from"], c2["from"], c3["from"])
        if not all(e in graph for e in edges):
            continue
        if not _forms_cycle(graph, *edges):
            continue
        candidate = f"{edges[1]}_{c2['fromLane']}"
        if candidate in chosen:
            continue
        # FIX: comprovado empiricamente (não só teórico) que uma lane curta
        # demais causa "skips stop" + teleporte em runtime -- ver
        # graph_utils.has_min_capacity para o raciocínio completo.
        if not graph_utils.has_min_capacity(candidate, max_vehicles_per_cs, lane_lengths, veh_length):
            continue
        chosen.add(candidate)

    if len(chosen) < cs_amount:
        raise RuntimeError(
            f"Não foi possível completar {cs_amount} estações com capacidade "
            f"mínima para {max_vehicles_per_cs} veículos "
            f"(achadas: {len(chosen)}, tentativas: {attempts})."
        )
    return chosen


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set:
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition, job.cs_amount)

    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount, job.max_vehicles_per_cs)
    if cached is not None:
        return cached

    chosen = _build(job.cs_amount, graph, job.max_vehicles_per_cs)
    evolution.save_stage(job.approach, job.repetition, job.cs_amount, job.max_vehicles_per_cs, chosen)
    return chosen