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

    IMPORTANTE: isso é diferente do grafo usado na fase de SIMULAÇÃO (ver
    cli.py: _worker_graph / simulation.run_simulation), que continua sendo
    o grafo completo -- um veículo pode legitimamente estar em qualquer
    edge do mapa quando é sorteado para recarregar, então o cálculo de
    rota até a estação precisa poder buscar a partir de qualquer posição,
    não só dentro do componente gigante.

    FIX: esta restrição já era usada internamente pelo algoritmo genético
    original (get_giant_component/candidate_nodes ali) -- mas nunca tinha
    sido aplicada às outras 4 estratégias, que validavam conectividade de
    um jeito mais fraco e inconsistente entre si (random/pseudorandom só
    conferiam se as 3 lanes sorteadas formavam ciclo ENTRE SI, sem garantir
    que pertenciam ao núcleo bem conectado do mapa; greedy/greedyvoronoi
    não conferiam nada; genetic_strategy.py só conferia "existe no grafo
    completo"). Unificar todos os 5 approaches para escolherem estações
    apenas dentro do mesmo componente gigante corrige essa inconsistência.

    Efeito colateral útil: como todo par de nós dentro do componente
    fortemente conexo é, por definição, mutuamente alcançável, a checagem
    de ciclo (_forms_cycle) em random/pseudorandom deixa de ser necessária
    -- basta o candidato pertencer a este grafo.
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


def realized_capacity(lane_id: str, max_vehicles_per_cs: int,
                       lane_lengths_dict: dict, vehicle_length: float) -> int:
    """
    Capacidade REAL de uma estação, dado o comprimento físico da lane onde
    ela vai ficar: min(max_vehicles_per_cs, quantos veículos cabem de
    verdade), nunca menos que 1.

    Decisão metodológica (não um bug/limitação técnica): em vez de REJEITAR
    uma posição de estação por não caber `max_vehicles_per_cs` veículos (o
    que travaria approaches sem candidato alternativo, como o genetic, cujas
    posições vêm de um algoritmo externo já publicado), a capacidade da
    estação se ADAPTA ao que a rua realmente comporta -- min() com o pedido,
    nunca inventando espaço que não existe. Isso espelha uma restrição real
    de infraestrutura (não dá pra instalar uma estação de 6 vagas numa rua
    que só cabe 2) e se aplica igualmente aos 5 approaches -- nenhum se
    beneficia ou é prejudicado sistematicamente por isso.

    A seleção de ONDE colocar uma estação não depende mais deste valor --
    qualquer lane escolhida por qualquer approach é aceita; só a capacidade
    escrita no .add.xml (ver io_utils.write_add_file) é que se ajusta à
    geometria real de cada uma.
    """
    length = lane_lengths_dict.get(lane_id)
    if length is None:
        return 1
    fits = int(length // vehicle_length)
    return max(1, min(max_vehicles_per_cs, fits))