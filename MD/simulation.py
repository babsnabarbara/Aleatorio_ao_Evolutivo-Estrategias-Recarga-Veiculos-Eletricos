"""
Núcleo de execução de UMA simulação SUMO/TraCI -- migrado de main.py
(funções run/decide/reroute/dict_trip/readChargingStations).

O QUE NÃO FOI MIGRADO (de propósito): as ~11 funções do main.py original
relacionadas a bateria (batteryActualValue, maximumBatteryCapacity,
isTheBatteryFull, isTheBatteryLow, hasReachedMaxTimeCharging), tripinfo
manual (createTripInfo, getTripInfo, tripInfoOutput), sortCars e
originalRoute -- nenhuma delas era chamada em lugar nenhum (todas as
chamadas restantes estavam comentadas dentro de run()). Ver
docs/ARQUITETURA.md seção 7 para o levantamento completo.

IMPORTANTE sobre o import de traci/sumolib: é feito sob demanda (dentro de
run_simulation), não no topo do módulo. Isso permite importar
simulation.py e inspecionar suas funções puras (decide_station, reroute,
read_charging_stations, read_sorted_cars) sem precisar da variável de
ambiente SUMO_HOME definida -- útil por exemplo se a fase de geração do
cli.py quiser reusar alguma dessas funções sem precisar de um SUMO
instalado na máquina que só gera arquivos.
"""
from __future__ import annotations

import datetime
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import networkx as nx

import config
import graph_utils
from sim_job import SimJob

_ATTR_RE = {
    name: re.compile(rf'{name}="([^"]*)"')
    for name in ("id", "depart", "from", "to")
}


# ---------------------------------------------------------------------------
# Leitura de arquivos já gerados (fase de geração já deve ter rodado)
# ---------------------------------------------------------------------------
def read_charging_stations(job: SimJob) -> dict:
    """Lê o .add.xml do job e devolve {station_id: {'lane': lane_id}}.

    Lê de <parkingArea>, não de <chargingStation> -- este projeto não usa
    mais chargingStation (recarga removida de propósito, ver
    io_utils.write_add_file); as posições das estações agora vêm só das
    parkingAreas, que continuam existindo no .add.xml normalmente. O nome
    da função foi mantido (mesmo assinatura/retorno) para não exigir
    mudança em quem já chama isso."""
    root = ET.parse(job.add_file).getroot()
    stations = {}
    for pa in root.findall(".//parkingArea"):
        stations[pa.get("id")] = {"lane": pa.get("lane")}
    return stations


def read_sorted_cars(job: SimJob) -> dict:
    """
    Lê sortedCars-N/sortedCarsN.xml (os veículos sorteados para recarregar)
    e devolve {trip_id: {'id', 'depart', 'from', 'to'}}.

    Parsing via regex por atributo (não split/strip por espaço) -- o
    dict_trip original usava `parte.split('=')` + `.strip('"\\'')` token a
    token, o que corrompe o último atributo sempre que não há espaço antes
    de '/>' (ex. `to="e52"/>` virava `e52"/>` em vez de `e52`, já que
    strip() só remove aspas nas PONTAS da string, e a ponta direita aqui é
    '>', não '"'). Regex extrai o valor exato entre aspas, não depende de
    onde a tag termina.
    """
    trips: dict = {}
    with open(job.sorted_cars_file, "r", encoding="utf-8") as f:
        for line in f:
            if "<trip" not in line:
                continue
            attrs = {}
            for name, pattern in _ATTR_RE.items():
                match = pattern.search(line)
                if match:
                    attrs[name] = match.group(1)
            trip_id = attrs.get("id")
            if trip_id:
                trips[trip_id] = attrs
    return trips


