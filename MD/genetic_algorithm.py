import random
import os
import time
import logging
import json
import networkx as nx
from bs4 import BeautifulSoup
from concurrent.futures import ProcessPoolExecutor

CROSSOVER_RATE = 0.8
MUTATION_RATE = 0.12
NUM_GENERATIONS = 250
POPULATION_SIZE = 300
NUM_STATIONS = 49
ELITISM_SIZE = 8
TOURNAMENT_SIZE = 7
NUM_WORKERS = os.cpu_count()

# Lista de seeds a rodar em sequência, cada uma com seu próprio conjunto de
# arquivos (log, checkpoints, resultado) -- não colidem entre si nem com
# execuções anteriores de uma seed só.
SEEDS_PARA_TESTAR = [42, 123, 777, 2024, 555]

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def _fmt_hms(seconds):
    """Formata segundos como Hh Mm Ss, só para deixar os logs de tempo
    legíveis em execuções longas (ex: 33h vira '33h 02m 14s')."""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m:02d}m {s:02d}s"


def _flush_log():
    """Força a escrita imediata no arquivo de log. Importante em execuções
    de muitas horas: sem isso, o buffer do SO pode segurar linhas na
    memória e você perde visibilidade em tempo real ao acompanhar o log
    remotamente (ex: tail -f)."""
    for handler in log.handlers:
        handler.flush()


def _configure_logging_for_run(log_file):
    """Reconfigura o logger para escrever no arquivo de log específico
    desta seed. Precisa remover o handler anterior (de uma seed anterior,
    se houver) para não continuar escrevendo no arquivo errado."""
    for handler in list(log.handlers):
        handler.close()
        log.removeHandler(handler)

    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    log.addHandler(file_handler)


# ---------------------------------------------------------------------------
# Construção do grafo
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


# ---------------------------------------------------------------------------
# Componente fortemente conexo gigante
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Fitness — Dijkstra multi-fonte no grafo (já restrito ao componente gigante)
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


def crossover(parent1, parent2, candidate_nodes, num_stations):
    if random.random() >= CROSSOVER_RATE:
        return list(random.choice([parent1, parent2]))

    half = num_stations // 2
    child = list(dict.fromkeys(parent1[:half] + parent2[half:]))

    while len(child) < num_stations:
        candidate = random.choice(candidate_nodes)
        if candidate not in child:
            child.append(candidate)

    return child[:num_stations]


def mutate(stations, candidate_nodes):
    for idx in range(len(stations)):
        if random.random() < MUTATION_RATE:
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
                       run_tag, ga_checkpoint_file, checkpoint_every=10):
    ga_start = time.time()
    population = generate_initial_population(candidate_nodes, num_stations, population_size)

    population, fitnesses = evaluate_population(executor, population)
    best_fitness_history = [fitnesses[0]]
    generations_since_improvement = 0
    log.info(f"Geração 0 (inicial) — melhor fitness: {fitnesses[0]}")

    for gen in range(generations):
        next_population = population[:ELITISM_SIZE]

        while len(next_population) < population_size:
            parent1 = tournament_select(population, fitnesses, TOURNAMENT_SIZE)
            parent2 = tournament_select(population, fitnesses, TOURNAMENT_SIZE)
            child = crossover(parent1, parent2, candidate_nodes, num_stations)
            child = mutate(child, candidate_nodes)
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
# Main — agora recebe a seed como parâmetro. Cada chamada recalcula
# RUN_TAG e todos os nomes de arquivo (log, checkpoints, resultado) a
# partir dela, e reconfigura o logger para escrever no log específico
# desta seed antes de começar.
# ---------------------------------------------------------------------------
def main(seed):
    run_tag = f"k{NUM_STATIONS}_seed{seed}"
    log_file = f"genetic_algorithm_{run_tag}.log"
    result_file = f"resultado_final_{run_tag}.json"
    local_search_checkpoint_file = f"checkpoint_local_search_{run_tag}.json"
    ga_checkpoint_file = f"checkpoint_ga_{run_tag}.json"

    _configure_logging_for_run(log_file)

    start_time = time.time()
    random.seed(seed)
    log.info("=" * 70)
    log.info(f"Iniciando execução — {run_tag}")
    log.info(f"Seed utilizada: {seed}")
    _flush_log()

    netfile = "../input/cologne.net.xml"
    log.info(f"Arquivo existe? {os.path.exists(netfile)}")

    graph = generate_graph(netfile)
    log.info(f"Número de nós no grafo completo: {len(graph.nodes)}")
    log.info(f"Número de estações desejadas: {NUM_STATIONS}")

    giant_graph = get_giant_component(graph)
    candidate_nodes = list(giant_graph.nodes)
    total_nodes = len(candidate_nodes)
    reversed_graph = giant_graph.reverse(copy=False)

    with ProcessPoolExecutor(
        max_workers=NUM_WORKERS,
        initializer=_init_worker,
        initargs=(reversed_graph, total_nodes),
    ) as executor:

        ga_start = time.time()
        best_solution, best_fitness = genetic_algorithm(
            executor, candidate_nodes, NUM_STATIONS, POPULATION_SIZE, NUM_GENERATIONS,
            run_tag, ga_checkpoint_file
        )
        ga_elapsed = time.time() - ga_start
        log.info(f"AG concluído em {_fmt_hms(ga_elapsed)} — melhor fitness: {best_fitness}")
        log.info(f"Melhores localizações de estações (antes do refinamento): {best_solution}")
        _flush_log()

        refine_start = time.time()
        refined_solution, refined_fitness = local_search(
            executor, best_solution, candidate_nodes, run_tag,
            local_search_checkpoint_file, exhaustive=True, max_no_improve=2
        )
        refine_elapsed = time.time() - refine_start
        log.info(f"Refinamento concluído em {_fmt_hms(refine_elapsed)}")

    total_elapsed = time.time() - start_time
    log.info(f"Tempo total de execução: {_fmt_hms(total_elapsed)}")
    log.info(f"Solução final: {refined_solution} | fitness: {refined_fitness}")
    log.info("=" * 70)
    _flush_log()

    result = {
        "seed": seed,
        "num_estacoes": NUM_STATIONS,
        "solucao_ga": best_solution,
        "fitness_ga": best_fitness,
        "solucao_final_refinada": refined_solution,
        "fitness_final": refined_fitness,
        "tempo_ag_segundos": round(ga_elapsed, 1),
        "tempo_refinamento_segundos": round(refine_elapsed, 1),
        "tempo_total_segundos": round(total_elapsed, 1),
        "num_geracoes": NUM_GENERATIONS,
        "tamanho_populacao": POPULATION_SIZE,
    }
    with open(result_file, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


if __name__ == "__main__":
    for s in SEEDS_PARA_TESTAR:
        main(seed=s)
