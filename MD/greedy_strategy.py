"""
Approach 'greedy' -- substitui findingStationsGreedy.py::findCSInQuadrants.

Estratégia determinística: lê as lanes mais visitadas (input/mostVisited.xml,
já ordenado por contagem de visitas -- não reordenamos aqui, preservamos a
ordem do arquivo como o original fazia) e, para cada uma, associa à primeira
quadrante ainda vazia que a contenha, até preencher todas as `cs_amount`
quadrantes.

Não usa `graph` (não há validação de ciclo aqui no original) nem sorteio
algum -- por isso, ao contrário dos outros 3 approaches, as 5 repetições de
'greedy' para uma mesma (cs, percentage) são sempre idênticas entre si (não
há fonte de aleatoriedade na escolha da estação em si; a única variação
entre repetições vem do sorteio de trips, que continua usando a seed do
job normalmente).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import networkx as nx

import config
from sim_job import SimJob


def _most_visited_lanes() -> dict[str, int]:
    root = ET.parse(config.MOST_VISITED_FILE).getroot()
    lanes: dict[str, int] = {}
    for lane_elem in root.findall(".//lane"):
        lane_id = lane_elem.get("id")
        count = lane_elem.get("count")
        if lane_id is not None:
            lanes[lane_id] = int(count) if count is not None else 0
    return lanes


def _quadrants_lanes(cs_amount: int) -> list[tuple[str, str, list[str]]]:
    """Devolve [(x, y, [lane_ids...]), ...] preservando a ordem do arquivo."""
    quadrants_file = config.LANES_IN_EACH_QUADRANT_DIR / f"{cs_amount}quadrants.xml"
    if not quadrants_file.exists():
        raise FileNotFoundError(
            f"{quadrants_file} não existe -- rode quadrants.py para gerar os "
            f"quadrantes de {cs_amount} estações antes de usar o approach greedy."
        )
    root = ET.parse(quadrants_file).getroot()
    result = []
    for quadrant in root.findall(".//quadrant"):
        lanes = [lane.text for lane in quadrant.findall("lane") if lane.text]
        result.append((quadrant.get("x"), quadrant.get("y"), lanes))
    return result


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set[str]:
    quadrants = _quadrants_lanes(job.cs_amount)
    most_visited = _most_visited_lanes()  # já ordenado por relevância no arquivo

    quadrant_filled = [False] * len(quadrants)
    chosen: set[str] = set()

    for lane_id in most_visited:
        if len(chosen) >= len(quadrants):
            break
        if lane_id in chosen:
            continue

        for idx, (_x, _y, lanes) in enumerate(quadrants):
            if quadrant_filled[idx]:
                continue
            if lane_id in lanes:
                quadrant_filled[idx] = True
                chosen.add(lane_id)
                break

    if len(chosen) < len(quadrants):
        raise RuntimeError(
            f"Só {len(chosen)}/{len(quadrants)} quadrantes preenchidos -- "
            f"mostVisited.xml não cobre todas as {len(quadrants)} quadrantes "
            f"(job={job.manifest_id})."
        )
    return chosen
