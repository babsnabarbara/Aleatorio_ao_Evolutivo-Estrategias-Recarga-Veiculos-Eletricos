"""
2_distribuir_tarefas.py

Distribui as tarefas de 'tarefas_completas.json' entre N servidores usando
o algoritmo LPT (Longest Processing Time first): ordena as tarefas da mais
lenta pra mais rápida e vai atribuindo cada uma ao servidor que, NAQUELE
MOMENTO, tem menos carga acumulada. Isso equilibra o TEMPO TOTAL estimado
por servidor, não o número de tarefas — essencial aqui porque k=49 demora
~6x mais que k=9.

Se seus servidores tiverem capacidades diferentes (ex. um Xeon mais potente),
ajuste PESOS_SERVIDORES abaixo (peso maior = servidor mais rápido, recebe
mais carga proporcionalmente). Com pesos iguais, o balanceamento é justo.

Gera um arquivo 'tarefas_servidor_N.json' para cada servidor N (0..3).
"""

import json
import heapq

NUM_SERVIDORES = 4

# Pesos relativos de capacidade de cada servidor, proporcionais ao número
# de cores (RAM/disco não são o gargalo aqui — todos têm sobra).
# Mapeamento índice -> máquina (ajuste os nomes conforme copiar os
# arquivos tarefas_servidor_N.json para cada uma):
#   0 = Xeon2x414R (48 cores) -> peso 1.5
#   1 = LCAD3      (32 cores) -> peso 1.0
#   2 = lcad2      (32 cores) -> peso 1.0
#   3 = LCAD1      (32 cores) -> peso 1.0
PESOS_SERVIDORES = [1.5, 1.0, 1.0, 1.0]


def distribuir_lpt(tarefas, num_servidores, pesos):
    """Retorna uma lista de listas: tarefas[servidor_i]."""
    assert len(pesos) == num_servidores

    # Só distribui o que ainda não foi feito (permite rodar de novo depois
    # de uma falha parcial sem reembaralhar tudo).
    pendentes = [t for t in tarefas if t["status"] == "pendente"]

    # Ordena da tarefa mais demorada pra mais rápida (chave do LPT)
    pendentes.sort(key=lambda t: t["tempo_estimado_segundos"], reverse=True)

    # Heap de (carga_atual_ajustada_pelo_peso, id_servidor)
    heap = [(0.0, i) for i in range(num_servidores)]
    heapq.heapify(heap)

    blocos = [[] for _ in range(num_servidores)]
    carga_real = [0.0] * num_servidores

    for tarefa in pendentes:
        carga_ajustada, servidor = heapq.heappop(heap)
        blocos[servidor].append(tarefa)
        carga_real[servidor] += tarefa["tempo_estimado_segundos"]
        # carga "ajustada" = carga real dividida pelo peso (servidor mais
        # rápido -> peso maior -> carga ajustada cresce mais devagar ->
        # continua recebendo tarefas por mais tempo antes de "encher")
        nova_carga_ajustada = carga_real[servidor] / pesos[servidor]
        heapq.heappush(heap, (nova_carga_ajustada, servidor))
        tarefa["servidor_atribuido"] = servidor

    return blocos, carga_real


def main():
    with open("tarefas_completas.json") as f:
        tarefas = json.load(f)

    blocos, carga_real = distribuir_lpt(tarefas, NUM_SERVIDORES, PESOS_SERVIDORES)

    # Tempo de PAREDE (wall-clock) de cada servidor = trabalho recebido /
    # sua capacidade. É isso que precisa ficar equilibrado entre servidores
    # com pesos diferentes — não o volume bruto de trabalho (carga_real),
    # que é maior de propósito nos servidores mais rápidos.
    carga_ajustada = [carga_real[i] / PESOS_SERVIDORES[i] for i in range(NUM_SERVIDORES)]

    print("Resumo da distribuição (LPT, balanceada por tempo de parede estimado):\n")
    print(f"{'Servidor':<10}{'Peso':<7}{'Nº tarefas':<12}{'Trabalho (h)':<15}{'Tempo parede':<15}{'~dias':<8}")
    for i, bloco in enumerate(blocos):
        trabalho_h = carga_real[i] / 3600
        parede_h = carga_ajustada[i] / 3600
        dias = parede_h / 24
        print(f"{i:<10}{PESOS_SERVIDORES[i]:<7}{len(bloco):<12}{trabalho_h:<15.1f}{parede_h:<15.1f}{dias:<8.2f}")

        # Quebra por k dentro de cada servidor, pra você conferir a mistura
        por_k = {}
        for t in bloco:
            por_k[t["k"]] = por_k.get(t["k"], 0) + 1
        detalhe = ", ".join(f"k={k}:{n}" for k, n in sorted(por_k.items()))
        print(f"           ({detalhe})")

        with open(f"tarefas_servidor_{i}.json", "w") as f:
            json.dump(bloco, f, indent=2)

    # Também salva o arquivo completo atualizado (com servidor_atribuido
    # preenchido), útil para o script de combinação de resultados depois.
    with open("tarefas_completas.json", "w") as f:
        json.dump(tarefas, f, indent=2)

    maior = max(carga_ajustada) / 3600
    menor = min(carga_ajustada) / 3600
    print(f"\nDesbalanceamento de tempo de parede entre servidores: "
          f"{maior - menor:.1f}h ({(maior - menor) / maior * 100:.1f}% do maior)")
    print("Arquivos gerados: tarefas_servidor_0.json ... "
          f"tarefas_servidor_{NUM_SERVIDORES - 1}.json")


if __name__ == "__main__":
    main()
