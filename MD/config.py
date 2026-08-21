"""
Configuração central do projeto.

Paths são ancorados na localização deste arquivo (não no cwd de onde o script
é chamado) — isso resolve o problema do código antigo, onde cada arquivo
assumia uma profundidade diferente ("../input", "../../input",
"../../../input") dependendo de quem o executava.

Estrutura real no disco (confirmada em TCC/):

    TCC/
    ├── input/                      -> INPUT_DIR
    ├── output/                     -> OUTPUT_DIR
    └── MD/                         -> MD_ROOT (onde este config.py mora)
"""
from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MD_ROOT = Path(__file__).resolve().parent           # .../TCC/MD
TCC_ROOT = MD_ROOT.parent                             # .../TCC

INPUT_DIR = TCC_ROOT / "input"
OUTPUT_DIR = TCC_ROOT / "output"

NET_FILE = INPUT_DIR / "cologne.net.xml"
TRIPS_FILE = INPUT_DIR / "cologne6to8.trips.xml"
ELECTRIC_VEHICLE_TYPE_FILE = INPUT_DIR / "electric_vehicle.xml"
MOST_VISITED_FILE = INPUT_DIR / "mostVisited.xml"
LANDMARK_DISTANCES_FILE = INPUT_DIR / "cologne_landmark_distances.txt"

LANES_IN_EACH_QUADRANT_DIR = INPUT_DIR / "lanesInEachQuadrant"
MOST_VISITED_LANES_IN_EACH_QUADRANT_DIR = INPUT_DIR / "mostVisitedLanesInEachQuadrant"


def genetic_result_file(cs_amount: int, seed: int) -> Path:
    """input/exhaustive_genetic<cs_amount>/resultado_final_k<cs_amount>_seed<seed>.json
    -- resultado pré-computado do algoritmo genético (rodado fora deste
    pipeline), consumido por station_strategies/genetic_strategy.py."""
    return (
        INPUT_DIR
        / f"exhaustive_genetic{cs_amount}"
        / f"resultado_final_k{cs_amount}_seed{seed}.json"
    )

# ---------------------------------------------------------------------------
# Grid do experimento
# ---------------------------------------------------------------------------
APPROACHES = ("random", "pseudorandom", "greedy", "greedyvoronoi", "genetic")

MINUTES_RECHARGING = (10, 20, 40, 60)
STATIONS_AMOUNTS = (9, 16, 25, 36, 49)
PERCENTAGES = tuple(range(5, 31, 5))     # 5, 10, 15, 20, 25, 30
REPETITIONS = tuple(range(1, 6))         # 1..5

# Seeds usadas nas rodadas pré-computadas do algoritmo genético (exhaustive
# GA, rodado fora deste pipeline). A ordem aqui define o mapeamento
# repetition -> seed: repetition 1 usa GENETIC_SEEDS[0] (42), repetition 2
# usa GENETIC_SEEDS[1] (123), e assim por diante -- só pra ter as mesmas 5
# "repetições" que os outros approaches usam, mesmo não sendo geradas por
# este código.
GENETIC_SEEDS = (42, 123, 555, 777, 2024)

# Parâmetros que hoje são fixos no seu grid mas continuam configuráveis
DEFAULT_VEHICLES = 8000
# Não é "quantos plugues tem o posto" -- é uma checagem espacial (ver
# station_strategies/pseudorandom_strategy.py): a lane escolhida precisa
# caber esse número de comprimentos de veículo. 6 representa um hub de
# recarga pública de porte médio urbano; ajuste conforme a densidade de
# rede que você está modelando (rede esparsa de hubs grandes -> valor
# maior; rede densa de pontos pequenos de bairro -> valor menor).
DEFAULT_MAX_VEHICLES_PER_CS = 6

# ---------------------------------------------------------------------------
# Parâmetros de infraestrutura do SUMO -- antes espalhados como literais
# mágicos ("20000.00", "100", "4", ...) repetidos em 5+ arquivos diferentes.
#
# CHARGING_POWER_W / CHARGE_DELAY_S / CHARGE_IN_TRANSIT foram removidos --
# eram usados só para escrever o <chargingStation> no .add.xml, e esse
# elemento foi tirado do projeto (ver io_utils.write_add_file): o objetivo
# nunca dependeu da recarga em si acontecer, só do veículo ficar parado o
# tempo certo (garantido via STOP_PARKING, não via chargingStation).
# ---------------------------------------------------------------------------

