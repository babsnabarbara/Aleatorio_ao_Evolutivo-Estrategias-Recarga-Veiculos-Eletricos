"""
genetic_algorithm.py

Mesma lógica do seu AG original, com duas mudanças estruturais pra permitir
rodar o grid search sem reconstruir grafo/executor a cada combinação e sem
depender de constantes globais fixas:

1) CROSSOVER_RATE, MUTATION_RATE, ELITISM_SIZE, TOURNAMENT_SIZE deixam de
   ser globais lidos dentro das funções — agora são parâmetros explícitos.
   Isso é o que permite o worker do grid search trocar os hiperparâmetros
   a cada tarefa sem reimportar o módulo nem usar monkey-patching.

2) A montagem do grafo (generate_graph + get_giant_component) e a criação
   do ProcessPoolExecutor saem do main() e viram responsabilidade de quem
   chama — no caso, o 3_worker.py monta isso UMA VEZ por servidor e reusa
   para as ~182 tarefas do bloco, em vez de refazer a cada tarefa (o grafo
   não muda com os hiperparâmetros nem com k).

O restante (fitness_function, checkpoints, hill-climbing) é o mesmo
algoritmo que você já validou, só reorganizado.
"""

import random
import os
import time
import logging
import json
import networkx as nx
from bs4 import BeautifulSoup
from concurrent.futures import ProcessPoolExecutor

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def _fmt_hms(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def _flush_log():
    for handler in log.handlers:
        handler.flush()


def configure_logging_for_run(log_file):
    """Reconfigura o logger pra escrever no arquivo de log de UMA execução
    específica (identificada por run_tag). Chamado antes de cada tarefa do
    grid search, senão todas as tarefas de um servidor escreveriam no mesmo
    arquivo de log misturado."""
    for handler in list(log.handlers):
        handler.close()
        log.removeHandler(handler)

    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(file_handler)


# ---------------------------------------------------------------------------
# Construção do grafo (chamada UMA VEZ pelo worker, não por tarefa)
# ---------------------------------------------------------------------------
def generate_graph(netfile):
    with open(netfile) as f:
        data = f.read()
    soup = BeautifulSoup(data, "xml")

    edges_length = {}
    for edge_tag in soup.findAll("edge"):
        edge_id = edge_tag["id"]
        lane_tag = edge_tag.find("lane")
        if lane_tag is None:
            continue
        edges_length[edge_id] = int(float(lane_tag["length"]))

    graph = nx.DiGraph()
    for connection_tag in soup.findAll("connection"):
        source_edge = connection_tag["from"]
        dest_edge = connection_tag["to"]
        if source_edge in edges_length:
            graph.add_edge(
                source_edge, dest_edge,
                length=edges_length[source_edge],
                weight=1,
            )
    return graph


def get_giant_component(graph):
    components = list(nx.strongly_connected_components(graph))
    components.sort(key=len, reverse=True)
    giant_nodes = components[0]
    log.info(
        f"Componente gigante: {len(giant_nodes)} de {len(graph.nodes)} nós "
        f"({len(graph.nodes) - len(giant_nodes)} nós de fora, em "
        f"{len(components) - 1} componentes menores)."
    )
    return graph.subgraph(giant_nodes).copy()


def montar_grafo_base(netfile):
    """Função de conveniência: monta tudo que é reutilizável entre
    tarefas (grafo revertido, lista de nós candidatos, total de nós).
    Chame isso UMA VEZ no worker, antes do loop de tarefas."""
    graph = generate_graph(netfile)
    log.info(f"Número de nós no grafo completo: {len(graph.nodes)}")
    giant_graph = get_giant_component(graph)
    candidate_nodes = list(giant_graph.nodes)
    total_nodes = len(candidate_nodes)
    reversed_graph = giant_graph.reverse(copy=False)
    return reversed_graph, candidate_nodes, total_nodes


# ---------------------------------------------------------------------------
# Fitness
# ---------------------------------------------------------------------------
def fitness_function(reversed_graph, total_nodes, stations):
    dist = nx.multi_source_dijkstra_path_length(
        reversed_graph, stations, weight="length"
    )
    assert len(dist) == total_nodes, "..."
    return sum(dist.values())


_worker_reversed_graph = None
_worker_total_nodes = None


def _init_worker(reversed_graph, total_nodes):
    global _worker_reversed_graph, _worker_total_nodes
    _worker_reversed_graph = reversed_graph
    _worker_total_nodes = total_nodes


def _fitness_worker(stations):
    return fitness_function(_worker_reversed_graph, _worker_total_nodes, stations)


def generate_initial_population(candidate_nodes, num_stations, population_size):
    population = []
    for _ in range(population_size):
        population.append(random.sample(candidate_nodes, num_stations))
    return population


def tournament_select(population, fitnesses, tournament_size):
    contenders = random.sample(range(len(population)), tournament_size)
    best_idx = min(contenders, key=lambda i: fitnesses[i])
    return population[best_idx]


def crossover(parent1, parent2, candidate_nodes, num_stations, crossover_rate):
    if random.random() >= crossover_rate:
        return list(random.choice([parent1, parent2]))

    half = num_stations // 2
    child = list(dict.fromkeys(parent1[:half] + parent2[half:]))

    while len(child) < num_stations:
        candidate = random.choice(candidate_nodes)
        if candidate not in child:
            child.append(candidate)

    return child[:num_stations]


def mutate(stations, candidate_nodes, mutation_rate):
    for idx in range(len(stations)):
        if random.random() < mutation_rate:
            candidates = [n for n in candidate_nodes if n not in stations]
            if candidates:
                stations[idx] = random.choice(candidates)
    return stations


def evaluate_population(executor, population):
    fitnesses = list(executor.map(_fitness_worker, population))
    ranked = sorted(zip(population, fitnesses), key=lambda pair: pair[1])
    return [ind for ind, _ in ranked], [fit for _, fit in ranked]


def _save_ga_checkpoint(checkpoint_file, run_tag, generation, total_generations,
                         best_solution, best_fitness, history, elapsed):
    checkpoint = {
        "run_tag": run_tag,
        "geracao_atual": generation,
        "total_geracoes": total_generations,
        "melhor_solucao_ate_agora": best_solution,
        "melhor_fitness_ate_agora": best_fitness,
        "historico_melhor_fitness": history,
        "tempo_decorrido_segundos": round(elapsed, 1),
    }
    with open(checkpoint_file, "w") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)


