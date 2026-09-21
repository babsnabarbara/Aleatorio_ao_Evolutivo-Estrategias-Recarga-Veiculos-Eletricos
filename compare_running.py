#!/usr/bin/env python3
"""
compare_running.py -- para cada simulação 'sumo' rodando AGORA, mostra há
quanto tempo ela está rodando e compara com a duração real das repetições
"irmãs" (mesma combinação minutes+percentage+cs_amount, outra repetition)
que já terminaram -- lidas direto do bloco "Performance: Duration:" que o
próprio SUMO escreve no log de cada uma.

Uso (de dentro de ~/TCC):

    python3 compare_running.py                  # approach = pseudorandom
    python3 compare_running.py greedyvoronoi     # qualquer outra abordagem

Não depende do config.py do projeto -- só do padrão de pastas/arquivos
output/<approach>/<minutes>min/<percentage>percentage<cs>cs/... e da
convenção de nomes já usada em analysis_report.py.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SIM_ENDED_RE = re.compile(r"Simulation ended at time:\s*(\d+(?:\.\d+)?)")
PERF_DURATION_RE = re.compile(r"Performance:.*?Duration:\s*(\d+(?:\.\d+)?)(m?s)", re.DOTALL)

CFG_RE = re.compile(
    r"output/(?P<approach>[^/]+)/(?P<minutes>\d+)min/"
    r"(?P<pct>\d+)percentage(?P<cs>\d+)cs/cologne(?P<rep>\d+)\.sumo\.cfg"
)


def fmt_seconds(s: float) -> str:
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{sec:02d}s"
    if m:
        return f"{m}m{sec:02d}s"
    return f"{sec}s"


def find_running_jobs(approach: str) -> list[dict]:
    """Lê `ps` e acha todo processo sumo cujo --config bate com o padrão de
    pastas dessa approach, junto do tempo decorrido (etimes, em segundos)."""
    out = subprocess.run(
        ["ps", "-eo", "pid,etimes,args"], capture_output=True, text=True, check=True
    ).stdout
    jobs = []
    for line in out.splitlines()[1:]:
        line = line.strip()
        if not line or "/sumo/bin/sumo" not in line or "--remote-port" not in line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, etimes, args = parts
        m = CFG_RE.search(args)
        if not m or m.group("approach") != approach:
            continue
        jobs.append({
            "pid": pid,
            "elapsed_s": float(etimes),
            "minutes": int(m.group("minutes")),
            "pct": int(m.group("pct")),
            "cs": int(m.group("cs")),
            "rep": int(m.group("rep")),
        })

    # Dedup por (minutes,pct,cs,rep) -- cada job real só deveria ter UM
    # processo sumo, mas por segurança (ex.: alguma linha repetida do
    # próprio `ps`) mantemos só uma entrada por combinação, com o maior
    # elapsed_s visto.
    dedup: dict[tuple[int, int, int, int], dict] = {}
    for j in jobs:
        key = (j["minutes"], j["pct"], j["cs"], j["rep"])
        if key not in dedup or j["elapsed_s"] > dedup[key]["elapsed_s"]:
            dedup[key] = j
    return list(dedup.values())


def parse_duration(log_path: Path) -> float | None:
    """Duração real (em segundos) do bloco Performance de um log JÁ
    terminado, ou None se o log não tiver um resumo completo (falhou ou
    ainda está rodando)."""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if SIM_ENDED_RE.search(text) is None:
        return None
    m = PERF_DURATION_RE.search(text)
    if m is None:
        return None
    value, unit = float(m.group(1)), m.group(2)
    return value / 1000.0 if unit == "ms" else value


def sibling_durations(approach: str, minutes: int, pct: int, cs: int, skip_rep: int) -> list[tuple[int, float]]:
    combo_dir = Path("output") / approach / f"{minutes}min" / f"{pct}percentage{cs}cs"
    results = []
    if not combo_dir.is_dir():
        return results
    for log_path in sorted(combo_dir.glob("log*.xml")):
        m = re.match(rf"^log(\d+){pct}percentage{cs}cs\.xml$", log_path.name)
        if not m:
            continue
        rep = int(m.group(1))
        if rep == skip_rep:
            continue
        dur = parse_duration(log_path)
        if dur is not None:
            results.append((rep, dur))
    return results


def main() -> None:
    approach = sys.argv[1] if len(sys.argv) > 1 else "pseudorandom"

    if not Path("output").is_dir():
        print("Não achei a pasta 'output' -- rode a partir de ~/TCC.")
        sys.exit(1)

    jobs = find_running_jobs(approach)
    if not jobs:
        print(f"Nenhuma simulação de '{approach}' rodando agora.")
        return

    jobs.sort(key=lambda j: (j["minutes"], j["pct"], j["cs"], j["rep"]))

    header = f"{'Job (min/pct/cs/rep)':<26} {'Rodando há':<12} {'Irmãs já terminadas (rep: duração)':<45} {'Média irmãs':<12} {'Status':<20}"
    print(header)
    print("-" * len(header))

    for j in jobs:
        label = f"{j['minutes']}min_{j['pct']}pct_{j['cs']}cs_rep{j['rep']}"
        elapsed_str = fmt_seconds(j["elapsed_s"])
        siblings = sibling_durations(approach, j["minutes"], j["pct"], j["cs"], j["rep"])
        if siblings:
            siblings_str = ", ".join(f"rep{r}: {fmt_seconds(d)}" for r, d in siblings)
            avg = sum(d for _, d in siblings) / len(siblings)
            avg_str = fmt_seconds(avg)
            max_d = max(d for _, d in siblings)
            if j["elapsed_s"] > max_d * 1.5:
                status = f"ACIMA do normal (max irmã {fmt_seconds(max_d)})"
            elif j["elapsed_s"] > max_d:
                status = "um pouco acima do max"
            else:
                status = "dentro do esperado"
        else:
            siblings_str = "(nenhuma irmã terminada ainda)"
            avg_str = "--"
            status = "sem referência"

        print(f"{label:<26} {elapsed_str:<12} {siblings_str:<45} {avg_str:<12} {status:<20}")


if __name__ == "__main__":
    main()
