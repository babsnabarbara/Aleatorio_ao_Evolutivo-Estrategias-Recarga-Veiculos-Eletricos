#!/usr/bin/env python3
"""
check_station_load.py

Hipótese nova (depois de descartar capacidade de lane e via muito
visitada): cada veículo é roteado pra estação de carga MAIS PRÓXIMA em
número de saltos (ver simulation.py::decide_station -- Dijkstra com
weight=1 em TODAS as arestas, ou seja, contagem de arestas no caminho,
não distância física). Isso significa que a demanda não é dividida
igualmente entre as N estações -- é dividida pela "área de influência"
de cada uma no grafo de saltos, que pode ser bem desigual mesmo se as
estações estiverem espacialmente bem distribuídas.

Esse script reproduz esse roteamento OFFLINE (sem precisar rodar SUMO):
lê o .add.xml (estações) e o sortedCars (veículos sorteados pra
recarregar) de um job específico, e para cada veículo calcula qual
estação seria escolhida -- exatamente a mesma lógica de
decide_station() -- e conta quantos veículos "caem" em cada estação.

Se uma estação específica concentrar uma fração desproporcional dos
veículos, isso é evidência direta de que ela fica sobrecarregada (fila
de carros esperando vaga cresce mais rápido do que esvazia), o que
combina exatamente com o padrão observado: só trava em minutes/percentage
mais altos (mais tempo de recarga = fila esvazia mais devagar; mais
veículos = fila cresce mais rápido), e só na disposição
(repetition, cs_amount) específica que tem essa estação desbalanceada.

Uso (rodar de dentro de ~/TCC/MD):
    python3 check_station_load.py --approach pseudorandom --minutes 20 \\
        --percentage 25 --cs-amount 9 --repetition 4
"""
import argparse
import xml.etree.ElementTree as ET
import re

import networkx as nx

import config
import graph_utils
from sim_job import SimJob

_ATTR_RE = {
    name: re.compile(rf'{name}="([^"]*)"')
    for name in ("id", "depart", "from", "to")
}


def read_charging_stations(add_file) -> dict:
    root = ET.parse(add_file).getroot()
    stations = {}
    for pa in root.findall(".//parkingArea"):
        stations[pa.get("id")] = {"lane": pa.get("lane")}
    return stations


def read_sorted_cars(sorted_cars_file) -> dict:
    trips = {}
    with open(sorted_cars_file, "r", encoding="utf-8") as f:
        for line in f:
            if "<trip" not in line:
                continue
            attrs = {}
            for name, pattern in _ATTR_RE.items():
                m = pattern.search(line)
                if m:
                    attrs[name] = m.group(1)
            trip_id = attrs.get("id")
            if trip_id:
                trips[trip_id] = attrs
    return trips


def edge_of_lane(graph, lane_id):
    # mesma convenção usada no resto do projeto: lane id -> edge id
    # removendo o sufixo "_N"
    return lane_id.rsplit("_", 1)[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--approach", required=True)
    ap.add_argument("--minutes", type=int, required=True)
    ap.add_argument("--percentage", type=int, required=True)
    ap.add_argument("--cs-amount", type=int, required=True)
    ap.add_argument("--repetition", type=int, required=True)
    ap.add_argument("--vehicles", type=int, default=config.DEFAULT_VEHICLES)
    ap.add_argument("--max-vehicles-per-cs", type=int,
                     default=config.DEFAULT_MAX_VEHICLES_PER_CS)
    args = ap.parse_args()

    job = SimJob(
        approach=args.approach, minutes=args.minutes, cs_amount=args.cs_amount,
        percentage=args.percentage, repetition=args.repetition,
        vehicles=args.vehicles, max_vehicles_per_cs=args.max_vehicles_per_cs,
        seed=0,  # não usado aqui, só pra satisfazer o dataclass
    )

    if not job.add_file.exists():
        print(f"Não achei {job.add_file}")
        return
    if not job.sorted_cars_file.exists():
        print(f"Não achei {job.sorted_cars_file}")
        return

    print("Carregando grafo completo do mapa...")
    graph = graph_utils.default_graph()

    stations = read_charging_stations(job.add_file)
    for info in stations.values():
        info["edge"] = edge_of_lane(graph, info["lane"])

    cars = read_sorted_cars(job.sorted_cars_file)
    print(f"{len(stations)} estações, {len(cars)} veículos sorteados pra recarregar\n")

    # Truque de eficiência (mesmo usado em fitness_function do genetic):
    # em vez de rodar um Dijkstra por veículo x por estação (lento demais
    # pra milhares de veículos), roda UM único multi_source_dijkstra a
    # partir das estações, no grafo REVERSO -- isso dá, pra cada nó do
    # mapa, a distância (e qual estação) até a estação mais próxima, tudo
    # de uma vez. Resultado idêntico ao decide_station() original, rodado
    # veículo por veículo -- só muito mais rápido.
    station_edges = {info["edge"]: sid for sid, info in stations.items()}
    reversed_graph = graph.reverse(copy=False)
    print("Calculando estação mais próxima de cada ponto do mapa (uma vez só)...")
    _, paths = nx.multi_source_dijkstra(
        reversed_graph, list(station_edges.keys()), weight="weight"
    )

    counts = {sid: 0 for sid in stations}
    unreachable = 0

    for car_id, attrs in cars.items():
        source = attrs.get("from")
        if not source or source not in paths:
            unreachable += 1
            continue
        nearest_edge = paths[source][0]  # primeiro nó do caminho = a estação usada
        sid = station_edges[nearest_edge]
        counts[sid] += 1

    total = sum(counts.values())
    print(f"\n{'estação (lane)':<20}{'veículos_atribuídos':<20}{'%_do_total':<12}")
    for sid, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        lane = stations[sid]["lane"]
        pct = (100 * n / total) if total else 0
        print(f"{lane:<20}{n:<20}{pct:<12.1f}")

    if unreachable:
        print(f"\n({unreachable} veículos sem caminho até nenhuma estação -- estranho, checar)")

    print(f"\nSe a demanda fosse perfeitamente igual, cada estação teria "
          f"~{total/len(stations):.0f} veículos ({100/len(stations):.1f}%).")


if __name__ == "__main__":
    main()
