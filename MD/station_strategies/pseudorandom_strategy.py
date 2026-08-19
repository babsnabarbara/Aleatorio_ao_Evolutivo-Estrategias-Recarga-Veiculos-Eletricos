"""
Approach 'pseudorandom' -- substitui
findingPseudoRandom.py::findAndSaveValidChargingPoints.

REVERTIDO para o comportamento original, por decisão explícita: usa a
malha de quadrantes do MESMO TAMANHO que cs_amount (9quadrants.xml para 9
estações, 16quadrants.xml para 16, ...) -- ou seja, cada cs_amount usa uma
partição espacial DIFERENTE do mapa, sem relação entre si.

Isso significa que este approach NÃO tem crescimento incremental: ao
crescer de 9 para 16 estações, a malha muda de forma inteira, então não há
garantia (nem seed que resolva -- mesma sequência de números aleatórios
aplicada a uma estrutura de dados diferente não produz resultados
relacionados) de que as 9 posições antigas continuem entre as 16 novas.
Mesmo comportamento/trade-off do approach 'greedyvoronoi' (ver aquele
arquivo para mais detalhes do raciocínio).

Por isso a seed usada aqui inclui `cs_amount` na chave
(StationSeedRegistry.apply(repetition, cs_amount)) -- cada tamanho de malha
sorteia do zero, de forma independente, mas ainda determinística e
cacheada (mesma seleção reaproveitada entre minutes/percentage diferentes
de uma mesma (cs_amount, repetition)).

FIX (herdado, mantido): a checagem de capacidade
(`lane.getLength / vehicletype.getLength >= max_vehicles_per_cs`) usava
TraCI ao vivo; aqui é lida estaticamente do net.xml/electric_vehicle.xml,
pois a fase de geração roda antes de qualquer SUMO ser iniciado.
"""
from __future__ import annotations

import random
import xml.etree.ElementTree as ET

import networkx as nx

import config
import graph_utils
import io_utils
from sim_job import SimJob
from station_strategies import evolution


def _forms_cycle(graph: nx.DiGraph, a_lane: str, b_lane: str, c_lane: str) -> bool:
    a, b, c = a_lane[:-2], b_lane[:-2], c_lane[:-2]
    if not all(n in graph for n in (a, b, c)):
        return False
    return (
        nx.has_path(graph, a, b)
        and nx.has_path(graph, b, c)
        and nx.has_path(graph, c, a)
    )


def _quadrants_for(cs_amount: int) -> list:
    from quadrants_check import ensure_quadrants
    ensure_quadrants(cs_amount)  # gera as malhas sob demanda se ainda não existirem

    quadrants_file = config.LANES_IN_EACH_QUADRANT_DIR / f"{cs_amount}quadrants.xml"
    root = ET.parse(quadrants_file).getroot()
    return [
        [lane.text for lane in quadrant.findall("lane") if lane.text]
        for quadrant in root.findall(".//quadrant")
    ]


def _build(cs_amount: int, graph: nx.DiGraph, max_vehicles_per_cs: int) -> set:
    quadrants = _quadrants_for(cs_amount)
    lane_lengths = graph_utils.lane_lengths()
    veh_length = io_utils.vehicle_length("soulEV65")

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
            if not _forms_cycle(graph, a, b, c):
                continue
            if b in chosen:
                continue
            if not graph_utils.has_min_capacity(b, max_vehicles_per_cs, lane_lengths, veh_length):
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

    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount, job.max_vehicles_per_cs)
    if cached is not None:
        return cached

    chosen = _build(job.cs_amount, graph, job.max_vehicles_per_cs)
    evolution.save_stage(job.approach, job.repetition, job.cs_amount, job.max_vehicles_per_cs, chosen)
    return chosen