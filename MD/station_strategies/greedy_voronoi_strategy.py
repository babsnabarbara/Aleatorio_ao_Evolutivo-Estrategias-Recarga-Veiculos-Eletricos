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
from scipy.spatial import Voronoi

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


def _plot_voronoi_manual(ax, vor: Voronoi) -> None:
    """
    Desenha o diagrama de Voronoi na mão (pontos + arestas finitas),
    sem depender de scipy.spatial.voronoi_plot_2d -- essa função tem um bug
    conhecido em algumas versões do scipy (o decorador interno
    `_held_figure` quebra com "takes from 2 to 3 positional arguments but 4
    were given", mesmo passando `ax` explícito). Isso é só um PNG de
    diagnóstico, não precisa da função pronta: desenhamos os pontos de
    entrada e as arestas finitas do diagrama (arestas que vão até o
    infinito são só puladas -- não afeta a leitura visual das regiões).
    """
    ax.plot(vor.points[:, 0], vor.points[:, 1], "o", markersize=4, color="tab:blue")
    for ridge in vor.ridge_vertices:
        if -1 in ridge:
            continue  # aresta infinita -- não desenhável sem extrapolar, pula
        p1 = vor.vertices[ridge[0]]
        p2 = vor.vertices[ridge[1]]
        ax.plot([p1[0], p2[0]], [p1[1], p2[1]], "k--", linewidth=0.8)


def _save_diagnostic(repetition: int, cs_amount: int, points: np.ndarray,
                      vor: Voronoi, ok: bool) -> None:
    out_dir = config.voronoi_stations_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"seed_{repetition}_{cs_amount}stations"

    fig, ax = plt.subplots()
    _plot_voronoi_manual(ax, vor)
    for point, region_index in zip(points, vor.point_region):
        ax.text(point[0], point[1], f"Região {region_index}", color="red",
                 ha="center", va="center")
    fig.savefig(out_dir / f"{tag}.png")
    plt.close(fig)

    (out_dir / f"FLAGARCHIVE-{tag}.txt").write_text("deu certo" if ok else "não deu certo")


def _build(cs_amount: int, graph: nx.DiGraph) -> set:
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
        # lane_id[:-2] converte lane id -> edge id (remove o sufixo "_0")
        if lane_id[:-2] not in graph:
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
    """
    Se sobrarem regiões sem nenhuma lane visitada elegível tocando nelas, o
    resultado pode ter menos de `cs_amount` estações -- não é erro (mesma
    decisão aplicada ao approach 'greedy'). O `FLAGARCHIVE-*.txt` continua
    registrando "deu certo"/"não deu certo" como diagnóstico, só não trava
    mais a execução.

    FIX: agora também exige que a lane pertença ao componente gigante do
    mapa (o `graph` recebido já vem restrito a esse componente -- ver
    cli.py/graph_utils.default_giant_graph), mesmo padrão unificado nos 5
    approaches.

    NÃO filtra por capacidade/comprimento de lane -- a capacidade real de
    cada estação é calculada depois, na hora de gerar o .add.xml (ver
    graph_utils.realized_capacity).
    """
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition, job.cs_amount)

    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount)
    if cached is not None:
        return cached

    chosen, points, vor, ok = _build(job.cs_amount, graph)
    _save_diagnostic(job.repetition, job.cs_amount, points, vor, ok)

    evolution.save_stage(job.approach, job.repetition, job.cs_amount, chosen)
    return chosen