# Threads internas de rerouting por simulação SUMO (astar). Isso importa
# para o multiprocessing: se N simulações rodam em paralelo, cada uma usando
# ROUTING_THREADS threads, o total de threads competindo pelos cores é
# N * ROUTING_THREADS -- ajuste um em função do outro (ver conversa sobre
# os servidores de 48 CPUs).
ROUTING_THREADS = 4

SIM_BEGIN_TIME_S = 21600  # 6h -- início da janela 6h-8h do cenário

# ---------------------------------------------------------------------------
# Layout de pastas de output — preserva EXATAMENTE a estrutura existente,
# só adiciona o nível de "Nmin" que antes causava sobrescrita silenciosa
# entre execuções com timeOfRecharge diferente.
# ---------------------------------------------------------------------------


def experiment_folder(approach: str, minutes: int, percentage: int, cs_amount: int) -> Path:
    """
    output/<approach>/<minutes>min/<percentage>percentage<cs>cs/

    Equivalente ao antigo functions.createExperimentFolder(args), mas com o
    nível de "min" adicionado e sem side-effect (não cria a pasta — quem
    chama decide quando materializar no disco).
    """
    return (
        OUTPUT_DIR
        / approach
        / f"{minutes}min"
        / f"{percentage}percentage{cs_amount}cs"
    )


def selected_lanes_dir(folder: Path) -> Path:
    return folder / "selectedLanes"


def sorted_cars_dir(folder: Path, vehicles: int) -> Path:
    return folder / f"sortedCars-{vehicles}"


def reports_dir(folder: Path) -> Path:
    return folder / "reports"


def jobs_dir(approach: str) -> Path:
    """Onde ficam os manifestos de cada job (para reexecução manual)."""
    return OUTPUT_DIR / approach / "jobs"


def voronoi_stations_dir() -> Path:
    """output/greedyvoronoi/voronoiStations/ -- mesma pasta que já existe
    hoje, usada pelo approach greedyvoronoi para os diagramas/flags de
    diagnóstico do sorteio de regiões."""
    return OUTPUT_DIR / "greedyvoronoi" / "voronoiStations"


def station_seed_registry_file(approach: str) -> Path:
    """
    Registro de SEEDS DE ESTAÇÃO -- uma por (approach, repetition) só,
    representando "uma evolução da cidade" (não varia com cs_amount,
    percentage nem minutes). Separado do registro de seeds de trips
    (abaixo) de propósito: a posição das estações não deveria depender de
    quantos veículos recarregam nem de quanto tempo demora a recarga.
    """
    return OUTPUT_DIR / approach / "seeds_stations_registry.json"


def trip_seed_registry_file(approach: str) -> Path:
    """
    Registro de SEEDS DE SORTEIO DE TRIPS -- por (approach, percentage,
    repetition). Independente da seed de estação: qual % de veículos
    recarrega não deveria influenciar onde as estações foram colocadas, e
    vice-versa.
    """
    return OUTPUT_DIR / approach / "seeds_trips_registry.json"


def station_evolution_dir(approach: str, repetition: int) -> Path:
    """
    Onde fica a sequência incremental de estações de UMA seed (repetition)
    de UM approach -- independente de percentage/minutes, já que a partir
    de agora a posição das estações não varia com esses dois parâmetros.

        output/<approach>/stations_evolution/seed_<repetition>/<cs>stations.xml

    Cada arquivo contém a seleção COMPLETA daquele estágio (ex.
    16stations.xml tem as 16 lanes, sendo as 9 primeiras idênticas às de
    9stations.xml) -- é o que garante o requisito de "nada se move, só se
    adiciona": quem lê um estágio não precisa recalcular nada, só carregar.
    """
    return OUTPUT_DIR / approach / "stations_evolution" / f"seed_{repetition}"