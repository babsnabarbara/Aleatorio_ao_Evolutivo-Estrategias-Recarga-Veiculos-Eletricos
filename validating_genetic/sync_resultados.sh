#!/bin/bash
# sync_resultados.sh
#
# Roda em background em CADA servidor, junto com o worker. A cada
# INTERVALO_SEGUNDOS, adiciona os resultados novos em resultados/,
# commita e envia pro repositório remoto. Como os ids de tarefa nunca
# se repetem entre servidores, isso nunca gera conflito de merge —
# na pior hipótese, um "git pull --rebase" resolve um push rejeitado
# por não ser fast-forward (outro servidor commitou entre seu pull e
# seu push).
#
# USO:
#   chmod +x sync_resultados.sh
#   nohup ./sync_resultados.sh 0 > sync_0.out 2>&1 &
#   disown

SERVIDOR_ID="${1:?Uso: ./sync_resultados.sh <indice_do_servidor>}"
INTERVALO_SEGUNDOS=300   # a cada 5 minutos

while true; do
    sleep "$INTERVALO_SEGUNDOS"

    if [ -z "$(git status --porcelain resultados/ 2>/dev/null)" ]; then
        continue   # nada novo desde o último sync
    fi

    git add resultados/
    git commit -m "resultados servidor ${SERVIDOR_ID} — $(date '+%Y-%m-%d %H:%M:%S')" \
        --quiet

    # Tenta enviar; se o remoto tiver commits novos de outro servidor,
    # faz rebase e tenta de novo (poucas tentativas, pra não travar
    # rodando pra sempre num loop de erro real).
    tentativas=0
    until git push --quiet; do
        tentativas=$((tentativas + 1))
        if [ "$tentativas" -ge 5 ]; then
            echo "[$(date)] Falha ao enviar após 5 tentativas. Verifique manualmente." >&2
            break
        fi
        git pull --rebase --quiet
    done

    echo "[$(date)] Resultados sincronizados (servidor ${SERVIDOR_ID})."
done