def genetic_algorithm(executor, candidate_nodes, num_stations, population_size, generations,
                       crossover_rate, mutation_rate, elitism_size, tournament_size,
                       run_tag, ga_checkpoint_file, checkpoint_every=10):
    ga_start = time.time()
    population = generate_initial_population(candidate_nodes, num_stations, population_size)

    population, fitnesses = evaluate_population(executor, population)
    best_fitness_history = [fitnesses[0]]
    generations_since_improvement = 0
    log.info(f"Geração 0 (inicial) — melhor fitness: {fitnesses[0]}")

    for gen in range(generations):
        next_population = population[:elitism_size]

        while len(next_population) < population_size:
            parent1 = tournament_select(population, fitnesses, tournament_size)
            parent2 = tournament_select(population, fitnesses, tournament_size)
            child = crossover(parent1, parent2, candidate_nodes, num_stations, crossover_rate)
            child = mutate(child, candidate_nodes, mutation_rate)
            next_population.append(child)

        population, fitnesses = evaluate_population(executor, next_population)
        best_fitness_history.append(fitnesses[0])

        if fitnesses[0] < best_fitness_history[-2]:
            generations_since_improvement = 0
        else:
            generations_since_improvement += 1

        log.info(
            f"Geração {gen + 1}/{generations} — melhor fitness: {fitnesses[0]} "
            f"| sem melhora há {generations_since_improvement} geração(ões)"
        )

        if (gen + 1) % checkpoint_every == 0 or (gen + 1) == generations:
            elapsed = time.time() - ga_start
            _save_ga_checkpoint(
                ga_checkpoint_file, run_tag, gen + 1, generations,
                population[0], fitnesses[0], best_fitness_history, elapsed
            )
            _flush_log()

    return population[0], fitnesses[0]


def _trial_worker(candidate_and_base):
    candidate, base_stations, idx = candidate_and_base
    trial = base_stations.copy()
    trial[idx] = candidate
    return candidate, _fitness_worker(trial)


def _save_local_search_checkpoint(checkpoint_file, run_tag, stations, best_fitness,
                                   round_num, rounds_without_improvement, exhaustive,
                                   elapsed, avg_round_seconds):
    checkpoint = {
        "run_tag": run_tag,
        "stations": stations,
        "best_fitness": best_fitness,
        "round_num": round_num,
        "rounds_without_improvement": rounds_without_improvement,
        "exhaustive": exhaustive,
        "tempo_decorrido_segundos": round(elapsed, 1),
        "tempo_medio_por_rodada_segundos": round(avg_round_seconds, 1) if avg_round_seconds else None,
    }
    with open(checkpoint_file, "w") as f:
        json.dump(checkpoint, f, indent=2, ensure_ascii=False)


