"""
Construção do grafo de roteamento a partir do cologne.net.xml.

No código original essa mesma lógica existia, praticamente idêntica, em
7 lugares: diagnosis.py, genetic_algorithm.py, main.py (como generate_graph),
e inline dentro de findingPseudoRandom.py, findingRandom.py,
findingStationsGreedy.py/findingStationsGreedyVoronoi.py e
generatingPseudoRandom.py. Esta é a única versão daqui pra frente.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import networkx as nx
from bs4 import BeautifulSoup

import config


def build_graph_from_netfile(netfile: Path | str) -> nx.DiGraph:
    """
    Lê o .net.xml do SUMO e monta um DiGraph onde cada edge do net vira um
    nó do grafo, ligado aos edges seguintes via as tags <connection>.
    O atributo 'length' de cada aresta vem do comprimento da lane; 'weight'
    é fixo em 1 (usado pela busca de ciclo das estratégias de estação, que
    conta número de saltos, não distância).
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
                weight=1,
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


def get_connections(netfile: Path | str = None) -> list[dict[str, str]]:
    """
    Lista de <connection> crua do net.xml (from/to/fromLane), usada pelas
    estratégias random/pseudorandom para montar candidatos a estação
    (id da estação = "<edge>_<fromLane>", como no código original).
    """
    netfile = Path(netfile) if netfile is not None else config.NET_FILE
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")
    return [
        {
            "from": c["from"],
            "to": c["to"],
            "fromLane": c.get("fromLane", "0"),
        }
        for c in soup.find_all("connection")
    ]


def get_lane_lengths(netfile: Path | str = None) -> dict[str, float]:
    """
    Comprimento de cada LANE individual (não do edge) -- necessário para o
    critério de capacidade mínima da estratégia pseudorandom
    (comprimento da lane >= maxVehiclesPerCS * comprimento do veículo).
    """
    netfile = Path(netfile) if netfile is not None else config.NET_FILE
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")
    lengths: dict[str, float] = {}
    for edge_tag in soup.find_all("edge"):
        for lane_tag in edge_tag.find_all("lane"):
            lengths[lane_tag["id"]] = float(lane_tag["length"])
    return lengths


def has_path(graph: nx.DiGraph, source: str, target: str) -> bool:
    try:
        nx.dijkstra_path(graph, source, target)
        return True
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return False


def forms_triangle_cycle(graph: nx.DiGraph, a: str, b: str, c: str) -> bool:
    """
    Testa se os 3 edges formam um ciclo alcançável (a->b->c->a) no grafo.
    Usado como critério de "candidato válido" pelas estratégias
    random/pseudorandom -- evita escolher uma lane isolada/sem saída como
    estação de recarga.
    """
    return has_path(graph, a, b) and has_path(graph, b, c) and has_path(graph, c, a)


def get_giant_component(graph: nx.DiGraph) -> nx.DiGraph:
    """Maior componente fortemente conexo -- evita que nós inalcançáveis
    do grafo completo distorçam buscas de caminho/fitness."""
    components = sorted(nx.strongly_connected_components(graph), key=len, reverse=True)
    return graph.subgraph(components[0]).copy()


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


def has_min_capacity(lane_id: str, max_vehicles_per_cs: int,
                      lane_lengths_dict: dict, vehicle_length: float) -> bool:
    """
    Confere se `lane_id` tem comprimento físico suficiente pra `roadsideCapacity`
    (a parkingArea da estação, ver io_utils.write_add_file/simulation.py)
    realmente caber `max_vehicles_per_cs` veículos, sem estourar o trecho da
    lane -- que, pelo modo como o SUMO distribui as vagas de uma parkingArea
    sem <space> customizado, é limitado ao próprio comprimento da lane.

    Comprovado empiricamente (não só teoricamente) que ignorar isso causa
    'skips stop' seguido de teleporte quando a lane é curta demais pro
    max_vehicles_per_cs pedido -- por isso essa checagem vale pra QUALQUER
    approach que escolhe estação, não só o pseudorandom (que já tinha essa
    lógica desde o código original).

    Usado por: pseudorandom, random, greedy, greedyvoronoi (como filtro na
    escolha de candidatos) e genetic (como validação pós-hoc, já que as
    posições vêm de fora e não há candidato alternativo pra tentar).
    """
    length = lane_lengths_dict.get(lane_id)
    if length is None:
        return False
    return (length / vehicle_length) >= max_vehicles_per_cs