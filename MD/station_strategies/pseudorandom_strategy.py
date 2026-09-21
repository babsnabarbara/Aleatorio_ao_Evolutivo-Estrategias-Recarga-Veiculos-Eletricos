"""
Approach 'pseudorandom' -- substitui
findingPseudoRandom.py::findAndSaveValidChargingPoints.

Usa a malha de quadrantes do MESMO TAMANHO que cs_amount (9quadrants.xml
para 9 estações, 16quadrants.xml para 16, ...) -- cada cs_amount usa uma
partição espacial DIFERENTE do mapa, sem relação entre si. Sem crescimento
incremental (mesmo trade-off do 'greedyvoronoi').

Seed inclui `cs_amount` na chave (StationSeedRegistry.apply(repetition,
cs_amount)) -- cada tamanho de malha sorteia do zero, de forma
independente, mas cacheada (mesma seleção reaproveitada entre
minutes/percentage diferentes de uma mesma (cs_amount, repetition)).

NÃO filtra candidatos por capacidade/comprimento de lane (o código original
tinha essa checagem via TraCI ao vivo -- removida por decisão
metodológica): a capacidade real de cada estação é calculada DEPOIS, na
hora de gerar o .add.xml (ver graph_utils.realized_capacity), adaptada à
geometria de cada lane, em vez de rejeitar posições que não caibam
max_vehicles_per_cs veículos. Isso mantém a regra simétrica entre os 5
approaches -- nenhum tem tratamento especial de capacidade na seleção.

Candidatos são restritos ao componente gigante do mapa (o `graph` recebido
já vem assim de cli.py/graph_utils.default_giant_graph) -- mesmo padrão do
algoritmo genético original, agora unificado nos 5 approaches. Como todo
par de nós dentro do componente gigante já é mutuamente alcançável por
definição, "pertence ao grafo recebido" já é suficiente -- não precisa
mais confirmar caminho entre eles com nx.has_path.

FIX: antes sorteava uma TRINCA de lanes do quadrante e exigia que as 3
pertencessem ao componente gigante, mesmo só usando a do meio como
candidato -- resquício de quando essa checagem servia pra validar um ciclo
entre as 3 (removido numa limpeza anterior). Sortear 1 lane direto por vez
é mais rápido (menos sorteios desperdiçados quando alguma das 3 falha à
toa) sem mudar qual candidato acaba sendo aceito.

FIX (2026-09-19): o componente gigante (default_giant_graph) é construído
no nível de EDGE, ignorando de qual LANE cada <connection> parte -- um edge
com 2 lanes, onde só uma delas tem conexão de saída, aparece inteiro como
"conectado", e a lane sem nenhuma conexão própria passava despercebida por
"lane[:-2] not in graph" (que só confere o edge, não a lane específica).
Isso deixou uma estação ser colocada numa lane SEM NENHUMA conexão de
saída (lane 96049309#0_0, seed 4/9cs) -- qualquer veículo que fosse
recarregar ali ficava preso para sempre, sem conseguir seguir viagem,
travando a simulação num loop infinito de "emergency stop" (2026-09-19,
pseudorandom rep4/9cs, 5 combinações). Agora, além de pertencer ao
componente gigante pelo edge, a lane candidata também precisa estar em
graph_utils.lanes_with_outgoing_connection() -- ou seja, ser ela mesma a
origem de pelo menos uma <connection> no net.xml.
"""
from __future__ import annotations

import random
import xml.etree.ElementTree as ET

import networkx as nx

import config
import graph_utils
from sim_job import SimJob
from station_strategies import evolution


def _quadrants_for(cs_amount: int) -> list:
    from quadrants_check import ensure_quadrants
    ensure_quadrants(cs_amount)  # gera as malhas sob demanda se ainda não existirem

    quadrants_file = config.LANES_IN_EACH_QUADRANT_DIR / f"{cs_amount}quadrants.xml"
    root = ET.parse(quadrants_file).getroot()
    return [
        [lane.text for lane in quadrant.findall("lane") if lane.text]
        for quadrant in root.findall(".//quadrant")
    ]


def _build(cs_amount: int, graph: nx.DiGraph) -> set:
    quadrants = _quadrants_for(cs_amount)
    connected_lanes = graph_utils.lanes_with_outgoing_connection()

    chosen: set = set()
    max_attempts_per_quadrant = 5000

    for quadrant_lanes in quadrants:
        if len(quadrant_lanes) < 1:
            raise ValueError(
                f"Quadrante sem nenhuma lane -- "
                f"impossível sortear candidato (cs_amount={cs_amount})."
            )

        found = False
        for _ in range(max_attempts_per_quadrant):
            lane = random.choice(quadrant_lanes)
            # lane[:-2] converte lane id -> edge id (remove o sufixo "_0")
            if lane[:-2] not in graph:
                continue
            if lane not in connected_lanes:
                continue  # lane sem conexão de saída própria -- veículo ficaria preso
            if lane in chosen:
                continue
            chosen.add(lane)
            found = True
            break

        if not found:
            raise RuntimeError(
                f"Não achei estação válida para um quadrante em "
                f"{max_attempts_per_quadrant} tentativas (cs_amount={cs_amount})."
            )

    return chosen


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set:
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition, job.cs_amount)

    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount)
    if cached is not None:
        return cached

    chosen = _build(job.cs_amount, graph)
    evolution.save_stage(job.approach, job.repetition, job.cs_amount, chosen)
    return chosen
