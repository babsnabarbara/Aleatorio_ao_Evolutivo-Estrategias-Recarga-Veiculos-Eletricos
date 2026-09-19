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

FIX: fallback geométrico para regiões de Voronoi sem nenhuma lane visitada
elegível. Antes, essas regiões ficavam permanentemente sem estação (mesma
decisão tomada em greedy_strategy.py, documentada ali e aqui). Agora, cada
região que sobra vazia depois da fase por visitação recebe a lane mais
próxima do PRÓPRIO NÚCLEO da região -- ou seja, o ponto (x, y) sorteado por
np.random.uniform que deu origem àquela região do diagrama de Voronoi. Não
é uma escolha arbitrária de "centro": por definição de um diagrama de
Voronoi, uma região é exatamente o conjunto de pontos mais próximos do seu
núcleo do que de qualquer outro -- o núcleo já É o centro geométrico exato
da região, sem precisar calcular nada a mais (ao contrário do 'greedy', que
precisou calcular o centroide do quadrante na mão). Entre TODAS as lanes do
mapa (não só as visitadas) que são elegíveis (componente gigante, ainda não
escolhidas) e cujo ponto mais próximo entre os `cs_amount` núcleos é o
núcleo dessa região, escolhe a mais próxima desse núcleo. Uma região só
continua sem estação se não tiver NENHUMA lane elegível nessas condições
(caso bem mais raro que antes).

FIX (2026-09-19): tanto o loop principal quanto o fallback só conferiam
"lane_id[:-2] not in graph" -- se o EDGE da lane pertence ao componente
gigante -- sem nunca checar se a LANE especificamente escolhida tem alguma
<connection> de saída própria. Mesmo bug já corrigido em
graph_utils.py/pseudorandom_strategy.py/greedy_strategy.py: um edge com 2+
lanes pode estar bem conectado ao resto do mapa via UMA lane, enquanto
outra lane do mesmo edge não tem nenhuma conexão de saída -- uma estação
ali prende pra sempre qualquer veículo que for recarregar. O fallback aqui
era o ponto mais exposto: escolhe a lane mais próxima do NÚCLEO da região
entre TODAS as lanes do mapa, e o núcleo é um ponto sorteado livremente
(np.random.uniform) que pode cair bem perto -- ou até coincidir -- com uma
lane sem saída nenhuma. Agora as duas checagens também exigem lane_id in
graph_utils.lanes_with_outgoing_connection(), sem mudar o critério de
"mais próxima do núcleo" em si, só reduzindo o pool de candidatas
elegíveis -- mesmo padrão usado nos outros approaches.
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
import graph_utils
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


def _lane_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Ponto representativo de uma lane -- média dos pontos do seu shape.
    Usado só pelo fallback (a fase principal usa _find_regions, que olha
    todos os pontos do shape, não um único representante)."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return sum(xs) / len(xs), sum(ys) / len(ys)


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
    connected_lanes = graph_utils.lanes_with_outgoing_connection()

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
        if lane_id not in connected_lanes:
            continue  # lane sem conexão de saída própria -- veículo ficaria preso
        touched = _find_regions(lanes_and_coords[lane_id], vor)
        for region in touched:
            if not region_filled.get(region, True):
                region_filled[region] = True
                chosen.add(lane_id)
                break

    # Fallback: regiões que sobraram vazias recebem a lane mais próxima do
    # PRÓPRIO NÚCLEO da região -- ver docstring do módulo. Percorre TODAS
    # as lanes do mapa (não só as mais visitadas), já que uma região vazia
    # por definição não tem nenhuma lane visitada elegível dentro dela.
    empty_regions = {region for region, filled in region_filled.items() if not filled}
    if empty_regions:
        best_by_region: dict[int, tuple[float, str]] = {}
        for lane_id, coords in lanes_and_coords.items():
            if lane_id in chosen:
                continue
            if lane_id[:-2] not in graph:
                continue
            if lane_id not in connected_lanes:
                continue  # idem -- não deixa o fallback escolher um beco sem saída
            lane_point = np.array(_lane_centroid(coords))
            distances = np.linalg.norm(vor.points - lane_point, axis=1)
            nearest_point_idx = int(np.argmin(distances))
            region = vor.point_region[nearest_point_idx]
            if region not in empty_regions:
                continue
            distance = float(distances[nearest_point_idx])
            current_best = best_by_region.get(region)
            if current_best is None or distance < current_best[0]:
                best_by_region[region] = (distance, lane_id)

        for region, (_distance, lane_id) in best_by_region.items():
            region_filled[region] = True
            chosen.add(lane_id)

    ok = len(chosen) >= cs_amount
    return chosen, points, vor, ok


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set:
    """
    FALLBACK: regiões que sobram vazias depois da fase por visitação
    recebem a lane mais próxima do núcleo da própria região -- ver
    docstring do módulo. Uma região só continua sem estação se não tiver
    NENHUMA lane elegível (visitada ou não), caso bem mais raro que antes.
    O `FLAGARCHIVE-*.txt` continua registrando "deu certo"/"não deu certo"
    como diagnóstico com base em `len(chosen) >= cs_amount`.

    FIX: agora também exige que a lane pertença ao componente gigante do
    mapa (o `graph` recebido já vem restrito a esse componente -- ver
    cli.py/graph_utils.default_giant_graph), mesmo padrão unificado nos 5
    approaches.

    FIX (2026-09-19): e que a lane tenha conexão de saída própria -- ver
    docstring do módulo.

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
