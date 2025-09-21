import random
import networkx as nx
from bs4 import BeautifulSoup
import os

CROSSOVER_RATE = 0.8
MUTATION_RATE = 0.1
NUM_GENERATIONS = 100
POPULATION_SIZE = 50    
NUM_STATIONS = 5

# Função de Fitness: calcula a distância total entre os nós e as estações de carregamento
def fitness_function(graph, stations):
    total_distance = 0
    for node in graph.nodes:
        distances = [nx.shortest_path_length(graph, source=node, target=station, weight='length') for station in stations]
        total_distance += min(distances)  # Menor distância até uma estação
    return total_distance

# Geração de população inicial
def generate_initial_population(graph, num_stations, population_size):
    population = []
    nodes = list(graph.nodes)
    for _ in range(population_size):
        stations = random.sample(nodes, num_stations)
        population.append(stations)
    return population

# Operador de Crossover
def crossover(parent1, parent2):
    if random.random() < CROSSOVER_RATE:
        half = len(parent1) // 2
        child = parent1[:half] + parent2[half:]
        return list(set(child))[:len(parent1)]  # Remove duplicatas e ajusta tamanho
    else:
        return random.choice([parent1, parent2])
    
# Operador de Mutação
def mutate(stations, graph):
    if random.random() < MUTATION_RATE:
        nodes = list(graph.nodes)
        idx = random.randint(0, len(stations) - 1)
        stations[idx] = random.choice(nodes)
    return stations

# Algoritmo Genético
def genetic_algorithm(graph, num_stations, population_size, generations):
    population = generate_initial_population(graph, num_stations, population_size)
    for _ in range(generations):
        # Avaliar a população
        population = sorted(population, key=lambda stations: fitness_function(graph, stations))
        # Seleção (os melhores indivíduos)
        parents = population[:population_size // 2]
        # Crossover e Mutação para gerar novos indivíduos
        offspring = []
        while len(offspring) < population_size:
            parent1, parent2 = random.sample(parents, 2)
            child = mutate(crossover(parent1, parent2), graph)
            offspring.append(child)
        population = offspring
    return sorted(population, key=lambda stations: fitness_function(graph, stations))[0]

# Main
def main():
    # Ler o arquivo XML da rede
    netfile = '../input/cologne.net.xml'
    with open(netfile, 'r') as f:
        soup = BeautifulSoup(f.read(), 'xml')

    # Criar grafo da rede
    graph = nx.DiGraph()
    edges_length = {}
    for edge in soup.find_all('edge'):
        edge_id = edge['id']
        length = float(edge.find('lane')['length'])
        edges_length[edge_id] = length
        for connection in edge.find_all('connection'):
            graph.add_edge(edge_id, connection['to'], length=length)

    # Rodar o AG
    best_solution = genetic_algorithm(graph, NUM_STATIONS, POPULATION_SIZE, NUM_GENERATIONS)
    print("Melhores localizações de estações:", best_solution)

if __name__ == "__main__":
    main()

