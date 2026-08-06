"""
Approach 'random' -- substitui findingRandom.py::findValidChargingPoints.

Sorteia trincas de <connection> aleatórias; uma trinca é aceita como
candidata se as 3 formarem um ciclo alcançável no grafo. A lane do meio da
trinca vira o id da estação ("<edge>_<fromLane>").

CRESCIMENTO INCREMENTAL: a seed agora é por (approach, repetition) só --
representa "uma evolução da cidade" -- e é aplicada UMA vez, antes de
chamar evolution.get_or_extend. Esta função nunca decide sozinha por onde
começar: `_extend` recebe o conjunto já escolhido nos tiers anteriores
(persistido em disco por evolution.py) e só sorteia as estações NOVAS
necessárias para completar o tier pedido -- as antigas nunca são
recalculadas nem substituídas.
"""
from __future__ import annotations

import random

import networkx as nx

import graph_utils
from sim_job import SimJob
from station_strategies import evolution


def _forms_cycle(graph: nx.DiGraph, a: str, b: str, c: str) -> bool:
    return (
        nx.has_path(graph, a, b)
        and nx.has_path(graph, b, c)
        and nx.has_path(graph, c, a)
    )


def _extend(already_chosen: set, target: int, graph: nx.DiGraph) -> set:
    connections = graph_utils.list_connections()
    if len(connections) < 3:
        raise ValueError("net.xml tem menos de 3 <connection> -- impossível formar trincas")

    chosen = set(already_chosen)
    needed = target - len(chosen)
    max_attempts = max(needed, 1) * 2000
    attempts = 0
    while len(chosen) < target and attempts < max_attempts:
        attempts += 1
        c1, c2, c3 = random.sample(connections, 3)
        edges = (c1["from"], c2["from"], c3["from"])
        if not all(e in graph for e in edges):
            continue
        if not _forms_cycle(graph, *edges):
            continue
        candidate = f"{edges[1]}_{c2['fromLane']}"
        if candidate not in chosen:
            chosen.add(candidate)

    if len(chosen) < target:
        raise RuntimeError(
            f"Não foi possível completar o tier de {target} estações "
            f"(achadas: {len(chosen)}, tentativas: {attempts})."
        )
    return chosen


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set:
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition)

    def extend_fn(already_chosen: set, target: int) -> set:
        return _extend(already_chosen, target, graph)

    return evolution.get_or_extend(job.approach, job.repetition, job.cs_amount, extend_fn)