# ---------------------------------------------------------------------------
# Decisão de estação + roteamento
# ---------------------------------------------------------------------------
def decide_station(graph: nx.DiGraph, source: str, charging_stations: dict) -> dict:
    """
    Escolhe, entre as estações disponíveis (já com 'edge' resolvido -- ver
    _inject_electric_vehicles), a de menor distância a partir de `source`.

    A distância usada é a soma do atributo 'length' das arestas do
    caminho (comprimento real da via, em metros) -- ou seja, o Dijkstra
    minimiza distância física, não número de saltos (que seria com
    weight="weight", sempre fixo em 1 no grafo, e é o que graph_utils usa
    para outros fins, como a busca de ciclo das station strategies).

    2026-09-21: trocado de weight="weight" (contagem de saltos, do
    main.py original) para weight="length" (distância real) -- mais
    realista, já que veículos/GPS de verdade não escolhem rota pelo menor
    número de cruzamentos. Isso muda os resultados das simulações em
    relação à versão anterior (rota e/ou estação escolhida pode ser
    diferente); o grid precisa ser regerado e rerrodado pra refletir essa
    mudança.
    """
    best_path = None
    best_id = None
    best_distance = float("inf")

    for station_id, info in charging_stations.items():
        edge = info["edge"]
        try:
            path = nx.dijkstra_path(graph, source, edge, weight="length")
        except nx.NetworkXNoPath:
            continue
        distance = sum(
            graph[path[i]][path[i + 1]]["length"] for i in range(len(path) - 1)
        )
        if distance < best_distance:
            best_distance = distance
            best_path = path
            best_id = station_id

    if best_path is None:
        raise RuntimeError(
            f"Nenhuma estação alcançável a partir de '{source}' -- "
            f"{len(charging_stations)} estações testadas."
        )
    return {"path": best_path, "id": best_id}


def nearest_station_table(graph: nx.DiGraph, charging_stations: dict) -> dict:
    """
    UM Dijkstra multi-fonte por simulação, partindo de todas as estações no
    grafo invertido (mesmo cálculo da aptidão do AG). Para cada trecho v
    do grafo, guarda:
      dist[v]    -- distância (soma de 'length') de v até a estação mais próxima;
      station[v] -- id dessa estação;
      nxt[v]     -- próximo trecho no caminho de v até ela.
    Relaxar a aresta u -> v no grafo invertido é usar a aresta v -> u do
    grafo original, com o mesmo 'length' -- então dist[v] é exatamente a
    distância que decide_station calcularia de v até a estação mais próxima.

    OTIMIZAÇÃO (2026-11-18): antes, decide_station rodava um Dijkstra do
    ponto de partida até CADA estação, para CADA elétrico (k x nº de
    elétricos execuções antes da simulação começar); era o que dominava o
    tempo de máquina (k=49 levava ~6x mais que k=9 com o mesmo tempo
    simulado). Agora é uma execução por simulação. A estação escolhida é a
    mesma, exceto em empate exato de distância (aí pode ser outra estação
    à mesma distância).
    """
    import heapq

    dist: dict = {}
    station: dict = {}
    nxt: dict = {}
    heap = []
    for order, (station_id, info) in enumerate(charging_stations.items()):
        edge = info["edge"]
        if edge not in graph or edge in station:
            continue
        dist[edge], station[edge], nxt[edge] = 0.0, station_id, None
        heapq.heappush(heap, (0.0, order, edge))

    done = set()
    counter = len(charging_stations)
    while heap:
        d, _, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        for v in graph.predecessors(u):       # aresta v -> u no grafo original
            nd = d + graph[v][u]["length"]
            if nd < dist.get(v, float("inf")):
                dist[v], station[v], nxt[v] = nd, station[u], u
                counter += 1
                heapq.heappush(heap, (nd, counter, v))
    return {"dist": dist, "station": station, "nxt": nxt}


def _ate_n_ruas_antes(graph: nx.DiGraph, trecho: str, n: int) -> set:
    """Trechos de onde se chega a `trecho` em até n passos (sem ele mesmo)."""
    vistos, fronteira = set(), {trecho}
    for _ in range(n):
        fronteira = {p for f in fronteira for p in graph.predecessors(f)} - vistos - {trecho}
        vistos |= fronteira
    return vistos


