"""
analysis_report.py -- varre todos os logs do SUMO já gerados e monta, para
cada (approach, minutes), um CSV com uma linha por job, contendo todos os
campos do resumo final do log (Simulation ended, Performance, Vehicles,
Teleports, Emergency Stops, Statistics).

Saída: TCC/output/analysis/<approach>/<minutes>min.csv

Ordem das colunas: primeiro as colunas de identificação (approach,
minutes, cs_amount, percentage, repetition), depois as de
'Statistics (avg):' (são a métrica principal de comparação entre
approaches -- tempo médio de viagem etc.), por último o resto (Simulation
ended, Performance, Vehicles, Teleports, Emergency Stops).

Fonte de verdade: lê direto os logs já escritos em disco (não recalcula
nada) -- mesmo princípio do capacity_report.py/check_durations.py.

Uso (de dentro de MD/, depois que pelo menos alguns jobs já terminaram):

    python3 analysis_report.py
    python3 analysis_report.py --approach random genetic
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import config

FOLDER_RE = re.compile(r"^(\d+)percentage(\d+)cs$")
MINUTES_DIR_RE = re.compile(r"^(\d+)min$")

SIM_ENDED_RE = re.compile(r"Simulation ended at time:\s*(\d+(?:\.\d+)?)")
REASON_RE = re.compile(r"Reason:\s*(.+)")
PERF_DURATION_RE = re.compile(r"Performance:.*?Duration:\s*(\d+(?:\.\d+)?)(m?s)", re.DOTALL)
RTF_RE = re.compile(r"Real time factor:\s*(\d+(?:\.\d+)?)")
UPS_RE = re.compile(r"UPS:\s*(\d+(?:\.\d+)?)")
INSERTED_RE = re.compile(r"Inserted:\s*(\d+)")
RUNNING_RE = re.compile(r"Running:\s*(\d+)")
WAITING_RE = re.compile(r"Waiting:\s*(\d+)")
TELEPORTS_TOTAL_RE = re.compile(r"Teleports:\s*(\d+)")
COLLISIONS_RE = re.compile(r"Collisions:\s*(\d+)")
JAM_RE = re.compile(r"Jam:\s*(\d+)")
YIELD_RE = re.compile(r"Yield:\s*(\d+)")
WRONG_LANE_RE = re.compile(r"Wrong Lane:\s*(\d+)")
EMERGENCY_RE = re.compile(r"Emergency Stops:\s*(\d+)")
STATS_BLOCK_RE = re.compile(r"Statistics \(avg\):(.*?)(?:\nAStarRouter|\Z)", re.DOTALL)

COLUMNS = [
    # identificação
    "approach", "minutes", "cs_amount", "percentage", "repetition",
    # Statistics (avg) -- primeiro, é a métrica principal de comparação
    "stat_route_length", "stat_duration", "stat_waiting_time",
    "stat_time_loss", "stat_depart_delay",
    # resto, por último
    "sim_ended_time", "reason", "perf_duration_s", "real_time_factor", "ups",
    "vehicles_inserted", "vehicles_running", "vehicles_waiting",
    "teleports_total", "teleports_collisions", "teleports_jam",
    "teleports_yield", "teleports_wrong_lane", "emergency_stops",
]


def _num(pattern: re.Pattern, text: str, cast=float, default=None):
    m = pattern.search(text)
    if m is None:
        return default
    return cast(m.group(1))


def parse_log(text: str) -> dict | None:
    """Devolve um dict com todos os campos, ou None se o log não tiver um
    resumo final completo (job que falhou/ainda está rodando)."""
    sim_ended = _num(SIM_ENDED_RE, text)
    if sim_ended is None:
        return None  # sem "Simulation ended at time:" -- não terminou

    perf_match = PERF_DURATION_RE.search(text)
    if perf_match is None:
        return None  # sem bloco de Performance -- resumo incompleto
    raw_value, unit = float(perf_match.group(1)), perf_match.group(2)
    perf_duration_s = raw_value / 1000.0 if unit == "ms" else raw_value

    stats_match = STATS_BLOCK_RE.search(text)
    stats_text = stats_match.group(1) if stats_match else ""

    reason_match = REASON_RE.search(text)

    return {
        "sim_ended_time": sim_ended,
        "reason": reason_match.group(1).strip() if reason_match else "",
        "perf_duration_s": perf_duration_s,
        "real_time_factor": _num(RTF_RE, text),
        "ups": _num(UPS_RE, text),
        "vehicles_inserted": _num(INSERTED_RE, text, cast=int, default=0),
        "vehicles_running": _num(RUNNING_RE, text, cast=int, default=0),
        "vehicles_waiting": _num(WAITING_RE, text, cast=int, default=0),
        "teleports_total": _num(TELEPORTS_TOTAL_RE, text, cast=int, default=0),
        "teleports_collisions": _num(COLLISIONS_RE, text, cast=int, default=0),
        "teleports_jam": _num(JAM_RE, text, cast=int, default=0),
        "teleports_yield": _num(YIELD_RE, text, cast=int, default=0),
        "teleports_wrong_lane": _num(WRONG_LANE_RE, text, cast=int, default=0),
        "emergency_stops": _num(EMERGENCY_RE, text, cast=int, default=0),
        "stat_route_length": _num(re.compile(r"RouteLength:\s*(\d+(?:\.\d+)?)"), stats_text),
        "stat_duration": _num(re.compile(r"Duration:\s*(\d+(?:\.\d+)?)"), stats_text),
        "stat_waiting_time": _num(re.compile(r"WaitingTime:\s*(\d+(?:\.\d+)?)"), stats_text),
        "stat_time_loss": _num(re.compile(r"TimeLoss:\s*(\d+(?:\.\d+)?)"), stats_text),
        "stat_depart_delay": _num(re.compile(r"DepartDelay:\s*(\d+(?:\.\d+)?)"), stats_text),
    }


def find_repetition(filename: str, percentage: int, cs_amount: int) -> int | None:
    """
    Nome do arquivo: log<repetition><percentage>percentage<cs_amount>cs.xml
    -- sem separador entre repetition e percentage, então não dá pra usar
    regex simples (ambíguo). Como já sabemos percentage/cs_amount pelo
    nome da pasta, isolamos o sufixo conhecido e o que sobra no início é a
    repetition.
    """
    if not filename.startswith("log") or not filename.endswith(".xml"):
        return None
    middle = filename[len("log"):-len(".xml")]
    suffix = f"{percentage}percentage{cs_amount}cs"
    if not middle.endswith(suffix):
        return None
    prefix = middle[: -len(suffix)]
    return int(prefix) if prefix.isdigit() else None


def collect_rows(approach: str, minutes: int) -> list[dict]:
    minutes_dir = config.OUTPUT_DIR / approach / f"{minutes}min"
    rows: list[dict] = []
    skipped = 0

    for combo_dir in sorted(minutes_dir.glob("*percentage*cs")):
        folder_match = FOLDER_RE.match(combo_dir.name)
        if not folder_match:
            continue
        percentage, cs_amount = int(folder_match.group(1)), int(folder_match.group(2))

        for log_path in sorted(combo_dir.glob("log*.xml")):
            repetition = find_repetition(log_path.name, percentage, cs_amount)
            if repetition is None:
                continue

            text = log_path.read_text(encoding="utf-8", errors="replace")
            parsed = parse_log(text)
            if parsed is None:
                skipped += 1
                continue

            row = {
                "approach": approach, "minutes": minutes, "cs_amount": cs_amount,
                "percentage": percentage, "repetition": repetition,
            }
            row.update(parsed)
            rows.append(row)

    if skipped:
        print(f"  ({skipped} log(s) incompletos/sem resumo final, ignorados)")
    return rows


def write_csv(approach: str, minutes: int, rows: list[dict]) -> Path:
    out_dir = config.OUTPUT_DIR / "analysis" / approach
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{minutes}min.csv"

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approach", nargs="+", default=list(config.APPROACHES),
                         choices=list(config.APPROACHES))
    args = parser.parse_args()

    for approach in args.approach:
        approach_dir = config.OUTPUT_DIR / approach
        if not approach_dir.exists():
            print(f"=== {approach}: nenhum output encontrado ainda ===")
            continue

        minutes_dirs = sorted(
            int(m.group(1))
            for p in approach_dir.glob("*min")
            if (m := MINUTES_DIR_RE.match(p.name))
        )
        if not minutes_dirs:
            print(f"=== {approach}: nenhuma pasta <minutes>min/ encontrada ===")
            continue

        print(f"=== {approach} ===")
        for minutes in minutes_dirs:
            rows = collect_rows(approach, minutes)
            if not rows:
                print(f"  {minutes}min: 0 job(s) com resumo completo -- CSV não gerado")
                continue
            out_path = write_csv(approach, minutes, rows)
            print(f"  {minutes}min: {len(rows)} job(s) -> {out_path}")


if __name__ == "__main__":
    main()
