from __future__ import absolute_import
from __future__ import print_function
from bs4 import BeautifulSoup
import networkx as nx
import random
import datetime
from pathlib import Path
import os
import sys
import argparse
import functions

# Importar módulos Python do diretório $SUMO_HOME/tools
if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("Por favor, declare a variável de ambiente 'SUMO_HOME'.")

from sumolib import checkBinary  # noqa
import traci  # noqa

def readChargingStations():
    with open("../output/sorted/sortedCS.xml", 'r') as xml_file:
        soup = BeautifulSoup(xml_file, 'xml')

    chargingStations = {}
    charging_station_elements = soup.find_all('chargingStation')

    for charging_station in charging_station_elements:
        id = charging_station['id']
        lane = charging_station['lane']
        chargingStations[id] = {'lane': lane}

    return chargingStations

def generate_graph(netfile):
    with open(netfile, 'r') as f:
        data = f.read()

    soup = BeautifulSoup(data, "xml")
    edges_length = {}

    for edge_tag in soup.findAll("edge"):
        edge_id = edge_tag["id"]
        lane_tag = edge_tag.find("lane")
        edge_length = int(float(lane_tag["length"]))
        edges_length[edge_id] = edge_length

    graph = nx.DiGraph()

    for connection_tag in soup.findAll("connection"):
        source_edge = connection_tag["from"]
        dest_edge = connection_tag["to"]
        graph.add_edge(source_edge, dest_edge, length=edges_length[source_edge], weight=1)

    return graph

def reroute(source, target, graph):
    new_route = nx.dijkstra_path(graph, source, target)
    if len(new_route) > 0:
        new_route = new_route[1:]
    return new_route

def decide(vehicle, chargingStations, graph, source):
    smaller_path = None
    destination = None
    smaller_distance = float('inf')

    for i, station_data in chargingStations.items():
        lane = station_data['edge']
        path = nx.dijkstra_path(graph, source, lane)
        distance = sum(graph[path[i]][path[i+1]]['weight'] for i in range(len(path)-1))

        if distance < smaller_distance:
            smaller_distance = distance
            smaller_path = path
            destination = i

    result = {'path': smaller_path, 'id': destination}
    return result

def run(args, graph):
    chargingStations = readChargingStations()

    for i, value in chargingStations.items():
        chargingStations[i]['edge'] = traci.lane.getEdgeID(value['lane'])

    dictCars = readChargingStations()
    duration = int(args.timeOfRecharge) * 60

    for carID, attributes in dictCars.items():
        source = dictCars[carID]['from']
        destination = dictCars[carID]['to']
        timeDeparture = dictCars[carID]['depart']

        result = decide(carID, chargingStations, graph, source)
        firstPath = result['path']
        stopSpot = result['id']
        chargingPoint = firstPath[-1]
        secondPath = reroute(chargingPoint, destination, graph)
        wholeRoute = firstPath + secondPath

        traci.route.add(carID, wholeRoute)
        traci.vehicle.add(carID, typeID="soulEV65", depart=timeDeparture, routeID=carID)
        traci.vehicle.setChargingStationStop(carID, stopSpot, duration=str(duration), flags=1)

    try:
        while traci.simulation.getMinExpectedNumber() > 0:
            traci.simulationStep()
    except traci.exceptions.FatalTraCIError as e:
        print(f"Erro: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--timeOfRecharge", dest="timeOfRecharge", help="Tempo de recarga [default: %(default)s]", metavar="NUMBER")
    parser.add_argument("-c", "--command", dest="command", default="sumo", help="Comando para rodar SUMO [default: %(default)s]", metavar="COMMAND")
    parser.add_argument("-n", "--network", dest="network", default="../input/cologne.net.xml", help="Arquivo de rede SUMO [default: %(default)s]", metavar="FILE")
    parser.add_argument("-v", "--vehicles", dest="vehicles", default="8000", help="Número de veículos na simulação [default: %(default)s]", metavar="NUMBER")

    args = parser.parse_args()

    sumoBinary = checkBinary(args.command)
    graph = generate_graph(args.network)
    folder = "output"  # Adapte conforme necessário

    functions.createReportsFolder(folder)


    args.scenario = "../input/cologne6to8.sumocfg"
    traci.start([sumoBinary, "-c", args.scenario])

    run(args, graph)


    traci.close()

if __name__ == "__main__":
    main()