def decide_station_from_table(table: dict, source: str) -> dict:
    """Mesmo retorno de decide_station ({"path": [...], "id": ...}), lido
    da tabela de nearest_station_table em vez de rodar k Dijkstras."""
    if source not in table["station"]:
        raise RuntimeError(f"Nenhuma estação alcançável a partir de '{source}'.")
    path = [source]
    while table["nxt"][path[-1]] is not None:
        path.append(table["nxt"][path[-1]])
    return {"path": path, "id": table["station"][source]}


def reroute(graph: nx.DiGraph, source: str, target: str) -> list:
    """Caminho de `source` até `target` (por distância real, ver
    docstring de decide_station), sem o próprio `source` (já ocupado
    pela ponta do trecho anterior da rota)."""
    route = nx.dijkstra_path(graph, source, target, weight="length")
    return route[1:] if route else route


# ---------------------------------------------------------------------------
# Injeção dos veículos elétricos via TraCI
# ---------------------------------------------------------------------------
# estação -> trechos de saída, preenchido por _inject_electric_vehicles
SAIDA_ESTACOES: dict = {}


def _inject_electric_vehicles(job: SimJob, graph: nx.DiGraph) -> dict:
    import traci  # import tardio -- ver docstring do módulo
    ev_station_edge = {}
    charging_stations = read_charging_stations(job)
    if not charging_stations:
        return ev_station_edge# cenário sem estações (cs_amount=0) -- nada a injetar

    for info in charging_stations.values():
        info["edge"] = traci.lane.getEdgeID(info["lane"])

    table = nearest_station_table(graph, charging_stations)
    cars = read_sorted_cars(job)
    duration_s = job.minutes * 60.0  # float, não string -- versões recentes do
    # TraCI empacotam 'duration' diretamente como double (struct.pack "...d...");
    # passar string aqui (como o main.py original fazia) quebra com
    # "struct.error: required argument is not a float" nessas versões.

    for car_id, attrs in cars.items():
        source = attrs["from"]
        destination = attrs["to"]
        depart = attrs["depart"]

        decision = decide_station_from_table(table, source)
        first_path = decision["path"]
        stop_spot = decision["id"]
        charging_edge = first_path[-1]
        second_path = reroute(graph, charging_edge, destination)
        whole_route = first_path + second_path

        traci.route.add(car_id, whole_route)
        traci.vehicle.add(car_id, typeID="soulEV65", depart=depart, routeID=car_id)
        # setParkingAreaStop (não setChargingStationStop) -- a parkingArea
        # (mesmo id, mesma lane, ver io_utils.write_add_file) é quem impõe
        # o limite real de capacidade via roadsideCapacity. Se a
        # parkingArea já estiver cheia quando esse veículo chegar, o
        # próprio SUMO faz ele esperar na via (fila), sem código nosso.
        # STOP_PARKING (flags=1): continua igual -- o carro sai da via de
        # verdade pra ocupar a vaga (não é opcional pra parkingArea,
        # inclusive: parar numa parkingArea sem STOP_PARKING não faz
        # sentido fisicamente).
        traci.vehicle.setParkingAreaStop(car_id, stop_spot, duration=duration_s, flags=1)
        ev_station_edge[car_id] = charging_edge
        # trechos por onde este elétrico sai da estação (ver
        # StuckMonitor._local_de_espera): a fila de NENHUMA estação pode
        # ficar parada neles
        SAIDA_ESTACOES.setdefault(charging_edge, set()).update(second_path[:2])
    return ev_station_edge
# ---------------------------------------------------------------------------
# Execução completa de um job
# ---------------------------------------------------------------------------
def _ensure_traci_importable() -> None:
    if "SUMO_HOME" not in os.environ:
        raise RuntimeError(
            "Variável de ambiente SUMO_HOME não definida -- necessária para "
            "rodar uma simulação (não para gerar arquivos)."
        )
    tools = os.path.join(os.environ["SUMO_HOME"], "tools")
    if tools not in sys.path:
        sys.path.append(tools)


