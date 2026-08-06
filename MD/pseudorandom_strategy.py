"""
Approach 'pseudorandom' -- substitui
findingPseudoRandom.py::findAndSaveValidChargingPoints.

MUDANÇA ESTRUTURAL (necessária para o crescimento incremental): o approach
original usava um arquivo de quadrantes DIFERENTE por cs_amount
(9quadrants.xml, 16quadrants.xml, ...) -- cada cs_amount tinha sua PRÓPRIA
malha espacial, sem relação entre si. Isso é incompatível com "crescer
mantendo as estações antigas": a malha de 16 não é uma extensão da de 9,
é uma partição geometricamente diferente.

A partir de agora esta estratégia usa SEMPRE a malha mais fina disponível
(49quadrants.xml) como partição fixa. Cada tier escolhe um subconjunto
dessas 49 células para receber uma estação -- 9 na primeira leva, e vai
completando à medida que cs_amount cresce, sem nunca tocar nas células já
usadas por um tier anterior.

FIX (herdado da versão anterior): a checagem de capacidade
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

_FIXED_QUADRANTS_CS_AMOUNT = max(config.STATIONS_AMOUNTS)  # 49 -- malha mais fina


def _forms_cycle(graph: nx.DiGraph, a_lane: str, b_lane: str, c_lane: str) -> bool:
    a, b, c = a_lane[:-2], b_lane[:-2], c_lane[:-2]
    if not all(n in graph for n in (a, b, c)):
        return False
    return (
        nx.has_path(graph, a, b)
        and nx.has_path(graph, b, c)
        and nx.has_path(graph, c, a)
    )


def _fixed_quadrants() -> list:
    quadrants_file = (
        config.LANES_IN_EACH_QUADRANT_DIR / f"{_FIXED_QUADRANTS_CS_AMOUNT}quadrants.xml"
    )
    if not quadrants_file.exists():
        raise FileNotFoundError(
            f"{quadrants_file} não existe -- rode quadrants.py para gerar a malha "
            f"fixa de {_FIXED_QUADRANTS_CS_AMOUNT} quadrantes usada pelo pseudorandom."
        )
    root = ET.parse(quadrants_file).getroot()
    return [
        [lane.text for lane in quadrant.findall("lane") if lane.text]
        for quadrant in root.findall(".//quadrant")
    ]


def _quadrant_of(lane_id: str, quadrants: list):
    for idx, lanes in enumerate(quadrants):
        if lane_id in lanes:
            return idx
    return None


def _extend(already_chosen: set, target: int, graph: nx.DiGraph, max_vehicles_per_cs: int) -> set:
    quadrants = _fixed_quadrants()
    if len(quadrants) < target:
        raise ValueError(
            f"Malha fixa tem só {len(quadrants)} quadrantes, mas o tier pede {target}."
        )

    lane_lengths = graph_utils.lane_lengths()
    veh_length = io_utils.vehicle_length("soulEV65")

    used_quadrants = set()
    for lane in already_chosen:
        idx = _quadrant_of(lane, quadrants)
        if idx is not None:
            used_quadrants.add(idx)

    chosen = set(already_chosen)
    order = list(range(len(quadrants)))
    random.shuffle(order)

    for idx in order:
        if len(chosen) >= target:
            break
        if idx in used_quadrants:
            continue

        lanes = quadrants[idx]
        if len(lanes) < 3:
            continue  # quadrante pequeno demais para formar trinca -- pula

        for _ in range(2000):
            a, b, c = random.sample(lanes, 3)
            if not _forms_cycle(graph, a, b, c):
                continue
            if b in chosen:
                continue
            length = lane_lengths.get(b)
            if length is None or (length / veh_length) < max_vehicles_per_cs:
                continue
            chosen.add(b)
            used_quadrants.add(idx)
            break

    if len(chosen) < target:
        raise RuntimeError(
            f"Não foi possível completar o tier de {target} estações -- só "
            f"{len(chosen)} quadrantes válidos encontrados na malha fixa "
            f"({len(quadrants) - len(used_quadrants)} quadrantes ainda livres)."
        )
    return chosen


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set:
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition)

    def extend_fn(already_chosen: set, target: int) -> set:
        return _extend(already_chosen, target, graph, job.max_vehicles_per_cs)

    return evolution.get_or_extend(job.approach, job.repetition, job.cs_amount, extend_fn)
