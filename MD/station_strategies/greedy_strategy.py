"""
Approach 'greedy' -- substitui findingStationsGreedy.py::findCSInQuadrants.

ATUALIZAÇÃO (2026-11-18): a descrição abaixo é da versão antiga
(determinística, por faixa). A versão atual sorteia, em cada quadrante, um
TRECHO entre os 100 mais visitados (visitas somadas por trecho em
most_visited_edges.py) e converte em faixa com graph_utils.lane_for_edge --
ver _build e select_charging_points.

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

FIX (2026-09-19): tanto o loop principal (lanes mais visitadas) quanto o
fallback geométrico só conferiam "lane_id[:-2] not in graph" -- isto é, se
o EDGE da lane pertence ao componente gigante -- sem nunca checar se a
LANE especificamente escolhida tem alguma <connection> de saída própria.
Isso é o mesmo bug já corrigido em graph_utils.py/pseudorandom_strategy.py:
um edge com 2+ lanes pode estar bem conectado ao resto do mapa via UMA
lane, enquanto outra lane do mesmo edge não tem nenhuma conexão de saída
-- uma estação posicionada ali prende pra sempre qualquer veículo que for
recarregar. O fallback geométrico era o ponto mais exposto: ele considera
TODAS as lanes do quadrante (não só as visitadas), então tinha mais chance
de cair numa lane sem saída -- inclusive podendo escolher uma lane
"perfeitamente central" (distância 0 do centroide) só pra descobrir, na
simulação, que ela é um beco sem saída. Agora as duas checagens também
exigem lane_id in graph_utils.lanes_with_outgoing_connection() -- mesmo
filtro adicional usado no pseudorandom, sem mudar o critério de "mais
central" em si, só reduzindo o pool de candidatas elegíveis.

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
import random
import xml.etree.ElementTree as ET
from functools import lru_cache

import networkx as nx

import config
import graph_utils
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


def _build(cs_amount: int, graph: nx.DiGraph) -> tuple[set[str], list[dict]]:
    """
    Para cada quadrante:
      1. trechos do quadrante = trechos de alguma faixa listada nele, que
         sejam candidatos (graph_utils.candidate_edges) e ainda não tenham
         estação;
      2. sorteia, com chance igual, um entre os TOP_VISITED_PER_REGION
         trechos mais visitados do quadrante (visitas somadas por trecho,
         most_visited_edges.load());
      3. se nenhum trecho do quadrante tem visita, usa o trecho mais
         próximo do centro do quadrante (fallback geométrico);
      4. a estação vai na faixa dada por graph_utils.lane_for_edge (mesma
         regra das outras abordagens).
    Devolve (faixas escolhidas, origem de cada estação) -- a origem é
    gravada em <k>stations_origem.csv (evolution.save_origins).
    """
    import most_visited_edges

    quadrants = _quadrants_lanes(cs_amount)
    visits = most_visited_edges.load()
    candidates = set(graph_utils.candidate_edges(graph))
    shapes = graph_utils.lane_shapes()

    chosen_edges: set[str] = set()
    chosen: set[str] = set()
    origins: list[dict] = []
    for x_str, y_str, lanes in quadrants:
        edges = ({most_visited_edges.edge_of(l) for l in lanes} & candidates) - chosen_edges
        if not edges:
            raise RuntimeError(
                f"greedy: quadrante ({x_str}, {y_str}) sem nenhum trecho "
                f"candidato (cs_amount={cs_amount})."
            )
        visited = most_visited_edges.top_visited(edges, visits, len(edges))
        top = visited[:config.TOP_VISITED_PER_REGION]
        row = {"quadrante_ou_regiao": f"quadrante ({x_str},{y_str})",
               "trechos_visitados_na_regiao": len(visited)}
        if top:
            edge = random.choice(top)
            row.update(origem="visitacao", tamanho_do_sorteio=len(top))
        else:
            centro = _quadrant_centroid(int(x_str), int(y_str), cs_amount)
            dist = lambda e: math.dist(
                _lane_centroid(shapes[graph_utils.lane_for_edge(e)]), centro)
            edge = min(sorted(edges), key=dist)
            row.update(origem="fallback", distancia_ao_centro_m=round(dist(edge)))
        lane = graph_utils.lane_for_edge(edge)
        chosen_edges.add(edge)
        chosen.add(lane)
        row.update(trecho=edge, faixa=lane, visitas_do_trecho=visits.get(edge, 0))
        origins.append(row)
    return chosen, origins


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set[str]:
    """
    MUDANÇA (2026-11-18): o greedy deixou de ser determinístico. Em vez da
    FAIXA mais visitada de cada quadrante, sorteia um TRECHO entre os
    TOP_VISITED_PER_REGION (100) trechos mais visitados do quadrante -- ver
    _build. Por isso agora usa seed de estação por (repetition, cs_amount),
    igual a random/pseudorandom/greedyvoronoi.

    NÃO filtra por capacidade/comprimento de lane -- a capacidade real de
    cada estação é calculada depois, na hora de gerar o .add.xml.
    """
    from seed_registry import StationSeedRegistry
    StationSeedRegistry(job.approach).apply(job.repetition, job.cs_amount)

    cached = evolution.load_stage(job.approach, job.repetition, job.cs_amount)
    if cached is not None:
        return cached

    chosen, origins = _build(job.cs_amount, graph)
    evolution.save_stage(job.approach, job.repetition, job.cs_amount, chosen)
    evolution.save_origins(job.approach, job.repetition, job.cs_amount, origins)
    return chosen