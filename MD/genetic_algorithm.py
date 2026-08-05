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
NUM_STATIONS = 9
ELITISM_SIZE = 8
TOURNAMENT_SIZE = 7
NUM_WORKERS = os.cpu_count()
SEED = 123  # <-- SEED: fixa a semente para reprodutibilidade

LOG_FILE = "genetic_algorithm.log"
RESULT_FILE = "resultado_final.json"

# ---------------------------------------------------------------------------
# Configuração de log em arquivo (em vez de print na tela)
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename=LOG_FILE,
    filemode="a",  # "a" = acrescenta ao final do arquivo a cada execução; use "w" para sobrescrever
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Estado global por processo worker — carregado UMA VEZ quando o processo
# nasce (via `initializer`), evitando reenviar o grafo inteiro a cada
# avaliação de fitness. Isso é o que elimina o overhead de pickling
# repetido do grafo (~71 mil nós) em toda chamada.
# ---------------------------------------------------------------------------
_worker_reversed_graph = None
_worker_total_nodes = None


def _init_worker(reversed_graph, total_nodes):
    global _worker_reversed_graph, _worker_total_nodes
    _worker_reversed_graph = reversed_graph
    _worker_total_nodes = total_nodes


def _fitness_worker(stations):
    return fitness_function(_worker_reversed_graph, _worker_total_nodes, stations)


# ---------------------------------------------------------------------------
# População inicial
# ---------------------------------------------------------------------------
def generate_initial_population(candidate_nodes, num_stations, population_size):
    population = []
    for _ in range(population_size):
        population.append(random.sample(candidate_nodes, num_stations))
    return population


# ---------------------------------------------------------------------------
# Seleção por torneio
# ---------------------------------------------------------------------------
def tournament_select(population, fitnesses, tournament_size):
    contenders = random.sample(range(len(population)), tournament_size)
    best_idx = min(contenders, key=lambda i: fitnesses[i])
    return population[best_idx]


# ---------------------------------------------------------------------------
# Crossover
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Mutação — cada gene (estação) tem sua própria chance independente
# ---------------------------------------------------------------------------
def mutate(stations, candidate_nodes):
    for idx in range(len(stations)):
        if random.random() < MUTATION_RATE:
            candidates = [n for n in candidate_nodes if n not in stations]
            if candidates:
                stations[idx] = random.choice(candidates)
    return stations


# ---------------------------------------------------------------------------
# Avaliação paralela da população
# ---------------------------------------------------------------------------
def evaluate_population(executor, population):
    fitnesses = list(executor.map(_fitness_worker, population))
    ranked = sorted(zip(population, fitnesses), key=lambda pair: pair[1])
    return [ind for ind, _ in ranked], [fit for _, fit in ranked]


# ---------------------------------------------------------------------------
# Algoritmo Genético
# ---------------------------------------------------------------------------
def genetic_algorithm(executor, candidate_nodes, num_stations, population_size, generations):
    population = generate_initial_population(candidate_nodes, num_stations, population_size)

    population, fitnesses = evaluate_population(executor, population)
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
        log.info(f"Geração {gen+1}/{generations} — melhor fitness: {fitnesses[0]}")

    return population[0], fitnesses[0]


# ---------------------------------------------------------------------------
# Refinamento local (hill-climbing) pós-AG
# ---------------------------------------------------------------------------
def _trial_worker(candidate_and_base):
    """Testa UM candidato: substitui o gene `idx` da solução base por
    `candidate` e devolve o fitness resultante. Roda em paralelo (usa o
    grafo já carregado como estado global do worker)."""
    candidate, base_stations, idx = candidate_and_base
    trial = base_stations.copy()
    trial[idx] = candidate
    return candidate, _fitness_worker(trial)


def local_search(executor, stations, candidate_nodes, exhaustive=True, max_no_improve=1):
    """Tenta melhorar a melhor solução do AG trocando, uma de cada vez, cada
    estação por outro nó candidato, mantendo a troca sempre que reduzir o
    fitness. Cada rodada testa TODOS os candidatos (exhaustive=True) ou uma
    amostra grande (exhaustive=False), em paralelo entre os processos do
    pool. Roda até `max_no_improve` passadas completas sem nenhuma melhoria."""
    stations = list(stations)
    best_fitness = executor.submit(_fitness_worker, stations).result()
    log.info(f"[Hill-climbing] fitness inicial: {best_fitness} (modo exaustivo: {exhaustive})")

    rounds_without_improvement = 0
    round_num = 0

    while rounds_without_improvement < max_no_improve:
        round_num += 1
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

        if improved_this_round:
            rounds_without_improvement = 0
        else:
            rounds_without_improvement += 1

    log.info(f"[Hill-climbing] fitness final: {best_fitness}")
    return stations, best_fitness


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    start_time = time.time()
    random.seed(SEED)  # <-- SEED: fixado antes de qualquer chamada aleatória
    log.info("=" * 70)
    log.info("Iniciando execução")
    log.info(f"Seed utilizada: {SEED}")  # <-- SEED: rastreabilidade no log

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
            executor, candidate_nodes, NUM_STATIONS, POPULATION_SIZE, NUM_GENERATIONS
        )
        ga_elapsed = time.time() - ga_start
        log.info(f"AG concluído em {ga_elapsed:.1f}s — melhor fitness: {best_fitness}")
        log.info(f"Melhores localizações de estações (antes do refinamento): {best_solution}")

        refine_start = time.time()
        refined_solution, refined_fitness = local_search(
            executor, best_solution, candidate_nodes, exhaustive=False, max_no_improve=2
        )
        refine_elapsed = time.time() - refine_start
        log.info(f"Refinamento concluído em {refine_elapsed:.1f}s")

    total_elapsed = time.time() - start_time
    log.info(f"Tempo total de execução: {total_elapsed:.1f}s")
    log.info(f"Solução final: {refined_solution} | fitness: {refined_fitness}")
    log.info("=" * 70)

    result = {
        "seed": SEED,  # <-- SEED: registrado no JSON de resultado
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
    with open(RESULT_FILE, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()