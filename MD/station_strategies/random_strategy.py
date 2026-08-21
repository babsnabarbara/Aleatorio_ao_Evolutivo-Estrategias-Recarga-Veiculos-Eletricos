"""
Approach 'random' -- substitui findingRandom.py::findValidChargingPoints.

Sorteia trincas de <connection> aleatórias; a lane do meio da trinca vira
o id da estação ("<edge>_<fromLane>"), desde que os 3 edges pertençam ao
componente gigante (giant strongly-connected component) do mapa -- o
`graph` recebido aqui já vem restrito a esse componente (ver
cli.py/graph_utils.default_giant_graph), mesmo padrão usado pelo algoritmo
genético original e agora unificado nos 5 approaches (antes, esta função
conferia só se as 3 lanes formavam ciclo ENTRE SI, uma checagem mais fraca
que não garantia pertencer ao núcleo bem conectado do mapa -- removida por
ser redundante agora: todo par de nós dentro do componente gigante já é
mutuamente alcançável por definição, então "pertence ao grafo recebido" já
é suficiente).

Cada `cs_amount` sorteia do zero, de forma independente -- 5 seleções
aleatórias por tamanho de estação (uma por repetição), sem relação entre
um `cs_amount` e outro (decisão explícita, mesmo padrão de `pseudorandom`
e `greedyvoronoi`).

NÃO filtra candidatos por capacidade/comprimento de lane -- decisão
metodológica: a capacidade real de cada estação é calculada DEPOIS, na
hora de gerar o .add.xml (ver graph_utils.realized_capacity), adaptada à
geometria de cada lane, em vez de rejeitar posições que não caibam
max_vehicles_per_cs veículos.
"""
from __future__ import annotations

import random

import networkx as nx

import graph_utils
from sim_job import SimJob
from station_strategies import evolution


def _build(cs_amount: int, graph: nx.DiGraph) -> set:
    connections = graph_utils.list_connections()
    if len(connections) < 3:
        raise ValueError("net.xml tem menos de 3 <connection> -- impossível formar trincas")

    chosen: set = set()
    max_attempts = max(cs_amount, 1) * 2000
    attempts = 0
    while len(chosen) < cs_amount and attempts < max_attempts:
        attempts += 1
        c1, c2, c3 = random.sample(connections, 3)
        edges = (c1["from"], c2["from"], c3["from"])
        if not all(e in graph for e in edges):
            continue
        candidate = f"{edges[1]}_{c2['fromLane']}"
        if candidate not in chosen:
            chosen.add(candidate)

    if len(chosen) < cs_amount:
        raise RuntimeError(
            f"Não foi possível completar {cs_amount} estações "
            f"(achadas: {len(chosen)}, tentativas: {attempts})."
        )
    return chosen


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set:
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition, job.cs_amount)

    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount)
    if cached is not None:
        return cached

    chosen = _build(job.cs_amount, graph)
    evolution.save_stage(job.approach, job.repetition, job.cs_amount, chosen)
    return chosen