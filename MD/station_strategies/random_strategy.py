"""
Approach 'random' -- substitui findingRandom.py::findValidChargingPoints.

Sorteia UMA <connection> aleatória por vez; sua lane vira o id da estação
("<edge>_<fromLane>"), desde que o edge pertença ao componente gigante
(giant strongly-connected component) do mapa -- o `graph` recebido aqui já
vem restrito a esse componente (ver cli.py/graph_utils.default_giant_graph).

FIX: antes sorteava uma TRINCA de conexões e exigia que as 3 pertencessem
ao componente gigante, mesmo só usando a do meio como candidato -- resquício
de quando essa checagem servia pra validar um ciclo entre as 3 (removido
numa limpeza anterior, quando a validação de ciclo virou desnecessária com
o componente gigante). Sortear 3 e descartar 2 não mudava QUAL candidato
acabava sendo aceito (a escolha final ainda saía aproximadamente uniforme
entre os edges válidos do componente gigante, com tentativas suficientes) --
só desperdiçava sorteios: bastava 1 dos 3 falhar a checagem pra trinca
inteira ser descartada, mesmo que o candidato real (o do meio) fosse
válido sozinho. Sortear 1 direto é mais rápido, sem mudar o resultado.

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
    if not connections:
        raise ValueError("net.xml não tem nenhuma <connection> -- impossível sortear candidato")

    chosen: set = set()
    max_attempts = max(cs_amount, 1) * 2000
    attempts = 0
    while len(chosen) < cs_amount and attempts < max_attempts:
        attempts += 1
        conn = random.choice(connections)
        edge = conn["from"]
        if edge not in graph:
            continue
        candidate = f"{edge}_{conn['fromLane']}"
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