def _write_report(job: SimJob, start: datetime.datetime,
                   end: datetime.datetime, error: str | None,
                   extra_lines: list | None = None) -> None:
    """Grava o relatório de texto da simulação. `extra_lines` são linhas
    opcionais acrescentadas ao final -- hoje, as contagens do stuck_monitor
    (ver stuck_monitor.StuckMonitor.resumo)."""
    lines = [
        f"PORCENTAGEM DE VEÍCULOS: {job.percentage}",
        f"NÚMERO DE ESTAÇÕES DE RECARGA: {job.cs_amount}",
        # FIX: no relatório original esse dado só existia no NOME do
        # arquivo (REPORT-Nfile-Ttime-...), nunca no conteúdo -- não dava
        # pra saber o tempo de recarga sem parsear o próprio filename.
        f"TEMPO DE RECARGA (min): {job.minutes}",
        f"SIMULAÇÃO (repetição): {job.repetition}",
        f"SEED: {job.seed}",
        "INÍCIO DA SIMULAÇÃO",
        f"hora: {start.strftime('%H:%M:%S')}",
        f"data: {start.strftime('%d/%m/%Y')}",
    ]
    if error is None:
        lines += [
            "FIM DA SIMULAÇÃO",
            f"hora: {end.strftime('%H:%M:%S')}",
            f"data: {end.strftime('%d/%m/%Y')}",
        ]
    else:
        lines += [
            "SIMULAÇÃO FALHOU",
            f"hora: {end.strftime('%H:%M:%S')}",
            f"data: {end.strftime('%d/%m/%Y')}",
            f"erro: {error}",
        ]
    lines += list(extra_lines or [])
    job.report_file.parent.mkdir(parents=True, exist_ok=True)
    job.report_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

# ---------------------------------------------------------------------------
# Detector de impasse (19/11): o timeout de config.DEFAULT_MAX_SIMULATION_HOURS
# mede tempo de RELÓGIO (30 h) -- um job travado gastava até 30 h x 4
# tentativas do batch antes de ser dado como falho. Este detector mede tempo
# SIMULADO sem nenhum progresso (nenhuma partida, chegada, início ou fim de
# estacionamento) e aborta em minutos de relógio, gravando o estado dos
# elétricos em <REPORT>.impasse.txt. Só observa: não muda regra nenhuma.
# Com recarga de até 60 min, toda estação ocupada gera pelo menos um fim de
# estacionamento a cada 60 min simulados, então 2 h sem nada = travado.
# ---------------------------------------------------------------------------
LIMITE_SEM_PROGRESSO_S = 7200


class ImpasseError(RuntimeError):
    pass


