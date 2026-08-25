"""
1_gerar_tarefas.py  (versão k=25 apenas)

Gera as 729 tarefas do grid de hiperparâmetros para k=25 (só esse valor).

Diferença importante em relação à versão anterior: como agora todas as
tarefas compartilham o mesmo k, usar a mesma média de tempo pra todas
faria o LPT não ter nada pra balancear (tudo pareceria "igual"). Em vez
disso, a estimativa de tempo de cada tarefa é escalada pelo número
aproximado de avaliações de fitness dela: population_size * num_generations
(mais indivíduos e/ou mais gerações = proporcionalmente mais avaliações,
que é o que domina o tempo de execução). O tempo médio real medido para
k=25 (6482s) é usado como âncora, ajustado pela combinação relativa de
cada tarefa em torno da média do grid.

Roda uma vez. Gera 'tarefas_completas.json'.
"""

import itertools
import json

# ---------------------------------------------------------------------------
# Espaço de hiperparâmetros do AG
# ---------------------------------------------------------------------------
CROSSOVER_RATE_OPTS = [0.7, 0.8, 0.9]
MUTATION_RATE_OPTS = [0.08, 0.12, 0.18]
POPULATION_SIZE_OPTS = [200, 300, 500]
ELITISM_SIZE_OPTS = [4, 8, 12]
TOURNAMENT_SIZE_OPTS = [5, 7, 10]
NUM_GENERATIONS_OPTS = [150, 250, 350]

K = 25
TEMPO_MEDIO_K25_SEGUNDOS = 6482  # âncora: sua média real medida para k=25


def gerar_combinacoes_hiperparametros():
    return list(itertools.product(
        CROSSOVER_RATE_OPTS, MUTATION_RATE_OPTS, POPULATION_SIZE_OPTS,
        ELITISM_SIZE_OPTS, TOURNAMENT_SIZE_OPTS, NUM_GENERATIONS_OPTS
    ))


def main():
    combinacoes = gerar_combinacoes_hiperparametros()
    print(f"{len(combinacoes)} combinações de hiperparâmetros geradas para k={K}.")

    # "custo relativo" de cada combinação = population_size * num_generations
    custos = [p * g for (_, _, p, _, _, g) in combinacoes]
    custo_medio = sum(custos) / len(custos)

    tarefas = []
    for task_id, ((c, m, p, e, t, g), custo) in enumerate(zip(combinacoes, custos)):
        tempo_estimado = TEMPO_MEDIO_K25_SEGUNDOS * (custo / custo_medio)
        tarefas.append({
            "id": task_id,
            "k": K,
            "params": {
                "crossover_rate": c,
                "mutation_rate": m,
                "population_size": p,
                "elitism_size": e,
                "tournament_size": t,
                "num_generations": g,
            },
            "tempo_estimado_segundos": round(tempo_estimado, 1),
            "status": "pendente",
            "servidor_atribuido": None,
            "tempo_real_segundos": None,
            "resultado": None,
        })

    with open("tarefas_completas.json", "w") as f:
        json.dump(tarefas, f, indent=2)

    total_horas = sum(t["tempo_estimado_segundos"] for t in tarefas) / 3600
    menor = min(t["tempo_estimado_segundos"] for t in tarefas)
    maior = max(t["tempo_estimado_segundos"] for t in tarefas)
    print(f"Tempo sequencial total estimado: {total_horas:.1f}h "
          f"(~{total_horas / 24:.1f} dias numa única máquina)")
    print(f"Faixa de tempo estimado por tarefa: {menor:.0f}s a {maior:.0f}s "
          f"(razão {maior / menor:.1f}x entre a mais barata e a mais cara)")
    print("Arquivo salvo: tarefas_completas.json")


if __name__ == "__main__":
    main()
