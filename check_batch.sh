#!/usr/bin/env bash
# Verificação de saúde do batch do "pseudorandom" em andamento.
# Uso (dentro da pasta ~/TCC):
#   bash check_batch.sh          -> checagem completa (demora ~60s)
#   bash check_batch.sh --fast   -> pula a checagem de CPU de 60s

set -u
# Roda a partir de onde o comando foi chamado (espera ser ~/TCC) -- não troca
# de pasta sozinho, pra sempre achar output/pseudorandom/cli.log certo.

APPROACH="pseudorandom"
FAST="${1:-}"

LOG_FILE="output/${APPROACH}/cli.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "Não achei $LOG_FILE -- confere se está na pasta ~/TCC e se o nome da abordagem está certo."
    exit 1
fi

echo "############################################"
echo "# Checando batch: $APPROACH"
echo "# $(date '+%Y-%m-%d %H:%M:%S')"
echo "############################################"

# --- Isola só a execução (rodada) mais recente do log, ignorando rodadas
# anteriores do mesmo approach que possam estar no mesmo arquivo. ---
START_LINE=$(grep -n "=== batch: approach=${APPROACH}" "$LOG_FILE" | tail -1 | cut -d: -f1)
if [ -z "$START_LINE" ]; then
    START_LINE=1
fi
CURRENT_LOG="/tmp/current_run_${APPROACH}.log"
tail -n +"$START_LINE" "$LOG_FILE" > "$CURRENT_LOG"

echo
echo "=== Progresso (sem duplicatas do bug de log conhecido) ==="
grep -E "job\(s\) pendentes|job\(s\) já têm|OK \(|FALHOU \(|=== retry|batch concluído|Nada a fazer" "$CURRENT_LOG" \
    | awk '{ $1=$1; line=$0; sub(/^[0-9-]+ [0-9:]+ \| INFO \| /, "", line); if (!seen[line]++) print }'

echo
echo "=== Erros no log desta rodada (vazio = nada de errado) ==="
grep -n -iE "error|traceback|exception|connection closed|falhou|falha" "$CURRENT_LOG"

echo
echo "=== Workers do batch e status ==="
# Acha os PIDs dos workers python (filhos diretos do processo principal do batch)
MAIN_PID=$(pgrep -f "cli.py batch --approach ${APPROACH}\b" | sort -n | head -1)
if [ -z "$MAIN_PID" ]; then
    echo "Nenhum processo 'cli.py batch --approach ${APPROACH}' rodando agora."
    exit 0
fi
echo "Processo principal: PID $MAIN_PID"

WORKER_PIDS=$(pgrep -f "cli.py batch --approach ${APPROACH}\b" | sort -n | tail -n +2)
if [ -z "$WORKER_PIDS" ]; then
    echo "(não achei workers filhos separados -- pode ser que o batch use outro"
    echo " mecanismo de paralelismo; olhe a lista completa abaixo)"
    pgrep -fa "cli.py batch --approach ${APPROACH}\b"
fi

ACTIVE=0
IDLE=0
for pid in $WORKER_PIDS; do
    SUMO_CHILD=$(pgrep -P "$pid" -a | grep -i sumo)
    if [ -n "$SUMO_CHILD" ]; then
        ACTIVE=$((ACTIVE + 1))
        echo "  worker $pid: ATIVO -- $SUMO_CHILD"
    else
        IDLE=$((IDLE + 1))
        echo "  worker $pid: ocioso (sem simulação atribuída no momento)"
    fi
done
echo "Total: $ACTIVE ativo(s), $IDLE ocioso(s)"

if [ "$FAST" = "--fast" ]; then
    echo
    echo "(--fast: pulando a checagem de CPU de 60s)"
    exit 0
fi

if [ "$ACTIVE" -eq 0 ]; then
    echo
    echo "Nenhum worker ativo no momento -- nada pra medir CPU."
    exit 0
fi

echo
echo "=== Checando se os workers ATIVOS estão progredindo de verdade ==="
echo "(compara o tempo de CPU acumulado de cada 'sumo' antes/depois de 60s --"
echo " se ficar TRAVADO/igual, é o mesmo sintoma do travamento antigo)"

declare -A BEFORE
for pid in $WORKER_PIDS; do
    child_pid=$(pgrep -P "$pid" -f sumo | head -1)
    if [ -n "$child_pid" ]; then
        t=$(ps -o time= -p "$child_pid" 2>/dev/null | tr -d ' ')
        BEFORE[$pid]="$child_pid|$t"
    fi
done

sleep 60

echo
PROBLEM=0
for pid in "${!BEFORE[@]}"; do
    child_pid="${BEFORE[$pid]%%|*}"
    t_before="${BEFORE[$pid]#*|}"
    t_after=$(ps -o time= -p "$child_pid" 2>/dev/null | tr -d ' ')
    if [ -z "$t_after" ]; then
        echo "  worker $pid (sumo pid $child_pid): processo sumiu -- provavelmente terminou entre as duas checagens (normal)."
        continue
    fi
    if [ "$t_before" = "$t_after" ]; then
        echo "  worker $pid (sumo pid $child_pid): *** SEM PROGRESSO EM 60s *** ($t_before -> $t_after) -- ATENÇÃO, pode ser o travamento antigo."
        PROBLEM=1
    else
        echo "  worker $pid (sumo pid $child_pid): progredindo normalmente ($t_before -> $t_after)."
    fi
done

echo
if [ "$PROBLEM" -eq 1 ]; then
    echo ">>> Encontrei worker(s) sem progresso -- vale a pena olhar de novo em alguns minutos."
    echo ">>> Lembre-se: o timeout de 30h ainda protege mesmo se isso confirmar um travamento real."
else
    echo ">>> Tudo progredindo normalmente, nenhum sinal do travamento antigo."
fi
