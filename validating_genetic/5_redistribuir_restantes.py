"""
5_redistribuir_restantes.py

Roda numa máquina com o repositório git já atualizado (git pull feito
antes), contendo os resultados/ de TODOS os servidores que já
sincronizaram (via sync_resultados.sh ou captura manual).

Descobre quais tarefas ainda faltam (comparando tarefas_completas.json
contra os ids presentes em resultados/) e gera um novo conjunto de
tarefas_servidor_N.json -- SOBRESCREVENDO os antigos -- só com o que
falta, redistribuído pelos servidores ATIVOS no momento (dá pra excluir
um servidor temporariamente indisponível, ex.: ocupado com outro
projeto, via --ativos).

Diferença em relação ao 2_distribuir_tarefas.py original: usa pesos
IGUAIS (1.0) para todos, não mais o peso 1.5 do Xeon -- os tempos reais
medidos mostraram que essa vantagem não se confirmou na prática (tarefas
rodando 15-70% mais devagar que o estimado no Xeon), então reequilibrar
com peso igual é mais seguro que continuar confiando numa estimativa que
já se mostrou errada.

USO:
    # Todos os 4 servidores disponíveis (default)
    python3 5_redistribuir_restantes.py

    # Só 0 (Xeon), 2 (lcad2) e 3 (LCAD1) -- ex.: LCAD3 (índice 1) ainda
    # ocupada com outro projeto
    python3 5_redistribuir_restantes.py --ativos 0,2,3
"""

import argparse
import json
import heapq
import os

NUM_SERVIDORES_TOTAL = 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ativos", default="0,1,2,3",
        help="Índices dos servidores disponíveis AGORA para receber "
             "tarefas, separados por vírgula (default: todos). Servidores "
             "fora dessa lista não recebem arquivo novo -- o "
             "tarefas_servidor_N.json deles fica intocado."
    )
    args = ap.parse_args()
    ativos = sorted(int(x) for x in args.ativos.split(","))
    print(f"Servidores ativos nesta redistribuição: {ativos}")

    with open("tarefas_completas.json") as f:
        todas = json.load(f)

    ja_feitas = {
        int(nome.split("_")[1].split(".")[0])
        for nome in os.listdir("resultados")
        if nome.startswith("tarefa_") and nome.endswith(".json")
    }

    pendentes = [t for t in todas if t["id"] not in ja_feitas]
    print(f"Total de tarefas: {len(todas)}")
    print(f"Já concluídas (encontradas em resultados/): {len(ja_feitas)}")
    print(f"Pendentes a redistribuir: {len(pendentes)}")

    if not pendentes:
        print("Nada pendente -- não há o que redistribuir.")
        return

    # Reseta status para permitir reatribuição limpa
    for t in pendentes:
        t["status"] = "pendente"
        t["servidor_atribuido"] = None

    # LPT com pesos iguais, só entre os servidores ativos
    pendentes_ordenadas = sorted(
        pendentes, key=lambda t: t["tempo_estimado_segundos"], reverse=True
    )
    heap = [(0.0, i) for i in ativos]
    heapq.heapify(heap)
    blocos = {i: [] for i in ativos}
    carga = {i: 0.0 for i in ativos}

    for tarefa in pendentes_ordenadas:
        carga_atual, servidor = heapq.heappop(heap)
        blocos[servidor].append(tarefa)
        carga[servidor] += tarefa["tempo_estimado_segundos"]
        heapq.heappush(heap, (carga[servidor], servidor))
        tarefa["servidor_atribuido"] = servidor

    print(f"\n{'Servidor':<10}{'Nº tarefas':<12}{'~dias':<8}")
    for i in ativos:
        bloco = blocos[i]
        dias = carga[i] / 3600 / 24
        print(f"{i:<10}{len(bloco):<12}{dias:<8.2f}")
        with open(f"tarefas_servidor_{i}.json", "w") as f:
            json.dump(bloco, f, indent=2)

    fora = set(range(NUM_SERVIDORES_TOTAL)) - set(ativos)
    if fora:
        print(f"\nServidor(es) {sorted(fora)} NÃO receberam arquivo novo "
              f"(ficaram de fora desta rodada) -- tarefas_servidor_N.json "
              f"deles ficou como estava.")

    print("\nFaça 'git add tarefas_servidor_*.json tarefas_completas.json "
          "&& git commit && git push' e reinicie o worker nos servidores "
          "ativos.")


if __name__ == "__main__":
    main()



if __name__ == "__main__":
    main()
