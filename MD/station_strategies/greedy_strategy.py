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

FIX: fallback geométrico para quadrantes sem nenhuma lane visitada
elegível. Antes, esses quadrantes ficavam permanentemente sem estação
(comportamento documentado e aceito inicialmente -- mesma decisão tomada
em greedy_voronoi_strategy.py). Agora, cada quadrante que sobra vazio
depois da fase por visitação recebe a lane GEOGRAFICAMENTE MAIS CENTRAL
dele: entre as lanes que pertencem aquele quadrante (mesma lista de
_quadrants_lanes, não só as visitadas) e que passam pela checagem de
componente gigante, escolhe a mais próxima do centro geométrico exato do
quadrante -- centro calculado com a MESMA fórmula que quadrants.py usa pra
decidir a quem cada lane pertence (x_min + (x+0.5)*tamanho_quadrant_x, idem
em y), não uma noção nova de "central". Um quadrante só continua sem
estação se não tiver NENHUMA lane elegível (nem visitada, nem qualquer
outra) -- caso bem mais raro que antes.

As funções de coordenada (_conv_boundary/_lanes_and_coordinates) são
intencionalmente duplicadas de greedy_voronoi_strategy.py (que já precisava
da mesma informação pro diagrama de Voronoi) em vez de compartilhadas via
um módulo comum -- evita import circular (greedy_voronoi_strategy já
importa de greedy_strategy) e mantém essa mudança contida neste arquivo.
Se um dia mais approaches precisarem da mesma coisa, vale extrair pra
graph_utils.py.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from functools import lru_cache

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


@lru_cache(maxsize=1)
def _conv_boundary() -> tuple[float, float, float, float]:
    """Duplicado de greedy_voronoi_strategy.py::_conv_boundary -- ver
    docstring do módulo (evita import circular entre as duas estratégias)."""
    root = ET.parse(config.NET_FILE).getroot()
    conv_boundary = root.find(".//location").attrib["convBoundary"]
    x_min, y_min, x_max, y_max = map(float, conv_boundary.split(","))
    return x_min, y_min, x_max, y_max


@lru_cache(maxsize=1)
def _lanes_and_coordinates() -> dict[str, list[tuple[float, float]]]:
    """Duplicado de greedy_voronoi_strategy.py::_lanes_and_coordinates --
    ver docstring do módulo (evita import circular entre as duas
    estratégias)."""
    root = ET.parse(config.NET_FILE).getroot()
    lanes: dict[str, list[tuple[float, float]]] = {}
    for edge in root.findall(".//edge[@type]"):
        for lane in edge.findall("./lane"):
            coords_raw = lane.attrib["shape"].split(" ")
            points = []
            for pair in coords_raw:
                if not pair.strip():
                    continue
                x_str, y_str = pair.split(",")
                points.append((float(x_str), float(y_str)))
            lanes[lane.attrib["id"]] = points
    return lanes


def _quadrant_centroid(x_idx: int, y_idx: int, cs_amount: int) -> tuple[float, float]:
    """Centro geométrico exato do quadrante (x_idx, y_idx), usando a MESMA
    divisão de grade que quadrants.py::dividir_em_quadrants usa pra decidir
    a quem cada lane pertence -- não introduz uma noção nova de 'central'."""
    x_min, y_min, x_max, y_max = _conv_boundary()
    quadrant_raiz = int(math.sqrt(cs_amount))
    tamanho_x = (x_max - x_min) / quadrant_raiz
    tamanho_y = (y_max - y_min) / quadrant_raiz
    return (
        x_min + (x_idx + 0.5) * tamanho_x,
        y_min + (y_idx + 0.5) * tamanho_y,
    )


def _lane_centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Ponto representativo de uma lane -- média dos pontos do seu shape."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set[str]:
    """
    Para cada lane mais visitada (na ordem de mostVisited.xml, decrescente),
    associa à primeira quadrante ainda vazia que a contém E cujo edge
    pertença ao componente gigante do mapa.

    FALLBACK: quadrantes que sobram vazios depois dessa fase (nenhuma lane
    visitada elegível caiu neles) recebem a lane geograficamente mais
    central do próprio quadrante -- ver docstring do módulo. Só continua
    sem estação um quadrante sem NENHUMA lane elegível (visitada ou não),
    caso bem mais raro que antes.

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

    # Fallback: quadrantes que sobraram vazios recebem a lane geograficamente
    # mais central deles -- ver docstring do módulo. lanes_and_coords só é
    # carregado sob demanda (nenhum custo extra quando não há quadrante
    # vazio, caso comum quando cs_amount é pequeno).
    lanes_and_coords: dict[str, list[tuple[float, float]]] | None = None
    for idx, (x_str, y_str, lanes) in enumerate(quadrants):
        if quadrant_filled[idx]:
            continue

        if lanes_and_coords is None:
            lanes_and_coords = _lanes_and_coordinates()

        centroid = _quadrant_centroid(int(x_str), int(y_str), job.cs_amount)
        best_lane = None
        best_distance = float("inf")
        for lane_id in lanes:
            if lane_id in chosen:
                continue
            if lane_id[:-2] not in graph:
                continue
            coords = lanes_and_coords.get(lane_id)
            if not coords:
                continue
            distance = math.dist(_lane_centroid(coords), centroid)
            if distance < best_distance:
                best_distance = distance
                best_lane = lane_id

        if best_lane is not None:
            quadrant_filled[idx] = True
            chosen.add(best_lane)

    evolution.save_stage(job.approach, job.repetition, job.cs_amount, chosen)
    return chosen
