"""
check_durations.py -- varre todos os logs do SUMO já gerados por um
approach e lista a duração REAL de cada simulação (o `Duration:` que o
próprio SUMO grava no fim do log, em segundos de execução), ordenada.

Isso é diferente do intervalo entre duas linhas 'OK' no cli.log/batch.log
-- como o batch roda vários jobs em paralelo, a ordem em que eles
APARECEM no log é a ordem em que TERMINAM, não a ordem em que começaram
nem quanto tempo cada um levou. Esse script lê a duração real de dentro
de cada log individual do SUMO, então não é enganado por isso.

Uso (de dentro de MD/, depois que pelo menos alguns jobs já terminaram):

    python3 check_durations.py --approach pseudorandom
    python3 check_durations.py --approach pseudorandom --top 20
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import config

DURATION_RE = re.compile(r"^\s*Duration:\s*([\d.]+)(m?s)\s*$", re.MULTILINE)
SIM_ENDED_RE = re.compile(r"Simulation ended at time:\s*([\d.]+)")


def find_log_files(approach: str) -> list[Path]:
    approach_dir = config.OUTPUT_DIR / approach
    if not approach_dir.exists():
        return []
    # nome do arquivo: log<repetition><percentage>percentage<cs>cs.xml
    # (não confundir com cli.log, que é o log da aplicação, não do SUMO)
    return sorted(approach_dir.glob("**/log*cs.xml"))


def parse_duration(log_path: Path) -> tuple[float, float] | None:
    """Devolve (duration_segundos, simulated_time_segundos), ou None se o
    log não tiver uma linha 'Duration:' (ex: job que falhou antes de
    terminar, ou ainda está rodando).

    FIX: o SUMO reporta essa linha em segundos ("Duration: 65.59s") ou em
    milissegundos ("Duration: 2728644ms"), dependendo da versão/tamanho da
    simulação -- sem aviso, o mesmo formato de log pode variar entre
    servidores. Sem tratar os dois, jobs que terminaram com sucesso (mas
    cujo log usava "ms") apareciam como "sem Duration registrada", como se
    tivessem falhado. Convertido sempre para segundos no retorno, pra
    manter a comparação entre jobs consistente independente do formato
    original de cada log. Repare que o regex exige 's' ou 'ms' logo após o
    número -- a linha 'Duration:' de dentro de 'Statistics (avg):' (duração
    MÉDIA DE VIAGEM dos veículos, não tempo de execução real) não tem essa
    unidade, então continua sendo ignorada corretamente."""
    text = log_path.read_text(encoding="utf-8", errors="replace")
    duration_match = DURATION_RE.search(text)
    if duration_match is None:
        return None
    raw_value = float(duration_match.group(1))
    unit = duration_match.group(2)
    duration = raw_value / 1000.0 if unit == "ms" else raw_value
    sim_match = SIM_ENDED_RE.search(text)
    simulated_time = float(sim_match.group(1)) if sim_match else 0.0
    return duration, simulated_time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approach", required=True, choices=list(config.APPROACHES))
    parser.add_argument("--top", type=int, default=10,
                         help="Quantos mostrar em cada ponta (mais rápidos / mais lentos)")
    args = parser.parse_args()

    log_files = find_log_files(args.approach)
    if not log_files:
        print(f"Nenhum log encontrado em {config.OUTPUT_DIR / args.approach} -- "
              f"esse approach ainda não gerou nenhum resultado.")
        return

    results: list[tuple[float, float, Path]] = []
    sem_duration = []
    for log_path in log_files:
        parsed = parse_duration(log_path)
        if parsed is None:
            sem_duration.append(log_path)
            continue
        duration, simulated_time = parsed
        results.append((duration, simulated_time, log_path))

    results.sort(key=lambda r: r[0])

    print(f"=== {args.approach}: {len(results)} job(s) com duração registrada "
          f"({len(sem_duration)} sem -- provavelmente ainda rodando ou falharam) ===\n")

    if results:
        durations = [r[0] for r in results]
        print(f"mais rápido: {durations[0]:.2f}s | mais lento: {durations[-1]:.2f}s | "
              f"média: {sum(durations)/len(durations):.2f}s\n")

        n = min(args.top, len(results))
        print(f"--- {n} MAIS RÁPIDOS ---")
        for duration, simulated_time, path in results[:n]:
            rel = path.relative_to(config.OUTPUT_DIR / args.approach)
            print(f"  {duration:8.2f}s  (simulou {simulated_time:.0f}s)  {rel}")

        print(f"\n--- {n} MAIS LENTOS ---")
        for duration, simulated_time, path in results[-n:]:
            rel = path.relative_to(config.OUTPUT_DIR / args.approach)
            print(f"  {duration:8.2f}s  (simulou {simulated_time:.0f}s)  {rel}")

    if sem_duration:
        print(f"\n--- {len(sem_duration)} log(s) SEM 'Duration:' registrada "
              f"(amostra, até 5) ---")
        for path in sem_duration[:5]:
            rel = path.relative_to(config.OUTPUT_DIR / args.approach)
            print(f"  {rel}")


if __name__ == "__main__":
    main()
