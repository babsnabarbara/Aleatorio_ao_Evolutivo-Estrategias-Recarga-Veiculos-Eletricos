#!/bin/bash
# sync_resultados.sh
#
# Roda em background em CADA servidor, junto com o worker. A cada
# INTERVALO_SEGUNDOS:
#   1) Puxa (git pull) o que os outros servidores já enviaram -- assim a
#      pasta resultados/ local sempre reflete o progresso de TODOS os
#      servidores, não só deste.
#   2) Se tiver resultado novo aqui, commita e envia (git push).
#
# USO:
#   chmod +x sync_resultados.sh
#   nohup ./sync_resultados.sh 0 > sync_0.out 2>&1 &
#   disown

SERVIDOR_ID="${1:?Uso: ./sync_resultados.sh <indice_do_servidor>}"
INTERVALO_SEGUNDOS=300   # a cada 5 minutos

while true; do
    sleep "$INTERVALO_SEGUNDOS"

    if ! git pull --rebase --quiet; then
        echo "[$(date)] git pull falhou (provavelmente edição local pendente em outro arquivo rastreado). Verifique manualmente." >&2
        continue
    fi

    if [ -z "$(git status --porcelain resultados/ 2>/dev/null)" ]; then
        continue   # nada novo desde o último sync
    fi

    git add resultados/
    git commit -m "resultados servidor ${SERVIDOR_ID} — $(date '+%Y-%m-%d %H:%M:%S')" \
        --quiet

    tentativas=0
    sucesso=0
    until git push --quiet; do
        tentativas=$((tentativas + 1))
        if [ "$tentativas" -ge 5 ]; then
            echo "[$(date)] Falha ao enviar após 5 tentativas. Verifique manualmente." >&2
            break
        fi
        git pull --rebase --quiet
    done

    if [ "$tentativas" -lt 5 ]; then
        echo "[$(date)] Resultados sincronizados (servidor ${SERVIDOR_ID})."
    fi
done
