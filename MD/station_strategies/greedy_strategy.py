"""
Approach 'greedy' -- substitui findingStationsGreedy.py::findCSInQuadrants.

Estratégia determinística: lê as lanes mais visitadas (input/mostVisited.xml)
e ordena por contagem de visitas decrescente (não confia na ordem do
arquivo -- ver _most_visited_lanes) e, para cada uma, associa à primeira
quadrante ainda vazia que a contenha, até preencher todas as `cs_amount`
quadrantes.

FIX: agora também exige que a lane pertença ao componente gigante do mapa
(o `graph` recebido já vem restrito a esse componente -- ver
cli.py/graph_utils.default_giant_graph). Antes, este approach não conferia
conectividade de forma alguma -- diferente dos outros 4, que (com graus
variados de rigor) já tinham algum tipo de checagem. Unificado agora: uma
lane mais visitada que esteja isolada/fora do núcleo bem conectado do mapa
é ignorada, como as outras 4 estratégias já fazem.

Não usa sorteio nenhum -- por isso, ao contrário dos outros approaches, as
5 repetições de 'greedy' para uma mesma (cs, percentage) são sempre
idênticas entre si (não há fonte de aleatoriedade na escolha da estação em
si; a única variação entre repetições vem do sorteio de trips, que
continua usando a seed do job normalmente).

FIX: agora usa o mesmo cache em disco que random/pseudorandom/greedyvoronoi
(station_strategies/evolution.py) -- antes recalculava do zero em TODA
chamada, mesmo sendo sempre o mesmo resultado para um dado cs_amount (até
600 vezes redundantes ao longo de um grid completo). Como 'greedy' não usa
seed nenhuma, o cache aqui é só por (approach, repetition, cs_amount) --
sem StationSeedRegistry envolvida.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import networkx as nx

import config
from sim_job import SimJob
from station_strategies import evolution


def _most_visited_lanes() -> dict[str, int]:
    """
    Lê input/mostVisited.xml e devolve {lane_id: count}, JÁ ORDENADO por
    count decrescente (mais visitada primeiro).

    FIX: o código original (e a primeira versão desta função) confiava que
    o arquivo já vinha pré-ordenado do processo que gerou as contagens, e
    só percorria na ordem em que as lanes apareciam nele -- sem nenhuma
    ordenação explícita por `count`. Isso é frágil: se o arquivo um dia for
    regenerado numa ordem diferente (ou não for gerado ordenado pra
    começar), o approach 'greedy' silenciosamente deixa de ser "greedy" de
    verdade (vira só "primeira lane do arquivo", sem relação com
    visitação), sem erro nenhum avisando. Ordenar aqui explicitamente
    elimina essa dependência da ordem do arquivo -- não muda nada se o
    arquivo já estiver ordenado, corrige se não estiver.
    """
    root = ET.parse(config.MOST_VISITED_FILE).getroot()
    lanes: dict[str, int] = {}
    for lane_elem in root.findall(".//lane"):
        lane_id = lane_elem.get("id")
        count = lane_elem.get("count")
        if lane_id is not None:
            lanes[lane_id] = int(count) if count is not None else 0
    return dict(sorted(lanes.items(), key=lambda item: item[1], reverse=True))


def _quadrants_lanes(cs_amount: int) -> list[tuple[str, str, list[str]]]:
    """Devolve [(x, y, [lane_ids...]), ...] preservando a ordem do arquivo."""
    from quadrants_check import ensure_quadrants
    ensure_quadrants(cs_amount)  # gera as malhas sob demanda se ainda não existirem

    quadrants_file = config.LANES_IN_EACH_QUADRANT_DIR / f"{cs_amount}quadrants.xml"
    root = ET.parse(quadrants_file).getroot()
    result = []
    for quadrant in root.findall(".//quadrant"):
        lanes = [lane.text for lane in quadrant.findall("lane") if lane.text]
        result.append((quadrant.get("x"), quadrant.get("y"), lanes))
    return result


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set[str]:
    """
    Para cada lane mais visitada (na ordem de mostVisited.xml, decrescente),
    associa à primeira quadrante ainda vazia que a contém E cujo edge
    pertença ao componente gigante do mapa. Um quadrante sem NENHUMA lane
    visitada elegível simplesmente fica sem estação -- não é erro, é
    esperado. O resultado pode ter menos de `cs_amount` estações nesse
    caso.

    NÃO filtra por capacidade/comprimento de lane -- a capacidade real de
    cada estação é calculada depois, na hora de gerar o .add.xml (ver
    graph_utils.realized_capacity).
    """
    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount)
    if cached is not None:
        return cached

    quadrants = _quadrants_lanes(job.cs_amount)
    most_visited = _most_visited_lanes()  # já ordenado por count decrescente

    quadrant_filled = [False] * len(quadrants)
    chosen: set[str] = set()

    for lane_id in most_visited:
        if len(chosen) >= len(quadrants):
            break
        if lane_id in chosen:
            continue
        # lane_id[:-2] converte lane id -> edge id (remove o sufixo "_0")
        if lane_id[:-2] not in graph:
            continue

        for idx, (_x, _y, lanes) in enumerate(quadrants):
            if quadrant_filled[idx]:
                continue
            if lane_id in lanes:
                quadrant_filled[idx] = True
                chosen.add(lane_id)
                break

    evolution.save_stage(job.approach, job.repetition, job.cs_amount, chosen)
    return chosen