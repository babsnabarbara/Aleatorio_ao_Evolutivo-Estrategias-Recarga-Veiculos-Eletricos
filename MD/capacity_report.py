"""
capacity_report.py -- varre os .add.xml já gerados e lista a capacidade
real (roadsideCapacity) de cada estação, para todos os approaches.

Fonte de verdade: lê direto os .add.xml já escritos em disco (não
recalcula nada) -- é exatamente o valor que graph_utils.realized_capacity
gravou na hora da geração (ver io_utils.write_add_file).

Como a capacidade de uma estação não depende de minutes/percentage (só de
qual lane foi escolhida, que por sua vez só depende de approach +
repetition + cs_amount), o script lê UM .add.xml representativo por
(approach, repetition, cs_amount) -- não repete a mesma informação para
cada combinação de minutes/percentage que exista.

Uso (de dentro de MD/, depois que pelo menos alguns jobs já foram gerados):

    python3 capacity_report.py
    python3 capacity_report.py --approach random genetic
"""
from __future__ import annotations

import argparse
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

import config

FOLDER_RE = re.compile(r"(\d+)percentage(\d+)cs$")
FILE_RE = re.compile(r"cologne(\d+)\.add\.xml$")


def find_representative_add_files(approach: str) -> dict[tuple[int, int], Path]:
    """
    Devolve {(repetition, cs_amount): caminho_de_um_add_xml}, com só UM
    arquivo por combinação (repetition, cs_amount) -- não importa qual
    minutes/percentage, já que a capacidade é a mesma em todos.
    """
    approach_dir = config.OUTPUT_DIR / approach
    if not approach_dir.exists():
        return {}

    result: dict[tuple[int, int], Path] = {}
    for add_path in approach_dir.glob("**/cologne*.add.xml"):
        folder_match = FOLDER_RE.search(add_path.parent.name)
        file_match = FILE_RE.search(add_path.name)
        if not folder_match or not file_match:
            continue
        cs_amount = int(folder_match.group(2))
        repetition = int(file_match.group(1))
        key = (repetition, cs_amount)
        if key not in result:  # só guarda o primeiro que achar
            result[key] = add_path
    return result


def read_capacities(add_path: Path) -> list[tuple[str, str, int]]:
    """Devolve [(station_id, lane, roadsideCapacity), ...] de um .add.xml."""
    root = ET.parse(add_path).getroot()
    stations = []
    for pa in root.findall(".//parkingArea"):
        stations.append((
            pa.get("id", "?"),
            pa.get("lane", "?"),
            int(pa.get("roadsideCapacity", "0")),
        ))
    return stations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approach", nargs="+", default=list(config.APPROACHES),
                         choices=list(config.APPROACHES))
    parser.add_argument("--output", default="capacity_report.txt")
    args = parser.parse_args()

    lines: list[str] = []
    lines.append("Relatório de capacidade real das estações (roadsideCapacity)")
    lines.append("=" * 65)
    lines.append("")

    for approach in args.approach:
        combos = find_representative_add_files(approach)
        if not combos:
            lines.append(f"=== {approach}: nenhum .add.xml encontrado ainda ===\n")
            continue

        lines.append(f"=== {approach} ===")
        all_capacities: list[int] = []

        for (repetition, cs_amount) in sorted(combos):
            add_path = combos[(repetition, cs_amount)]
            stations = read_capacities(add_path)
            capacities = [cap for _id, _lane, cap in stations]
            all_capacities.extend(capacities)

            lines.append(
                f"  repetition={repetition} cs_amount={cs_amount}: "
                f"{len(stations)} estação(ões), capacidades: "
                f"min={min(capacities)} max={max(capacities)} "
                f"média={statistics.mean(capacities):.1f}"
            )
            for station_id, lane, cap in sorted(stations, key=lambda s: s[0]):
                lines.append(f"    estação {station_id:>3} (lane {lane}): capacidade = {cap}")

        if all_capacities:
            lines.append(
                f"  --- resumo geral do approach: min={min(all_capacities)} "
                f"max={max(all_capacities)} média={statistics.mean(all_capacities):.2f} "
                f"({len(all_capacities)} estação(ões) no total) ---"
            )
        lines.append("")

    full_text = "\n".join(lines)
    print(full_text)

    out_path = Path(args.output)
    out_path.write_text(full_text, encoding="utf-8")
    print(f"[relatório salvo em: {out_path.resolve()}]")


if __name__ == "__main__":
    main()