def load_local_search_checkpoint(checkpoint_file):
    if not os.path.exists(checkpoint_file):
        return None
    with open(checkpoint_file) as f:
        return json.load(f)


def local_search(executor, stations, candidate_nodes, run_tag, checkpoint_file,
                  exhaustive=True, max_no_improve=1, resume=True):
    round_num = 0
    rounds_without_improvement = 0
    round_durations = []
    search_start = time.time()

    checkpoint = load_local_search_checkpoint(checkpoint_file) if resume else None
    if checkpoint is not None and checkpoint.get("run_tag") == run_tag:
        stations = list(checkpoint["stations"])
        best_fitness = checkpoint["best_fitness"]
        round_num = checkpoint["round_num"]
        rounds_without_improvement = checkpoint["rounds_without_improvement"]
        log.info(
            f"[Hill-climbing] checkpoint encontrado — retomando da rodada "
            f"{round_num} | fitness: {best_fitness}"
        )
    else:
        stations = list(stations)
        best_fitness = executor.submit(_fitness_worker, stations).result()
        log.info(f"[Hill-climbing] fitness inicial: {best_fitness} (modo exaustivo: {exhaustive})")

    while rounds_without_improvement < max_no_improve:
        round_num += 1
        round_start = time.time()
        improved_this_round = False

        for idx in range(len(stations)):
            current_gene = stations[idx]

            if exhaustive:
                trial_candidates = [n for n in candidate_nodes if n not in stations]
            else:
                sample_size = min(3000, len(candidate_nodes))
                trial_candidates = [
                    n for n in random.sample(candidate_nodes, sample_size)
                    if n not in stations
                ]

            tasks = [(c, stations, idx) for c in trial_candidates]
            results = executor.map(_trial_worker, tasks, chunksize=200)

            for candidate, trial_fitness in results:
                if trial_fitness < best_fitness:
                    stations[idx] = candidate
                    best_fitness = trial_fitness
                    improved_this_round = True
                    current_gene = candidate

            log.info(
                f"[Hill-climbing] rodada {round_num}, gene {idx} testado "
                f"({len(trial_candidates)} candidatos) — melhor até agora: "
                f"{current_gene} | fitness: {best_fitness}"
            )

        round_elapsed = time.time() - round_start
        round_durations.append(round_elapsed)
        avg_round = sum(round_durations) / len(round_durations)
        total_elapsed = time.time() - search_start

        rodadas_restantes_estimadas = max(max_no_improve - (
            0 if improved_this_round else rounds_without_improvement + 1
        ), 0) + (1 if improved_this_round else 0)
        eta_seconds = avg_round * rodadas_restantes_estimadas

        log.info(
            f"[Hill-climbing] rodada {round_num} concluída em {_fmt_hms(round_elapsed)} "
            f"(média por rodada: {_fmt_hms(avg_round)}) — melhorou nesta rodada: "
            f"{improved_this_round} | tempo total até agora: {_fmt_hms(total_elapsed)} "
            f"| ETA aproximado p/ conclusão: {_fmt_hms(eta_seconds)}"
        )

        if improved_this_round:
            rounds_without_improvement = 0
        else:
            rounds_without_improvement += 1

        _save_local_search_checkpoint(
            checkpoint_file, run_tag, stations, best_fitness, round_num,
            rounds_without_improvement, exhaustive, total_elapsed, avg_round
        )
        _flush_log()

    log.info(f"[Hill-climbing] fitness final: {best_fitness}")

    if os.path.exists(checkpoint_file):
        os.remove(checkpoint_file)

    return stations, best_fitness


