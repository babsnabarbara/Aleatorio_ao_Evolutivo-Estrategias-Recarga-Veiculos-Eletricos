"""
Gera as malhas de quadrantes usadas pelos approaches `greedy` e
`pseudorandom` -- input/lanesInEachQuadrant/{9,16,25,36,49}quadrants.xml.

Migrado pra usar os paths centralizados de config.py (em vez de
"../input/..." fixo, que só funcionava se o script fosse chamado de dentro
de MD/) e pra expor `generate_all_quadrants()` como função importável --
é isso que permite `station_strategies` (greedy/pseudorandom) chamarem
esse gerador sozinhos, sob demanda, se os arquivos ainda não existirem, em
vez de você precisar lembrar de rodar `python3 quadrants.py` manualmente
antes.

Rodar direto continua funcionando exatamente como antes:

    python3 quadrants.py
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from xml.dom import minidom

import config


def criar_elemento_quadrant(root, quadrant, lanes):
    quadrant_elem = ET.SubElement(root, "quadrant")
    quadrant_elem.set("x", str(quadrant[0]))
    quadrant_elem.set("y", str(quadrant[1]))

    for lane_id in lanes:
        lane_elem = ET.SubElement(quadrant_elem, "lane")
        lane_elem.text = str(lane_id)


def dividir_em_quadrants(conv_boundary, num_quadrants, lanes):
    # Dividindo as coordenadas da convBoundary
    x_min, y_min, x_max, y_max = map(float, conv_boundary.split(","))

    # Calculando o tamanho do quadrant
    quadrant_raiz = int(math.sqrt(num_quadrants))
    tamanho_quadrant_x = (x_max - x_min) / quadrant_raiz
    tamanho_quadrant_y = (y_max - y_min) / quadrant_raiz

    # Inicialize a estrutura para armazenar os quadrants e suas lanes associadas
    quadrants = {(i, j): [] for i in range(quadrant_raiz) for j in range(quadrant_raiz)}

    # Preenchendo os quadrants com as lanes correspondentes
    for lane in lanes:
        coords = lane["coords"]
        for j in coords:
            x, y = map(float, j.split(" "))
            quadrant_x = int((x - x_min) / tamanho_quadrant_x)
            quadrant_y = int((y - y_min) / tamanho_quadrant_y)

            # esses condicionais não tem nada a ver com evitar arredondamento, é
            # simplesmente porque o cologne disponibilizou o arquivo onde as
            # coordenadas de algumas lanes ultrapassam a delimitação da
            # convBoundary descrita no próprio arquivo, então caso ultrapasse um
            # pouco o último quadrant, a lane vai ser inclusa nele
            if quadrant_x == quadrant_raiz:
                quadrant_x = quadrant_raiz - 1
            if quadrant_y == quadrant_raiz:
                quadrant_y = quadrant_raiz - 1

            # Verificar se a lane_id já existe no quadrant, se não, adicionar
            if lane["lane_id"] not in quadrants[(quadrant_x, quadrant_y)]:
                quadrants[(quadrant_x, quadrant_y)].append(lane["lane_id"])

    return quadrants


def parse_xml(xml_content):
    root = ET.fromstring(xml_content)

    # Obtendo as informações da convBoundary
    conv_boundary = root.find(".//location").attrib["convBoundary"]

    # Obtendo a lista de edges com suas respectivas lanes
    edges = root.findall(".//edge[@type]")
    lanes = []
    for edge in edges:
        for lane in edge.findall("./lane"):
            lane_id = f"{lane.attrib['id']}"
            coords = lane.attrib["shape"].split(",")
            if " " in coords[0]:
                lanes.append({"lane_id": lane_id, "coords": coords})
            else:
                coords.pop(0)
                coords.pop()
                lanes.append({"lane_id": lane_id, "coords": coords})

    return conv_boundary, lanes


def generate_all_quadrants() -> None:
    """
    Gera as 5 malhas (9, 16, 25, 36, 49 quadrantes) a partir do
    cologne.net.xml, em input/lanesInEachQuadrant/. Idêntico ao que o
    script fazia rodado direto -- só extraído pra função, pra poder ser
    chamado de outros módulos (station_strategies/greedy_strategy.py e
    pseudorandom_strategy.py chamam isso sozinhos se os arquivos ainda não
    existirem).
    """
    config.LANES_IN_EACH_QUADRANT_DIR.mkdir(parents=True, exist_ok=True)

    with open(config.NET_FILE, "r") as file:
        xml_content = file.read()
    conv_boundary, lanes = parse_xml(xml_content)

    for i in range(3, 8):
        num_quadrants = i ** 2

        resultado = dividir_em_quadrants(conv_boundary, num_quadrants, lanes)

        root = ET.Element("quadrants")
        for quadrant, quadrant_lanes in resultado.items():
            criar_elemento_quadrant(root, quadrant, quadrant_lanes)

        xml_str = ET.tostring(root, encoding="utf-8")
        xml_formatted = minidom.parseString(xml_str).toprettyxml(indent="  ")

        out_path = config.LANES_IN_EACH_QUADRANT_DIR / f"{num_quadrants}quadrants.xml"
        with open(out_path, "w") as file:
            file.write(xml_formatted)


if __name__ == "__main__":
    generate_all_quadrants()
