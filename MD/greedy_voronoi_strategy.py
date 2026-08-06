"""
Approach 'greedyvoronoi' -- substitui
findingStationsGreedyVoronoi.py::findCSinRegions.

AO CONTRÁRIO de random/pseudorandom, este approach NÃO tem crescimento
incremental: cada cs_amount sorteia seu próprio diagrama de Voronoi do
zero, de forma independente. Isso é intencional -- diferente do 'greedy'
(que não usa sorteio nenhum, então nunca teve esse problema), o
'greedyvoronoi' usa np.random.uniform para posicionar os pontos do
diagrama, mas foi decidido manter o comportamento original aqui: ao
crescer de 9 para 16 estações, as posições podem mudar por completo (sem
garantia de que as 9 antigas permaneçam).

Por isso a seed usada aqui inclui `cs_amount` na chave
(StationSeedRegistry.apply(repetition, cs_amount)) -- diferente de
random/pseudorandom, que usam só `repetition`. Isso garante pelo menos que
10min/20min/40min/60min de uma mesma (cs_amount, repetition) continuem
usando o MESMO diagrama entre si (comparação pareada no tempo de recarga),
só não entre cs_amounts diferentes.

O resultado de cada (repetition, cs_amount) é cacheado em disco
(stations_evolution/seed_<repetition>/<cs>stations.xml, reaproveitando o
mesmo local de arquivo que random/pseudorandom usam para os estágios --
aqui cada arquivo é independente, não uma cadeia) para não recalcular o
mesmo diagrama para cada combinação de percentage/minutes que passar por
aqui.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from functools import lru_cache

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from scipy.spatial import Voronoi, voronoi_plot_2d

import config
from sim_job import SimJob
from station_strategies import evolution
from station_strategies.greedy_strategy import _most_visited_lanes


@lru_cache(maxsize=1)
def _conv_boundary():
    root = ET.parse(config.NET_FILE).getroot()
    conv_boundary = root.find(".//location").attrib["convBoundary"]
    x_min, y_min, x_max, y_max = map(float, conv_boundary.split(","))
    return x_min, y_min, x_max, y_max


@lru_cache(maxsize=1)
def _lanes_and_coordinates():
    root = ET.parse(config.NET_FILE).getroot()
    lanes = {}
    for edge in root.findall(".//edge[@type]"):
        for lane in edge.findall("./lane"):
            coords_raw = lane.attrib["shape"].split(" ")
            points = []
            for pair in coords_raw:
                if not pair.strip():
                    continue
                x_str, y_str = pair.split(",")
                points.append((float(x_str), float(y_str)))
            lanes[lane.attrib["id"]] = points
    return lanes


def _find_regions(coords, vor: Voronoi) -> set:
    regions = set()
    for x, y in coords:
        point = np.array([x, y])
        nearest_idx = np.argmin(np.linalg.norm(vor.points - point, axis=1))
        regions.add(vor.point_region[nearest_idx])
    return regions


def _save_diagnostic(repetition: int, cs_amount: int, points: np.ndarray,
                      vor: Voronoi, ok: bool) -> None:
    out_dir = config.voronoi_stations_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"seed_{repetition}_{cs_amount}stations"

    voronoi_plot_2d(vor, line_colors="k", line_style="--", show_vertices=False)
    for point, region_index in zip(points, vor.point_region):
        plt.text(point[0], point[1], f"Região {region_index}", color="red",
                  ha="center", va="center")
    plt.savefig(out_dir / f"{tag}.png")
    plt.close()

    (out_dir / f"FLAGARCHIVE-{tag}.txt").write_text("deu certo" if ok else "não deu certo")


def _build(cs_amount: int) -> set:
    x_min, y_min, x_max, y_max = _conv_boundary()
    points = np.random.uniform([x_min, y_min], [x_max, y_max], size=(cs_amount, 2))
    vor = Voronoi(points)

    most_visited = _most_visited_lanes()
    lanes_and_coords = _lanes_and_coordinates()

    region_filled = {region: False for region in vor.point_region}
    chosen: set = set()

    for lane_id in most_visited:
        if len(chosen) >= cs_amount:
            break
        if lane_id not in lanes_and_coords:
            continue
        touched = _find_regions(lanes_and_coords[lane_id], vor)
        for region in touched:
            if not region_filled.get(region, True):
                region_filled[region] = True
                chosen.add(lane_id)
                break

    ok = len(chosen) >= cs_amount
    return chosen, points, vor, ok


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set:
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition, job.cs_amount)

    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount)
    if cached is not None:
        return cached

    chosen, points, vor, ok = _build(job.cs_amount)
    _save_diagnostic(job.repetition, job.cs_amount, points, vor, ok)

    if not ok:
        raise RuntimeError(
            f"Só {len(chosen)}/{job.cs_amount} regiões preenchidas em "
            f"greedyvoronoi/seed_{job.repetition}/{job.cs_amount}."
        )

    evolution.save_stage(job.approach, job.repetition, job.cs_amount, chosen)
    return chosen
