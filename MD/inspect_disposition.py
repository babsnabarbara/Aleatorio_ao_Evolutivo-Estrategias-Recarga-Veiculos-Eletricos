#!/usr/bin/env python3
"""
inspect_disposition.py

Dado um approach/repetition/cs_amount, lista as lanes escolhidas como
estação (lidas do cache em stations_evolution/) e cruza cada uma com:
  - comprimento (lane_lengths / net.xml) e capacidade realizada
  - quantas vezes aparece em mostVisited.xml (proxy de o quanto essa rua
    é uma via de passagem movimentada)

Objetivo: já que a capacidade baixa foi descartada como causa dos
travamentos, isso ajuda a ver se alguma das estações dessa seed está
numa via MUITO movimentada (candidata a virar gargalo real quando
carros ficam parados ali esperando vaga), mesmo sendo uma lane comprida
o bastante.

Uso (rodar de dentro de ~/TCC/MD, onde ficam graph_utils.py/config.py):
    python3 inspect_disposition.py --approach pseudorandom --repetition 4 --cs-amount 9
"""
import argparse
import xml.etree.ElementTree as ET

import config
import graph_utils
import io_utils


def load_most_visited():
    """Lê input/mostVisited.xml -> {lane_id: count} (mesmo formato/parsing
    que greedy_strategy.py::_most_visited_lanes: <lane id=... count=.../>)."""
    counts = {}
    try:
        root = ET.parse(config.MOST_VISITED_FILE).getroot()
    except (FileNotFoundError, ET.ParseError):
        return counts
    for lane_elem in root.findall(".//lane"):
        lane_id = lane_elem.get("id")
        count = lane_elem.get("count")
        if lane_id is not None:
            counts[lane_id] = int(count) if count is not None else 0
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--approach", required=True)
    ap.add_argument("--repetition", type=int, required=True)
    ap.add_argument("--cs-amount", type=int, required=True)
    args = ap.parse_args()

    stations_file = (
        config.station_evolution_dir(args.approach, args.repetition)
        / f"{args.cs_amount}stations.xml"
    )
    if not stations_file.exists():
        print(f"Não achei {stations_file}")
        return

    root = ET.parse(stations_file).getroot()
    # formato escrito por io_utils.write_selected_lanes_file_to:
    # <cs><lane>lane_id</lane>...</cs>
    lanes = [el.text.strip() for el in root.findall(".//lane") if el.text and el.text.strip()]

    lengths = graph_utils.lane_lengths()
    veh_len = io_utils.vehicle_length("soulEV65")
    visited = load_most_visited()

    max_visits = max(visited.values()) if visited else 0

    rows = []
    for lane in lanes:
        length = lengths.get(lane)
        cap = (length / veh_len) if length else None
        entered = visited.get(lane, 0)
        pct_of_max = (100 * entered / max_visits) if max_visits else 0
        rows.append((lane, length, cap, entered, pct_of_max))

    rows.sort(key=lambda r: r[3], reverse=True)  # mais visitada primeiro

    print(f"{len(lanes)} estações -- {args.approach} rep{args.repetition} cs{args.cs_amount}\n")
    print(f"{'lane':<20}{'comprimento(m)':<16}{'cabe_veic':<12}{'vezes_visitada':<16}{'%_da_mais_visitada_do_mapa':<10}")
    for lane, length, cap, entered, pct in rows:
        length_s = f"{length:.1f}" if length else "?"
        cap_s = f"{cap:.1f}" if cap else "?"
        print(f"{lane:<20}{length_s:<16}{cap_s:<12}{entered:<16}{pct:<10.2f}")

    print(f"\n(referência: a lane mais visitada de TODO o mapa tem {max_visits} entradas)")
    print("Estações com % alto aqui são vias de passagem movimentadas -- "
          "candidatas a gargalo real se ficarem com fila de carro esperando vaga.")


if __name__ == "__main__":
    main()
