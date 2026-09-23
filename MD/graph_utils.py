"""
Construção do grafo de roteamento a partir do cologne.net.xml.

No código original essa mesma lógica existia, praticamente idêntica, em
7 lugares: diagnosis.py, genetic_algorithm.py, main.py (como generate_graph),
e inline dentro de findingPseudoRandom.py, findingRandom.py,
findingStationsGreedy.py/findingStationsGreedyVoronoi.py e
generatingPseudoRandom.py. Esta é a única versão daqui pra frente.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import networkx as nx
from bs4 import BeautifulSoup

import config


def build_graph_from_netfile(netfile: Path | str) -> nx.DiGraph:
    """
    Lê o .net.xml do SUMO e monta um DiGraph onde cada edge do net vira um
    nó do grafo, ligado aos edges seguintes via as tags <connection>.
    O atributo 'length' de cada aresta vem do comprimento da lane -- usado
    pelo roteamento em tempo de simulação (ver simulation.py::decide_station/
    reroute, que faz Dijkstra ponderado por distância real).
    """
    netfile = Path(netfile)
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")

    edges_length: dict[str, int] = {}
    for edge_tag in soup.find_all("edge"):
        edge_id = edge_tag["id"]
        lane_tag = edge_tag.find("lane")
        if lane_tag is None:
            continue
        edges_length[edge_id] = int(float(lane_tag["length"]))

    graph = nx.DiGraph()
    for connection_tag in soup.find_all("connection"):
        source_edge = connection_tag["from"]
        dest_edge = connection_tag["to"]
        if source_edge in edges_length:
            graph.add_edge(
                source_edge,
                dest_edge,
                length=edges_length[source_edge],
            )
    return graph


@lru_cache(maxsize=1)
def default_graph() -> nx.DiGraph:
    """
    Cache em processo -- útil quando várias combinações do mesmo approach
    são geradas em sequência no mesmo processo (evita reparsear o net.xml,
    ~70 mil nós, a cada combinação). Em execução paralela (multiprocessing),
    cada worker tem seu próprio cache -- combine com um `initializer` que
    chama esta função uma vez por worker, como já é feito hoje em
    genetic_algorithm.py.
    """
    return build_graph_from_netfile(config.NET_FILE)


def get_giant_component(graph: nx.DiGraph) -> nx.DiGraph:
    """Maior componente fortemente conexo -- evita que nós inalcançáveis
    do grafo completo distorçam buscas de caminho/fitness."""
    components = sorted(nx.strongly_connected_components(graph), key=len, reverse=True)
    return graph.subgraph(components[0]).copy()


@lru_cache(maxsize=1)
def default_giant_graph() -> nx.DiGraph:
    """
    Versão cacheada de get_giant_component(default_graph()) -- é este o
    "grafo de trabalho" usado na fase de SELEÇÃO de estação, pelas 5
    station strategies (ver cli.py: generate_combo/run_single), não o
    grafo completo.
    """
    return get_giant_component(default_graph())


@lru_cache(maxsize=1)
def list_connections(netfile: Path | str = None) -> tuple[dict, ...]:
    """
    Lista bruta das tags <connection> do net.xml, com 'from'/'to'/'fromLane'
    preservados -- necessário para a estratégia 'random', que sorteia
    conexões inteiras (não só edges) para formar o id "edge_lane" da
    estação. Cacheado por processo (mesmo motivo do default_graph()).
    """
    netfile = Path(netfile) if netfile else config.NET_FILE
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")
    return tuple(
        {"from": tag["from"], "to": tag["to"], "fromLane": tag.get("fromLane", "0")}
        for tag in soup.find_all("connection")
    )


@lru_cache(maxsize=1)
def lanes_with_outgoing_connection(netfile: Path | str = None) -> frozenset:
    """
    Conjunto de ids de LANE (não edge) que são a origem de pelo menos uma
    <connection> no net.xml -- ou seja, lanes que, uma vez ocupadas por um
    veículo estacionado pra recarregar, permitem que ele continue viagem
    depois.

    Isso é diferente (e mais estrito) do que "o edge pertence ao componente
    gigante" (default_giant_graph): build_graph_from_netfile monta o grafo
    no nível de EDGE e ignora 'fromLane' -- um edge com 2 lanes, onde só a
    lane 1 tem conexão de saída, aparece no grafo como conectado mesmo
    assim, e a lane 0 (sem conexão nenhuma) passa despercebida pela checagem
    de componente gigante feita pelas station strategies.

    Uma estação posicionada numa lane SEM conexão de saída própria prende
    para sempre qualquer veículo que for recarregar ali -- ele termina de
    carregar e não tem como seguir viagem, gerando "performs emergency stop
    ... because there is no connection to the next edge" a cada passo de
    simulação, indefinidamente (foi exatamente o que travou 5 simulações do
    pseudorandom presas na lane 96049309#0_0, seed 4/9cs, 2026-09-19 --
    ela pertencia ao componente gigante pelo edge, mas não tinha nenhuma
    <connection> saindo dela mesma).

    Use este conjunto como filtro ADICIONAL ao componente gigante, nunca
    como substituto -- o componente gigante ainda garante que o EDGE como
    um todo está bem conectado ao resto do mapa; este conjunto garante que
    a LANE específica escolhida tem por onde sair.
    """
    netfile = Path(netfile) if netfile else config.NET_FILE
    return frozenset(
        f"{c['from']}_{c['fromLane']}" for c in list_connections(netfile)
    )


@lru_cache(maxsize=1)
def edge_to_lanes(netfile: Path | str = None) -> dict[str, tuple[str, ...]]:
    """
    Mapeia cada EDGE id pra tupla ordenada dos ids de LANE que pertencem a
    ele (na ordem em que aparecem no net.xml -- tipicamente índice 0, 1,
    2...). Necessário pro approach 'genetic', que recebe apenas edge ids de
    um algoritmo externo (o GA opera no nível de rua/edge, não de lane
    específica) e precisa escolher UMA lane concreta desse edge pra virar
    estação -- ver docstring de genetic_strategy.py.
    """
    netfile = Path(netfile) if netfile else config.NET_FILE
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")
    result: dict[str, tuple[str, ...]] = {}
    for edge_tag in soup.find_all("edge"):
        edge_id = edge_tag["id"]
        lane_ids = tuple(lane_tag["id"] for lane_tag in edge_tag.find_all("lane"))
        if lane_ids:
            result[edge_id] = lane_ids
    return result


@lru_cache(maxsize=1)
def lane_lengths(netfile: Path | str = None) -> dict:
    """
    Comprimento de cada LANE (não edge) do net.xml, indexado pelo id da
    própria lane (ex. "24484032#0_0"). Usado para validar se uma estação
    candidata comporta `max_vehicles_per_cs` veículos sem depender de uma
    simulação SUMO viva (traci.lane.getLength) -- a fase de geração roda
    antes de qualquer SUMO ser iniciado.
    """
    netfile = Path(netfile) if netfile else config.NET_FILE
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")
    lengths = {}
    for edge_tag in soup.find_all("edge"):
        for lane_tag in edge_tag.find_all("lane"):
            lengths[lane_tag["id"]] = float(lane_tag["length"])
    return lengths


@lru_cache(maxsize=1)
def lane_shapes(netfile: Path | str = None) -> dict[str, tuple[tuple[float, float], ...]]:
    """
    Mapeia cada LANE id para sua geometria -- a lista de pontos (x, y) do
    atributo 'shape' no net.xml, na ordem em que aparecem (do início ao fim
    da lane). Usado só para posicionar as vagas de estacionamento fora da
    via (<space> de uma parkingArea com onRoad="false") coladas à lane real,
    em vez de coordenadas arbitrárias -- ver parking_space_positions().
    """
    netfile = Path(netfile) if netfile else config.NET_FILE
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")
    shapes: dict[str, tuple[tuple[float, float], ...]] = {}
    for edge_tag in soup.find_all("edge"):
        for lane_tag in edge_tag.find_all("lane"):
            shape_raw = lane_tag.get("shape")
            if not shape_raw:
                continue
            points = tuple(
                tuple(map(float, pair.split(",")))
                for pair in shape_raw.split(" ")
                if pair.strip()
            )
            if points:
                shapes[lane_tag["id"]] = points
    return shapes


def parking_space_positions(shape: tuple[tuple[float, float], ...], n: int,
                             offset: float = 1.5, spacing: float = 2.5) -> list[tuple[float, float]]:
    """
    Calcula N posições (x, y) para as vagas (<space>) de uma parkingArea
    fora da via (onRoad="false"), coladas à lane real -- um pequeno
    deslocamento perpendicular ao ponto médio da lane (offset, em metros),
    em grade de até 3 colunas por linha (spacing entre vagas).

    IMPORTANTE: isso é puramente cosmético/estrutural -- evita que todas as
    vagas fiquem desenhadas exatamente sobrepostas no sumo-gui. NÃO afeta
    roteamento nem a distância percorrida pelos veículos: a rota é
    calculada pelo grafo (decide_station/reroute em simulation.py, via
    Dijkstra por 'length') até a LANE da parkingArea, não até a coordenada
    do <space> -- a posição exata da vaga não entra nesse cálculo.

    Fallback: se a lane não tiver geometria (`shape` vazio -- não deveria
    acontecer para uma lane real do net.xml, mas por segurança), usa (0, 0)
    como base em vez de falhar.
    """
    if len(shape) < 2:
        x0, y0 = shape[0] if shape else (0.0, 0.0)
        return [(x0 + i * spacing, y0) for i in range(n)]

    x1, y1 = shape[0]
    x2, y2 = shape[-1]
    dx, dy = x2 - x1, y2 - y1
    lane_len = math.hypot(dx, dy) or 1.0
    dir_x, dir_y = dx / lane_len, dy / lane_len   # vetor unitário ao longo da lane
    perp_x, perp_y = -dir_y, dir_x                # vetor unitário perpendicular

    mid_x = (x1 + x2) / 2.0
    mid_y = (y1 + y2) / 2.0

    cols = 3
    positions = []
    for i in range(n):
        row, col = divmod(i, cols)
        along = (col - (cols - 1) / 2.0) * spacing
        across = offset + row * spacing
        x = mid_x + dir_x * along + perp_x * across
        y = mid_y + dir_y * along + perp_y * across
        positions.append((x, y))
    return positions