def _dump_impasse(job: SimJob, ev_station_edge: dict, monitor, agora: float) -> None:
    from collections import Counter
    import traci  # import tardio -- ver docstring do módulo

    def seg(fn, *a):
        try:
            return fn(*a)
        except Exception as e:  # um veículo pode ter saído entre uma chamada e outra
            return f"erro:{e}"

    linhas = [f"t={agora:.0f} veiculos_na_rede={traci.vehicle.getIDCount()}"]
    if monitor is not None:
        linhas += monitor.resumo()
        for est in sorted(set(ev_station_edge.values())):
            linhas.append(
                f"ESTACAO {est} estacionados={monitor.estacionados[est]} "
                f"em_espera={sum(1 for v in monitor.em_espera if ev_station_edge.get(v) == est)} "
                f"autorizados={sum(1 for v in monitor.autorizados if ev_station_edge.get(v) == est)}")
    estados = Counter()
    evs = []
    for v in traci.vehicle.getIDList():
        if v not in ev_station_edge:
            continue
        m = monitor
        st = (f"esp={bool(m and v in m.em_espera)} aut={bool(m and v in m.autorizados)} "
              f"rec={bool(m and v in m.recarregados)} "
              f"parado={seg(traci.vehicle.isStopped, v)} "
              f"park={seg(traci.vehicle.isStoppedParking, v)}")
        estados[st] += 1
        evs.append(
            f"EV {v} est={ev_station_edge[v]} {st} road={seg(traci.vehicle.getRoadID, v)} "
            f"lane={seg(traci.vehicle.getLaneID, v)} pos={seg(traci.vehicle.getLanePosition, v)} "
            f"vel={seg(traci.vehicle.getSpeed, v)} espera_s={seg(traci.vehicle.getWaitingTime, v)} "
            f"lider={seg(traci.vehicle.getLeader, v, 100.0)} "
            f"paradas={str(seg(traci.vehicle.getNextStops, v))[:200]}")
    linhas.append("RESUMO_ESTADOS")
    linhas += [f"  {n:4d}  {st}" for st, n in estados.most_common()]
    linhas += evs
    destino = job.report_file.with_name(job.report_file.name + ".impasse.txt")
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def run_simulation(job: SimJob, graph: nx.DiGraph = None, sumo_command: str = "sumo",
                    max_hours: float | None = None) -> None:
    """
    Executa UMA simulação completa: conecta ao SUMO via TraCI, injeta as
    rotas dos veículos elétricos (estação + rota decididas pelo grafo),
    roda até o fim, e sempre fecha a conexão (mesmo em erro).

    Pressupõe que a fase de geração já rodou (job.is_generated() é True) --
    esta função não gera nada, só consome os arquivos já existentes.

    FIX importante em relação ao main.py original: lá, um
    traci.exceptions.FatalTraCIError era capturado com um simples
    `print(f"Erro: {e}")` e a função devolvia 0 mesmo assim -- ou seja, uma
    simulação que travou no meio era tratada como SUCESSO por quem chamava
    (o relatório era escrito como "FIM DA SIMULAÇÃO" normalmente). Aqui a
    exceção é logada no relatório E relançada -- é o que permite ao
    orquestrador (cli.py) saber que ESTE job específico falhou e precisa
    ser reexecutado, em vez de marcá-lo como concluído silenciosamente
    (o problema que motivou o pedido de reexecução manual determinística).

    Porta TraCI: se job.port for None (padrão), o TraCI escolhe uma porta
    livre automaticamente por processo -- suficiente para evitar conflito
    entre simulações rodando em paralelo (ProcessPoolExecutor) sem precisar
    de nenhuma coordenação manual de portas.

    `max_hours`: FIX -- timeout de segurança (ver config.py::
    DEFAULT_MAX_SIMULATION_HOURS). Achado real (investigação set/2026): um
    job pode ficar com um veículo genuinamente incapaz de se mover (bug de
    roteamento numa lane específica -- rota topologicamente "válida" no
    grafo abstrato usado aqui, mas que o SUMO recusa em tempo de
    simulação), o que mantém getMinExpectedNumber() > 0 para sempre e o
    loop abaixo nunca termina sozinho -- só descoberto antes via
    `ps`/`top` mostrando um processo `sumo` com DIAS de CPU acumulado,
    resolvido manualmente com `kill -9`. Preferimos `time.monotonic()` a
    `datetime.now()` aqui porque não é afetado por ajuste de relógio do
    sistema durante uma execução de horas.
    """
    if not job.is_generated():
        raise RuntimeError(
            f"Job {job.manifest_id} não tem todos os arquivos gerados "
            f"(.cfg/.add/.trips/selectedLanes/sortedCars) -- rode a fase "
            f"de geração antes de simular."
        )

    _ensure_traci_importable()
    import traci
    from sumolib import checkBinary

    graph = graph if graph is not None else graph_utils.default_graph()
    sumo_binary = checkBinary(sumo_command)
    sumo_cmd = [
        sumo_binary,
        "-c", str(job.cfg_file),
        "--log", str(job.log_file),
        "--tripinfo-output", str(job.tripinfo_output_file),
        # Uma linha por parada (início, fim, parkingArea): separa a recarga
        # (parada na parkingArea) da espera na fila (parada comum dada pelo
        # stuck_monitor). Sem isso, o stopTime do tripinfo soma as duas, e a
        # espera na fila pareceria tempo de recarga.
        "--stop-output", str(job.tripinfo_output_file.with_name(
            job.tripinfo_output_file.name.replace("simulation", "stops"))),
        # FIX: --battery-output removido. Esse arquivo não é lido por
        # NENHUMA parte do pipeline (verify_recharge.py usa o tripinfo,
        # não o battery-output) -- e, no requisito real deste projeto, a
        # recarga em si não precisa acontecer, só a parada precisa durar
        # o tempo certo (já validado via tripinfo/stopTime). Uma única
        # simulação de 200 veículos já gerava ~470MB nesse arquivo; no
        # grid completo (120 combinações x 5 repetições) isso estourou o
        # disco no meio de uma rodada real ("No space left on device").
        # Removendo, cada simulação passa a gravar só o tripinfo (poucos
        # KB/MB), que é tudo que o pipeline realmente usa.
    ]

    max_hours = max_hours if max_hours is not None else config.DEFAULT_MAX_SIMULATION_HOURS
    max_seconds = max_hours * 3600.0

    start_time = datetime.datetime.now()
    started = False
    monitor = None
    try:
        traci.start(sumo_cmd, port=job.port)
        started = True

        SAIDA_ESTACOES.clear()
        ev_station_edge = _inject_electric_vehicles(job, graph)
        if config.USE_STUCK_MONITOR:
            from stuck_monitor import StuckMonitor
            monitor = StuckMonitor(
                traci, ev_station_edge,
                intervalo_s=config.STUCK_CHECK_INTERVAL_S,
                limite_s=config.STUCK_LIMIT_S,
                mapa_faixas=graph_utils.edge_to_lanes,
                # fila na rua da estação, parando antes das vagas
                # (ver StuckMonitor._controlar_fila)
                capacidade=job.max_vehicles_per_cs if config.QUEUE_BEFORE_STATION else None,
                # trechos até 5 ruas antes da estação: o elétrico recebe a
                # parada de espera cedo, antes de chegar perto dela
                aproximacao={s: sorted(_ate_n_ruas_antes(graph, s, 5))
                             for s in set(ev_station_edge.values()) if s in graph},
                faixa_estacao={traci.lane.getEdgeID(info["lane"]): info["lane"]
                               for info in read_charging_stations(job).values()},
                folga_saida_m=config.PARKING_ZONE_HALF_M + config.QUEUE_GAP_M,
                saida_estacoes=SAIDA_ESTACOES,
                meia_zona_m=config.PARKING_ZONE_HALF_M,
            )

        
        loop_start = time.monotonic()
        ultimo_progresso = None
        while traci.simulation.getMinExpectedNumber() > 0:
            elapsed = time.monotonic() - loop_start
            if elapsed > max_seconds:
                raise TimeoutError(
                    f"Simulação excedeu {max_hours}h sem terminar (rodou "
                    f"{elapsed / 3600:.1f}h) -- provavelmente um veículo "
                    f"genuinamente preso (ver log do job), não lentidão "
                    f"normal. Abortando pra permitir retry/investigação em "
                    f"vez de rodar indefinidamente."
                )
            traci.simulationStep()
            if monitor is not None:
                monitor.apos_passo()
            agora = traci.simulation.getTime()
            if (ultimo_progresso is None
                    or traci.simulation.getArrivedNumber()
                    or traci.simulation.getDepartedNumber()
                    or traci.simulation.getParkingStartingVehiclesIDList()
                    or traci.simulation.getParkingEndingVehiclesIDList()):
                ultimo_progresso = agora
            elif agora - ultimo_progresso > LIMITE_SEM_PROGRESSO_S:
                try:
                    _dump_impasse(job, ev_station_edge, monitor, agora)
                except Exception as dump_exc:
                    print(f"falha ao gravar o diagnóstico de impasse: {dump_exc}")
                raise ImpasseError(
                    f"Impasse: nenhuma partida, chegada nem estacionamento há "
                    f"{LIMITE_SEM_PROGRESSO_S} s simulados (t={agora:.0f}); "
                    f"ver {job.report_file.name}.impasse.txt"
                )
    except Exception as exc:  # inclui traci.exceptions.FatalTraCIError e o TimeoutError acima
        _write_report(job, start_time, datetime.datetime.now(), error=str(exc),
                      extra_lines=monitor.resumo() if monitor else None)
        raise
    else:
        _write_report(job, start_time, datetime.datetime.now(), error=None,
                      extra_lines=monitor.resumo() if monitor else None)
    finally:
        if started:
            try:
                traci.close()
            except Exception:
                pass  # conexão já pode ter caído por causa do próprio erro
