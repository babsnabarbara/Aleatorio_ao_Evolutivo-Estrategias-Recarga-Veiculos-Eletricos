#!/usr/bin/env bash
# identify_stuck_jobs.sh
#
# Dado um ou mais PIDs de processos sumo travados, identifica qual job
# (minutes/percentage/cs_amount/repetition) cada um está rodando, lendo
# a linha de comando do processo (/proc/<pid>/cmdline) -- o SUMO é
# chamado com "-c <caminho>/cologne<repetition>.sumo.cfg", e o caminho
# já contém approach/minutes/percentage/cs.
#
# Uso:
#   bash identify_stuck_jobs.sh 140812 140896 147286 147462 152119
#
# Se não passar PIDs, detecta automaticamente todo processo sumo
# rodando no momento.

if [ "$#" -eq 0 ]; then
    PIDS=$(pgrep -x sumo)
    if [ -z "$PIDS" ]; then
        echo "Nenhum processo 'sumo' rodando agora."
        exit 0
    fi
else
    PIDS="$@"
fi

printf "%-10s %-12s %-45s %s\n" "PID" "CPU_TIME" "job (approach/minutes/pct/cs/rep)" "cfg_path"
printf "%-10s %-12s %-45s %s\n" "---" "--------" "----------------------------------" "--------"

for pid in $PIDS; do
    if [ ! -d "/proc/$pid" ]; then
        echo "$pid: processo não existe mais (já terminou ou foi morto)"
        continue
    fi

    cmdline=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null)
    cfg=$(echo "$cmdline" | grep -oP '(?<=-c )\S+\.sumo\.cfg' | head -1)
    if [ -z "$cfg" ]; then
        cfg=$(echo "$cmdline" | grep -oP '\S+\.sumo\.cfg' | head -1)
    fi

    cputime=$(ps -o cputime= -p "$pid" 2>/dev/null | tr -d ' ')

    if [ -z "$cfg" ]; then
        printf "%-10s %-12s %-45s %s\n" "$pid" "${cputime:-?}" "(não achei .sumo.cfg na cmdline)" "$cmdline"
        continue
    fi

    # cfg tipicamente: .../output/<approach>/<min>min/<pct>percentage<cs>cs/cologne<rep>.sumo.cfg
    job=$(echo "$cfg" | grep -oP 'output/\K[^/]+/[0-9]+min/[0-9]+percentage[0-9]+cs' )
    rep=$(basename "$cfg" | grep -oP '(?<=cologne)\d+(?=\.sumo\.cfg)')

    printf "%-10s %-12s %-45s %s\n" "$pid" "${cputime:-?}" "${job:-?}/rep${rep:-?}" "$cfg"
done
