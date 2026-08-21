"""
Approach 'pseudorandom' -- substitui
findingPseudoRandom.py::findAndSaveValidChargingPoints.

Usa a malha de quadrantes do MESMO TAMANHO que cs_amount (9quadrants.xml
para 9 estações, 16quadrants.xml para 16, ...) -- cada cs_amount usa uma
partição espacial DIFERENTE do mapa, sem relação entre si. Sem crescimento
incremental (mesmo trade-off do 'greedyvoronoi').

Seed inclui `cs_amount` na chave (StationSeedRegistry.apply(repetition,
cs_amount)) -- cada tamanho de malha sorteia do zero, de forma
independente, mas cacheada (mesma seleção reaproveitada entre
minutes/percentage diferentes de uma mesma (cs_amount, repetition)).

NÃO filtra candidatos por capacidade/comprimento de lane (o código original
tinha essa checagem via TraCI ao vivo -- removida por decisão
metodológica): a capacidade real de cada estação é calculada DEPOIS, na
hora de gerar o .add.xml (ver graph_utils.realized_capacity), adaptada à
geometria de cada lane, em vez de rejeitar posições que não caibam
max_vehicles_per_cs veículos. Isso mantém a regra simétrica entre os 5
approaches -- nenhum tem tratamento especial de capacidade na seleção.

Candidatos são restritos ao componente gigante do mapa (o `graph` recebido
já vem assim de cli.py/graph_utils.default_giant_graph) -- mesmo padrão do
algoritmo genético original, agora unificado nos 5 approaches. Como todo
par de nós dentro do componente gigante já é mutuamente alcançável por
definição, "pertence ao grafo recebido" já é suficiente -- não precisa
mais confirmar caminho entre eles com nx.has_path.
"""
from __future__ import annotations

import random
import xml.etree.ElementTree as ET

import networkx as nx

import config
from sim_job import SimJob
from station_strategies import evolution


def _quadrants_for(cs_amount: int) -> list:
    from quadrants_check import ensure_quadrants
    ensure_quadrants(cs_amount)  # gera as malhas sob demanda se ainda não existirem

    quadrants_file = config.LANES_IN_EACH_QUADRANT_DIR / f"{cs_amount}quadrants.xml"
    root = ET.parse(quadrants_file).getroot()
    return [
        [lane.text for lane in quadrant.findall("lane") if lane.text]
        for quadrant in root.findall(".//quadrant")
    ]


def _build(cs_amount: int, graph: nx.DiGraph) -> set:
    quadrants = _quadrants_for(cs_amount)

    chosen: set = set()
    max_attempts_per_quadrant = 5000

    for quadrant_lanes in quadrants:
        if len(quadrant_lanes) < 3:
            raise ValueError(
                f"Quadrante com só {len(quadrant_lanes)} lane(s) -- "
                f"impossível sortear trinca (cs_amount={cs_amount})."
            )

        found = False
        for _ in range(max_attempts_per_quadrant):
            a, b, c = random.sample(quadrant_lanes, 3)
            # a[:-2] converte lane id -> edge id (remove o sufixo "_0")
            if not all(lane[:-2] in graph for lane in (a, b, c)):
                continue
            if b in chosen:
                continue
            chosen.add(b)
            found = True
            break

        if not found:
            raise RuntimeError(
                f"Não achei estação válida para um quadrante em "
                f"{max_attempts_per_quadrant} tentativas (cs_amount={cs_amount})."
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