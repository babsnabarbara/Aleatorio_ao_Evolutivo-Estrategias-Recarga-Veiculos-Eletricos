"""
Approach 'random' -- substitui findingRandom.py::findValidChargingPoints.

Sorteia trechos (vértices) com a mesma chance e põe a estação na faixa dada
por graph_utils.lane_for_edge -- ver FIX em _build. Critério de elegibilidade:
o edge pertence ao componente gigante e a própria faixa tem conexão de saída
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
    """
    FIX (2026-11-18): sorteio em dois passos, uniforme sobre os VÉRTICES.
      1. sorteia `cs_amount` trechos distintos entre os candidatos
         (graph_utils.candidate_edges), todos com a mesma chance;
      2. cada trecho vira estação na faixa dada por graph_utils.lane_for_edge
         (a mesma regra do approach 'genetic').
    Antes sorteava uma <connection> e usava a faixa de origem: faixas com
    mais conexões de saída, e trechos com mais faixas, tinham mais chance.
    Também não permite duas estações no mesmo trecho.
    """
    candidates = graph_utils.candidate_edges(graph)
    if len(candidates) < cs_amount:
        raise RuntimeError(
            f"Só existem {len(candidates)} trechos candidatos; "
            f"impossível escolher {cs_amount} estações."
        )
    return {graph_utils.lane_for_edge(edge)
            for edge in random.sample(candidates, cs_amount)}


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set:
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition, job.cs_amount)

    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount)
    if cached is not None:
        return cached

    chosen = _build(job.cs_amount, graph)
    evolution.save_stage(job.approach, job.repetition, job.cs_amount, chosen)
    return chosen