"""
verify_recharge.py -- confere, para uma combinação de parâmetros já
simulada, se o pipeline de recarga funcionou como esperado em cada
approach:

    1. A % certa de veículos foi selecionada para recarregar
       (sortedCars-N/sortedCarsN.xml tem exatamente
       int(percentage/100 * vehicles) carros).
    2. Todos esses carros ficaram parados na estação por pelo menos
       `minutes * 60` segundos.

Usa o tripinfo (`stopTime`) como fonte de verdade da duração da parada --
NÃO o arquivo de --battery-output. O campo chargingStationId no
battery-output fica marcado desde o momento em que a parada é agendada
(enquanto o carro ainda está se aproximando da estação), não só enquanto
ele está fisicamente parado -- contar linhas ali mistura viagem + parada e
dá um número inflado, sem relação com o tempo real parado. Isso já causou
uma investigação longa e desnecessária numa sessão anterior; o tripinfo
resolve de forma direta e confiável.

Uso (rodar de dentro de MD/, depois que os approaches já foram simulados):

    python3 verify_recharge.py
    python3 verify_recharge.py --minutes 10 --cs 10 --percentage 5 --repetition 1 --vehicles 200
    python3 verify_recharge.py --approach random pseudorandom

Gera verification_report.txt nesta mesma pasta, além de imprimir na tela.
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import config
from sim_job import SimJob
from simulation import read_sorted_cars


def _read_tripinfo(job: SimJob) -> dict:
    """{trip_id: {'stopTime': float, 'vaporized': str}} -- ou {} se o
    arquivo ainda não existir (approach não simulado)."""
    path = job.tripinfo_output_file
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    result = {}
    for trip in root.findall(".//tripinfo"):
        stop_time_raw = trip.get("stopTime")
        result[trip.get("id")] = {
            "stopTime": float(stop_time_raw) if stop_time_raw is not None else 0.0,
            "vaporized": trip.get("vaporized", ""),
        }
    return result


def verify_approach(approach: str, minutes: int, cs_amount: int, percentage: int,
                     repetition: int, vehicles: int) -> dict:
    job = SimJob(
        approach=approach, minutes=minutes, cs_amount=cs_amount,
        percentage=percentage, repetition=repetition, vehicles=vehicles,
        max_vehicles_per_cs=config.DEFAULT_MAX_VEHICLES_PER_CS, seed=0,
    )

    report: dict = {"approach": approach, "job_folder": str(job.folder)}

    if not job.sorted_cars_file.exists():
        report["error"] = f"arquivo de sorteados não encontrado: {job.sorted_cars_file}"
        return report
    if not job.tripinfo_output_file.exists():
        report["error"] = f"tripinfo não encontrado: {job.tripinfo_output_file}"
        return report

    selected = read_sorted_cars(job)
    selected_ids = set(selected.keys())
    expected_count = int((percentage / 100) * vehicles)
    actual_count = len(selected_ids)

    report["expected_selected_count"] = expected_count
    report["actual_selected_count"] = actual_count
    report["percentual_correto"] = actual_count == expected_count

    tripinfos = _read_tripinfo(job)
    required_stop_s = minutes * 60

    missing: list = []          # sorteado, mas nunca terminou a viagem (sem tripinfo)
    too_short: list = []        # terminou, mas stopTime < esperado
    forced_removed: list = []   # vaporized != "" -- removido à força pelo SUMO

    for trip_id in selected_ids:
        info = tripinfos.get(trip_id)
        if info is None:
            missing.append(trip_id)
            continue
        if info["vaporized"]:
            forced_removed.append(trip_id)
        if info["stopTime"] < required_stop_s:
            too_short.append((trip_id, info["stopTime"]))

    report["required_stop_seconds"] = required_stop_s
    report["missing_from_tripinfo"] = missing
    report["forced_removed_vaporized"] = forced_removed
    report["stopped_short"] = too_short
    report["todos_pararam_tempo_certo"] = (
        actual_count > 0 and not missing and not too_short
    )

    return report


def _format_report(r: dict) -> str:
    lines = [f"=== approach: {r['approach']} ==="]
    if "error" in r:
        lines.append(f"  ERRO: {r['error']}")
        lines.append("  (approach provavelmente ainda não foi simulado com esses parâmetros)")
        return "\n".join(lines)

    lines.append(f"  pasta: {r['job_folder']}")
    lines.append(
        f"  percentual de carros certo selecionado? "
        f"{'true' if r['percentual_correto'] else 'false'}"
        f"  (esperado: {r['expected_selected_count']}, achado: {r['actual_selected_count']})"
    )
    lines.append(
        f"  todos os carros selecionados ficaram >= {r['required_stop_seconds']}s "
        f"parados na estação? {'true' if r['todos_pararam_tempo_certo'] else 'false'}"
    )

    if r["missing_from_tripinfo"]:
        amostra = r["missing_from_tripinfo"][:5]
        lines.append(
            f"    -> {len(r['missing_from_tripinfo'])} carro(s) sorteado(s) nunca "
            f"aparecem no tripinfo (não terminaram a viagem): {amostra}"
            + (" ..." if len(r["missing_from_tripinfo"]) > 5 else "")
        )
    if r["stopped_short"]:
        amostra = r["stopped_short"][:5]
        lines.append(
            f"    -> {len(r['stopped_short'])} carro(s) pararam menos tempo que o "
            f"pedido: {amostra}" + (" ..." if len(r["stopped_short"]) > 5 else "")
        )
    if r["forced_removed_vaporized"]:
        amostra = r["forced_removed_vaporized"][:5]
        lines.append(
            f"    -> {len(r['forced_removed_vaporized'])} carro(s) foram removidos "
            f"à força pelo SUMO (vaporized) antes do fim natural da viagem: {amostra}"
            + (" ..." if len(r["forced_removed_vaporized"]) > 5 else "")
        )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minutes", type=int, default=10)
    parser.add_argument("--cs", type=int, default=16)
    parser.add_argument("--percentage", type=int, default=5)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--vehicles", type=int, default=200)
    parser.add_argument("--approach", nargs="+", default=list(config.APPROACHES),
                         choices=list(config.APPROACHES))
    parser.add_argument("--output", default="verification_report.txt")
    args = parser.parse_args()

    header = [
        "Relatório de verificação de recarga",
        f"gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"parâmetros: minutes={args.minutes} cs={args.cs} percentage={args.percentage} "
        f"repetition={args.repetition} vehicles={args.vehicles}",
        "",
    ]

    blocks = []
    for approach in args.approach:
        r = verify_approach(
            approach, args.minutes, args.cs, args.percentage,
            args.repetition, args.vehicles,
        )
        blocks.append(_format_report(r))

    full_text = "\n".join(header) + "\n\n".join(blocks) + "\n"
    print(full_text)

    out_path = Path(args.output)
    out_path.write_text(full_text, encoding="utf-8")
    print(f"[relatório salvo em: {out_path.resolve()}]")


if __name__ == "__main__":
    main()
