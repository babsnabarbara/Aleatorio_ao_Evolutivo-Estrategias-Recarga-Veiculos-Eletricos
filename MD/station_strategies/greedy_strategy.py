"""
Approach 'greedy' -- substitui findingStationsGreedy.py::findCSInQuadrants.

Estratégia determinística: lê as lanes mais visitadas (input/mostVisited.xml)
e ordena por contagem de visitas decrescente (não confia na ordem do
arquivo -- ver _most_visited_lanes) e, para cada uma, associa à primeira
quadrante ainda vazia que a contenha, até preencher todas as `cs_amount`
quadrantes.

Não usa `graph` (não há validação de ciclo aqui no original) nem sorteio
algum -- por isso, ao contrário dos outros 3 approaches, as 5 repetições de
'greedy' para uma mesma (cs, percentage) são sempre idênticas entre si (não
há fonte de aleatoriedade na escolha da estação em si; a única variação
entre repetições vem do sorteio de trips, que continua usando a seed do
job normalmente).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import networkx as nx

import config
from sim_job import SimJob


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
    associa à primeira quadrante ainda vazia que a contém. Um quadrante sem
    NENHUMA lane visitada simplesmente fica sem estação -- não é erro, é
    esperado (região pouco/nada percorrida na simulação usada pra gerar as
    contagens). O resultado pode ter menos de `cs_amount` estações nesse
    caso.
    """
    quadrants = _quadrants_lanes(job.cs_amount)
    most_visited = _most_visited_lanes()  # já ordenado por count decrescente

    quadrant_filled = [False] * len(quadrants)
    chosen: set[str] = set()

    for lane_id in most_visited:
        if len(chosen) >= len(quadrants):
            break
        if lane_id in chosen:
            continue

        for idx, (_x, _y, lanes) in enumerate(quadrants):
            if quadrant_filled[idx]:
                continue
            if lane_id in lanes:
                quadrant_filled[idx] = True
                chosen.add(lane_id)
                break

    return chosen
