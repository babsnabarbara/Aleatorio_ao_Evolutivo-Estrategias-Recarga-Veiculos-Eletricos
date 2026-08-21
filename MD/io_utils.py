"""
Leitura/escrita dos arquivos que o SUMO consome ou que alimentam o pipeline
de geração: .sumo.cfg, .add.xml, seleção de lanes (selectedLanes/*.xml) e
sorteio de trips por percentual.

Substitui, numa única versão, o que antes existia (quase idêntico, com
pequenas divergências de path/bug entre as cópias) em: functions.py,
findingPseudoRandom.py, findingRandom.py, generatingGreedy.py,
generatingPseudoRandom.py, generatingWithRegions.py.

Convenção: toda função aqui recebe um SimJob e deriva os paths dele
(sim_job.py) -- nada de string concatenada na mão, o que era a causa raiz
dos bugs de "../input" vs "../../input" vs "../../../input" e dos
"cologneNone.sumo.cfg" que apareceram no seu output.zip.
"""
from __future__ import annotations

import random
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from pathlib import Path
from typing import Iterable

import config
import graph_utils
from sim_job import SimJob


def _pretty_write(root: ET.Element, path: Path) -> None:
    """Serializa um Element com indentação legível, escrita atômica."""
    raw = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(raw).toprettyxml(indent="    ", encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_bytes(pretty)
    tmp_path.replace(path)


# ---------------------------------------------------------------------------
# Seleção de estações (selectedLanes/Nchargingstations.xml)
# ---------------------------------------------------------------------------
def write_selected_lanes_file(job: SimJob, lanes: Iterable[str]) -> None:
    """
    Grava a escolha de estações desta repetição. Formato preservado do
    functions.createSelectedCSFiles original: <cs><lane>id</lane>...</cs>.
    """
    write_selected_lanes_file_to(job.selected_lanes_file, lanes)


def write_selected_lanes_file_to(path: Path, lanes: Iterable[str]) -> None:
    """Mesma coisa que write_selected_lanes_file, mas para um path
    arbitrário -- usado por station_strategies/evolution.py para persistir
    os estágios da evolução incremental (que não pertencem a um job
    específico, são compartilhados entre percentage/minutes)."""
    root = ET.Element("cs")
    for lane_id in lanes:
        lane_elem = ET.SubElement(root, "lane")
        lane_elem.text = str(lane_id)
    _pretty_write(root, path)


def read_selected_lanes_file(path: Path) -> set[str]:
    """
    Lê de volta um arquivo no formato acima (ou no formato legado
    <additional>/<quadrant> com <lane> filhos em qualquer profundidade --
    por isso o './/lane' recursivo, que corrige o bug de
    generatingGreedy.py onde uma cópia usava 'lane' direto e outra
    './/lane', dando resultados diferentes para o mesmo tipo de arquivo).
    """
    lanes: set[str] = set()
    tree = ET.parse(path)
    root = tree.getroot()
    for lane_elem in root.findall(".//lane"):
        if lane_elem.text:
            lanes.add(lane_elem.text.strip())
    return lanes


# ---------------------------------------------------------------------------
# Sorteio de trips por percentual
# ---------------------------------------------------------------------------
def _strip_vtype_lines(lines: list) -> list:
    """
    Remove blocos <vType>...</vType> (ou <vType .../> auto-fechado) das
    linhas do trips.xml mestre antes de usá-las.

    Motivo: sample_trips copia pro arquivo de "restantes" (que vira o
    route-files do .cfg) tudo que não é uma linha <trip> sorteada -- se o
    trips.xml mestre já tiver um <vType id="soulEV65"> embutido (comum em
    arquivos gerados por ferramentas do próprio SUMO), ele se duplica
    contra o electric_vehicle.xml que carregamos explicitamente como
    additional-file, e o SUMO recusa a simulação com "Another vehicle type
    ... exists". A definição oficial e única do soulEV65 é sempre
    config.ELECTRIC_VEHICLE_TYPE_FILE -- nenhum outro arquivo deveria
    carregar um <vType> com esse id.
    """
    result = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if skipping:
            if "</vType>" in stripped:
                skipping = False
            continue
        if stripped.startswith("<vType"):
            if stripped.endswith("/>"):
                continue  # auto-fechado, uma linha só -- já removido
            skipping = True
            continue
        result.append(line)
    return result


def sample_trips(job: SimJob) -> None:
    """
    A partir do trips.xml mestre (config.TRIPS_FILE), sorteia
    `job.percentage`% de `job.vehicles` linhas <trip> e grava:
        - job.sorted_cars_file: as sorteadas (viram veículos elétricos,
          roteados para estação via TraCI em tempo de simulação)
        - job.trips_file: o restante (veículos normais, consumidos
          diretamente pelo route-files do .sumo.cfg)

    IMPORTANTE: chame seed_registry.apply(...) antes desta função, para que
    o sorteio seja reprodutível a partir da seed registrada do job (e não
    dependa do estado global de random no momento da chamada).
    """
    quantidade = int((job.percentage / 100) * job.vehicles)

    with open(config.TRIPS_FILE, "r", encoding="utf-8") as f:
        linhas = _strip_vtype_lines(f.readlines())

    linhas_com_trip = [linha.strip() for linha in linhas if "<trip" in linha]
    if quantidade > len(linhas_com_trip):
        raise ValueError(
            f"Pedido de {quantidade} trips ({job.percentage}% de {job.vehicles}) "
            f"excede as {len(linhas_com_trip)} trips disponíveis em {config.TRIPS_FILE}"
        )

    linhas_sorteadas = set(random.sample(linhas_com_trip, quantidade))

    job.sorted_cars_dir.mkdir(parents=True, exist_ok=True)
    tmp_sorted = job.sorted_cars_file.with_suffix(".xml.tmp")
    tmp_sorted.write_text("\n".join(sorted(linhas_sorteadas)), encoding="utf-8")
    tmp_sorted.replace(job.sorted_cars_file)

    linhas_restantes = [linha for linha in linhas if linha.strip() not in linhas_sorteadas]
    job.folder.mkdir(parents=True, exist_ok=True)
    tmp_remaining = job.trips_file.with_suffix(".xml.tmp")
    tmp_remaining.write_text("".join(linhas_restantes), encoding="utf-8")
    tmp_remaining.replace(job.trips_file)


# ---------------------------------------------------------------------------
# cologneN.sumo.cfg
# ---------------------------------------------------------------------------
def write_cfg_file(job: SimJob, routing_threads: int | None = None) -> None:
    """
    Gera o .sumo.cfg desta repetição. Antes escrito à mão linha por linha
    (5 cópias quase idênticas); aqui via ElementTree, então erros de tag
    fechada errada viram erro de parsing em vez de XML malformado silencioso.

    Paths de net-file/astar.landmark-distances vão absolutos (config.py),
    o que elimina os "../../../input/" hardcoded que quebravam dependendo
    de quem chamava o script. route-files/additional-files continuam
    relativos (só o nome do arquivo) -- o SUMO resolve caminhos relativos
    de um .cfg em relação à pasta do próprio .cfg, e ambos os arquivos
    vivem ao lado dele (job.folder).
    """
    threads = routing_threads if routing_threads is not None else config.ROUTING_THREADS

    root = ET.Element("configuration")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set("xsi:noNamespaceSchemaLocation", "http://sumo.dlr.de/xsd/sumoConfiguration.xsd")

    input_el = ET.SubElement(root, "input")
    ET.SubElement(input_el, "net-file").set("value", str(config.NET_FILE))
    ET.SubElement(input_el, "route-files").set("value", job.trips_file.name)
    # FIX: o .add.xml (estações) sozinho aqui NÃO carrega o vType "soulEV65"
    # -- sem isso, traci.vehicle.add(..., typeID="soulEV65", ...) usa um tipo
    # padrão silenciosamente (sem device.battery), e os "veículos elétricos"
    # não têm bateria de verdade pra recarregar. Esse bug já existia no
    # projeto original (electric_vehicle.xml só era referenciado em código
    # morto) -- corrigido carregando os dois arquivos como additional-files.
    ET.SubElement(input_el, "additional-files").set(
        "value", f"{job.add_file.name},{config.ELECTRIC_VEHICLE_TYPE_FILE}"
    )

    time_el = ET.SubElement(root, "time")
    ET.SubElement(time_el, "begin").set("value", str(config.SIM_BEGIN_TIME_S))

    routing_el = ET.SubElement(root, "routing")
    ET.SubElement(routing_el, "routing-algorithm").set("value", "astar")
    ET.SubElement(routing_el, "astar.landmark-distances").set(
        "value", str(config.LANDMARK_DISTANCES_FILE)
    )
    ET.SubElement(routing_el, "device.rerouting.period").set("value", "300")
    ET.SubElement(routing_el, "device.rerouting.adaptation-steps").set("value", "18")
    ET.SubElement(routing_el, "device.rerouting.adaptation-interval").set("value", "10")
    ET.SubElement(routing_el, "device.rerouting.threads").set("value", str(threads))

    report_el = ET.SubElement(root, "report")
    ET.SubElement(report_el, "verbose").set("value", "true")
    ET.SubElement(report_el, "log").set("value", "cologne6to8.log")
    ET.SubElement(report_el, "duration-log.statistics").set("value", "true")
    ET.SubElement(report_el, "no-step-log").set("value", "true")

    _pretty_write(root, job.cfg_file)


# ---------------------------------------------------------------------------
# cologneN.add.xml
# ---------------------------------------------------------------------------
def write_add_file(job: SimJob, lanes: Iterable[str] | None = None) -> None:
    """
    Gera o .add.xml com <chargingStation> + <parkingArea> desta repetição.
    Se `lanes` não for passado, lê de job.selected_lanes_file (o arquivo
    já deve ter sido gerado pela station strategy antes de chamar isso).

    Cada estação é DOIS elementos na mesma lane, com o mesmo id:
    - <parkingArea roadsideCapacity=...> -- capacidade REAL, calculada por
      lane (ver graph_utils.realized_capacity): min(job.max_vehicles_per_cs,
      quantos veículos cabem fisicamente naquela lane específica), nunca
      menos que 1. Decisão metodológica: a seleção de estação (nas 5
      strategies) NÃO filtra mais por capacidade -- qualquer lane escolhida
      é aceita, e a capacidade só se ajusta aqui, na hora de gerar o
      arquivo, à geometria real daquela posição específica.
    - <chargingStation parkingArea="<mesmo id>"> -- dá a potência de
      recarga. O atributo `parkingArea` (documentado em
      https://sumo.dlr.de/docs/Models/Electric.html#charging_stations) liga
      as duas explicitamente: "vehicles will only charge after reaching the
      parking".
    """
    if lanes is None:
        lanes = read_selected_lanes_file(job.selected_lanes_file)

    lane_lengths = graph_utils.lane_lengths()
    veh_length = vehicle_length("soulEV65")

    root = ET.Element("additional")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set("xsi:noNamespaceSchemaLocation", "http://sumo.dlr.de/xsd/additional_file.xsd")

    for i, lane_id in enumerate(sorted(lanes)):
        capacity = graph_utils.realized_capacity(
            lane_id, job.max_vehicles_per_cs, lane_lengths, veh_length
        )

        pa = ET.SubElement(root, "parkingArea")
        pa.set("id", str(i))
        pa.set("name", "chargingStation")
        pa.set("lane", lane_id)
        pa.set("roadsideCapacity", str(capacity))

        cs = ET.SubElement(root, "chargingStation")
        cs.set("id", str(i))
        cs.set("name", "chargingStation")
        cs.set("lane", lane_id)
        cs.set("power", config.CHARGING_POWER_W)
        cs.set("chargeInTransit", config.CHARGE_IN_TRANSIT)
        cs.set("chargeDelay", config.CHARGE_DELAY_S)
        cs.set("parkingArea", str(i))  # liga explicitamente à parkingArea de mesmo id

    _pretty_write(root, job.add_file)


# ---------------------------------------------------------------------------
# vType (electric_vehicle.xml) -- lido estaticamente, sem depender de uma
# simulação TraCI viva (a fase de geração roda antes de qualquer SUMO
# iniciar).
# ---------------------------------------------------------------------------
def vehicle_length(type_id: str = "soulEV65") -> float:
    tree = ET.parse(config.ELECTRIC_VEHICLE_TYPE_FILE)
    root = tree.getroot()
    for vtype in root.findall(".//vType"):
        if vtype.get("id") == type_id:
            return float(vtype.get("length"))
    raise ValueError(
        f"vType '{type_id}' não encontrado em {config.ELECTRIC_VEHICLE_TYPE_FILE}"
    )