# ---------------------------------------------------------------------------
# Ponto de entrada usado pelo grid search: roda UMA combinação de
# hiperparâmetros, reaproveitando grafo e executor já montados.
# ---------------------------------------------------------------------------
def rodar_combinacao(executor, candidate_nodes, num_stations, params, seed, run_tag,
                      log_dir="logs", checkpoint_dir="checkpoints",
                      usar_local_search=False, local_search_max_no_improve=2):
    """
    executor: ProcessPoolExecutor já criado (com _init_worker já aplicado)
    candidate_nodes: lista de nós candidatos (do componente gigante)
    num_stations: k desta tarefa
    params: dict com crossover_rate, mutation_rate, population_size,
            elitism_size, tournament_size, num_generations
    seed: seed do random para esta execução
    run_tag: identificador único desta tarefa (ex.: "servidor0_tarefa17"),
             usado nos nomes de arquivo de log/checkpoint
    usar_local_search: False por padrão no grid search de hiperparâmetros
        do AG — o refinamento exaustivo é caro e não faz parte do que está
        sendo comparado aqui (decisão já discutida: isolar o efeito do AG).
    """
    os.makedirs(log_dir, exist_ok=True)
    os.makedirs(checkpoint_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"{run_tag}.log")
    ga_checkpoint_file = os.path.join(checkpoint_dir, f"ga_{run_tag}.json")
    local_search_checkpoint_file = os.path.join(checkpoint_dir, f"ls_{run_tag}.json")

    configure_logging_for_run(log_file)
    random.seed(seed)

    log.info("=" * 70)
    log.info(f"Iniciando tarefa — {run_tag} | k={num_stations} | seed={seed}")
    log.info(f"Hiperparâmetros: {params}")
    _flush_log()

    start_time = time.time()

    ga_start = time.time()
    best_solution, best_fitness = genetic_algorithm(
        executor, candidate_nodes, num_stations,
        params["population_size"], params["num_generations"],
        params["crossover_rate"], params["mutation_rate"],
        params["elitism_size"], params["tournament_size"],
        run_tag, ga_checkpoint_file,
    )
    ga_elapsed = time.time() - ga_start
    log.info(f"AG concluído em {_fmt_hms(ga_elapsed)} — melhor fitness: {best_fitness}")
    _flush_log()

    refined_solution, refined_fitness = best_solution, best_fitness
    refine_elapsed = 0.0
    if usar_local_search:
        refine_start = time.time()
        refined_solution, refined_fitness = local_search(
            executor, best_solution, candidate_nodes, run_tag,
            local_search_checkpoint_file, exhaustive=True,
            max_no_improve=local_search_max_no_improve,
        )
        refine_elapsed = time.time() - refine_start
        log.info(f"Refinamento concluído em {_fmt_hms(refine_elapsed)}")

    total_elapsed = time.time() - start_time
    log.info(f"Tempo total da tarefa: {_fmt_hms(total_elapsed)}")
    log.info(f"Fitness final: {refined_fitness}")
    log.info("=" * 70)
    _flush_log()

    # Remove o checkpoint do AG ao final (o de local_search já se
    # autolimpa dentro de local_search() quando termina).
    if os.path.exists(ga_checkpoint_file):
        os.remove(ga_checkpoint_file)

    return {
        "fitness": refined_fitness,
        "fitness_ga": best_fitness,
        "estacoes": refined_solution,
        "estacoes_ga": best_solution,
        "tempo_ag_segundos": round(ga_elapsed, 1),
        "tempo_refinamento_segundos": round(refine_elapsed, 1),
        "tempo_total_segundos": round(total_elapsed, 1),
        "seed": seed,
        "usou_local_search": usar_local_search,
    }


# ---------------------------------------------------------------------------
# Uso standalone (fora do grid search): mantém a possibilidade de rodar
# uma única combinação/k/seed isolada, como antes.
# ---------------------------------------------------------------------------
DEFAULT_PARAMS = {
    "crossover_rate": 0.8,
    "mutation_rate": 0.12,
    "population_size": 300,
    "elitism_size": 8,
    "tournament_size": 7,
    "num_generations": 250,
}


def main(seed, num_stations=49, params=None, netfile="input/cologne.net.xml",
         usar_local_search=True):
    params = params or DEFAULT_PARAMS
    run_tag = f"k{num_stations}_seed{seed}"

    reversed_graph, candidate_nodes, total_nodes = montar_grafo_base(netfile)

    with ProcessPoolExecutor(
        max_workers=os.cpu_count(),
        initializer=_init_worker,
        initargs=(reversed_graph, total_nodes),
    ) as executor:
        resultado = rodar_combinacao(
            executor, candidate_nodes, num_stations, params, seed, run_tag,
            usar_local_search=usar_local_search,
        )

    result_file = f"resultado_final_{run_tag}.json"
    with open(result_file, "w") as f:
        json.dump({"seed": seed, "num_estacoes": num_stations, **resultado}, f,
                   indent=2, ensure_ascii=False)

    return resultado


if __name__ == "__main__":
    for s in [42, 123, 777, 2024, 555]:
        main(seed=s)
