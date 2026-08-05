import random
import math
import networkx as nx
from bs4 import BeautifulSoup


def generate_graph(netfile):
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")

    edges_length = {}
    for edge_tag in soup.findAll("edge"):
        edge_id = edge_tag["id"]
        lane_tag = edge_tag.find("lane")
        if lane_tag is None:
            continue
        edges_length[edge_id] = int(float(lane_tag["length"]))

    graph = nx.DiGraph()
    for connection_tag in soup.findAll("connection"):
        source_edge = connection_tag["from"]
        dest_edge = connection_tag["to"]
        if source_edge in edges_length:
            graph.add_edge(
                source_edge, dest_edge,
                length=edges_length[source_edge],
                weight=1,
            )
    return graph


def distance_direct(graph, node, station):
    """Método antigo: shortest_path_length direto no grafo original."""
    try:
        return nx.shortest_path_length(graph, source=node, target=station, weight="length")
    except nx.NetworkXNoPath:
        return math.inf


def main():
    netfile = "../input/cologne.net.xml"
    graph = generate_graph(netfile)
    nodes = list(graph.nodes)

    # mesmas 3 estações que apareceram no seu resultado
    stations = ['32808311#0', '132531140#4', '70843075']

    # verifica se as estações existem no grafo
    for s in stations:
        print(f"Estação {s} está no grafo?", s in graph.nodes)

    # amostra de nós aleatórios para testar
    sample_nodes = random.sample(nodes, 30)

    reversed_graph = graph.reverse(copy=False)
    dist_reversed = nx.multi_source_dijkstra_path_length(reversed_graph, stations, weight="length")

    print(f"\n{'nó':30} {'direto (lento)':>15} {'invertido (rápido)':>20} {'bateu?':>8}")
    mismatches = 0
    unreachable_direct = 0
    unreachable_reversed = 0

    for node in sample_nodes:
        d_direct = min(distance_direct(graph, node, s) for s in stations)
        d_reversed = dist_reversed.get(node, math.inf)

        if d_direct == math.inf:
            unreachable_direct += 1
        if d_reversed == math.inf:
            unreachable_reversed += 1

        ok = "OK" if d_direct == d_reversed else "DIFERENTE!"
        if ok == "DIFERENTE!":
            mismatches += 1
        print(f"{node:30} {d_direct!s:>15} {d_reversed!s:>20} {ok:>8}")

    print(f"\nTotal de diferenças: {mismatches} de {len(sample_nodes)}")
    print(f"Inalcançáveis (método direto): {unreachable_direct}")
    print(f"Inalcançáveis (método invertido): {unreachable_reversed}")

    # também mostra quantos nós no grafo inteiro são alcançados pelo multi-source
    total_nodes = len(nodes)
    reachable = len(dist_reversed)
    print(f"\nNo grafo inteiro ({total_nodes} nós):")
    print(f"Alcançáveis a partir das estações (via grafo invertido): {reachable}")
    print(f"Inalcançáveis: {total_nodes - reachable}")


if __name__ == "__main__":
    main()