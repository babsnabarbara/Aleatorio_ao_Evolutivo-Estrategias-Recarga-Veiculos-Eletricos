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

# we need to import python modules from the $SUMO_HOME/tools directory
if 'SUMO_HOME' in os.environ:
    tools = os.path.join(os.environ['SUMO_HOME'], 'tools')
    sys.path.append(tools)
else:
    sys.exit("please declare environment variable 'SUMO_HOME'")

from sumolib import checkBinary  # noqa
import traci  # noqa
from traci import constants as tc

def batteryActualValue (vehicle):
    return ((float)(traci.vehicle.getParameter(vehicle,"device.battery.actualBatteryCapacity")))

def maximumBatteryCapacity(vehicle):
    return ((float)(traci.vehicle.getParameter(vehicle,"device.battery.maximumBatteryCapacity")))


def isTheBatteryFull (vehicle):
    return (batteryActualValue(vehicle) == maximumBatteryCapacity(vehicle))

def isTheBatteryLow (vehicle, threshold):
    return (maximumBatteryCapacity(vehicle) * threshold >= batteryActualValue(vehicle))
    
def hasReachedMaxTimeCharging (begtime):
    return(traci.simulation.getTime()-begtime)>=3600#1 hora

def sortCars (cars, percentage):
   
    amountOfCars = int(len(cars) * (percentage / 100))

    sortedCars = set()
    
    while len(sortedCars) < amountOfCars:
        sortedCar = random.choice(cars)
        sortedCars.add(sortedCar)

    return sortedCars

def isStuck():
    restingVehicles = 0
    if traci.simulation.getTime() >= 500000:
            for vehicle in traci.vehicle.getIDList():
                if traci.vehicle.getSpeed(vehicle) == 0:
                    restingVehicles+=1
                   
            if restingVehicles == traci.vehicle.getIDCount():
                return 1

def originalRoute(args):

    """execute the TraCI control loop"""
    step = 0
    #tripinfo = createTripInfo()
    while traci.simulation.getMinExpectedNumber()>0:  
        #getTripInfo(tripinfo)
        #if isStuck() == 1:
        #    print ("tempo: ", traci.simulation.getTime())
        #    print ("minExpected: ", traci.simulation.getMinExpectedNumber())
        #    return 1
        #step+=1
        traci.simulationStep()
    #tripInfoOutput(args, tripinfo)
    return 0
    
def readChargingStations (args):
    with open(args.csAmountFile, 'r') as xml_file:
        soup = BeautifulSoup(xml_file, 'xml')

    # Cria um dicionário para armazenar os attributes 'lane'
    chargingStations = {}

    # Encontra todos os elementos 'chargingStation'
    charging_station_elements = soup.find_all('chargingStation')

    # Itera sobre os elementos e extrai os attributes 'id' e 'lane'
    for charging_station in charging_station_elements:
        id = charging_station['id']
        lane = charging_station['lane']
        chargingStations[id] = {'lane': lane}
        

    return chargingStations

def run(args, graph, actualSimulation, folder):
    step = traci.simulation.getTime() 
    chargingStations = readChargingStations(args)
    #print("charging: ", chargingStations)
    if int(args.csAmount) != 0:
        for i, value in chargingStations.items():
            chargingStations[i]['edge'] = traci.lane.getEdgeID(value['lane'])
    
        dictCars = dict_trip(f"{folder}/sortedCars-{args.vehicles}/sortedCars{actualSimulation}.xml")
        duration = int(args.timeOfRecharge) * 60
        print(f"DURATION: {duration}")
        for carID, attributes in dictCars.items():
            #print("id: ",carID)
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
            traci.vehicle.setChargingStationStop(carID, stopSpot, duration= str(duration), flags=1)
        print("ACABOU AS ROTAS")
    
    try:
        print("ANTES DE >0")
        while traci.simulation.getMinExpectedNumber() > 0:
            print("antes do STEP")
            traci.simulationStep()
            print("depois do STEP")
            # código da simulação
    except traci.exceptions.FatalTraCIError as e:
        print(f"Erro: {e}")


    return 0
    
        
def generate_graph(netfile):
    f = open(netfile)
    data = f.read()
    soup = BeautifulSoup(data, "xml")

    f.close()

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

def createTripInfo():
    tripinfo = []
    return tripinfo

def getTripInfo(tripinfo):
    vehicle_ids = traci.vehicle.getIDList()
    for vehicle_id in vehicle_ids:
        trip_data = next((trip for trip in tripinfo if trip['id'] == vehicle_id), None)
        if trip_data is not None:
            # Veículo já existe na lista tripinfo, substituir o value de distância
            trip_data['distance'] = traci.vehicle.getDistance(vehicle_id)
        else:
            # Veículo ainda não existe na lista tripinfo, adicionar uma nova entrada
            trip_data = {'id': vehicle_id, 'distance': traci.vehicle.getDistance(vehicle_id)}
            tripinfo.append(trip_data)

    
def tripInfoOutput (args, tripinfo):
    # Write tripinfo data to XML file
    with open(args.tripinfo_output, 'w') as f:
        f.write('<tripinfos>\n')
        for trip_data in tripinfo:
            
            f.write('  <tripinfo ')
            for key, value in trip_data.items():
                f.write(f'{key}="{value}" ')
            f.write('/>\n')
        f.write('</tripinfos>\n')
 
    

def reroute(source, target, graph):
    new_route = nx.dijkstra_path(graph, source, target)
    if len(new_route)>0:
        new_route = new_route[1:]
    return new_route   


def decide(vehicle, chargingStations, graph, source):
    # Encontre o menor caminho para cada destino
    smaller_path = None
    destination = None
    lane = None
    smaller_distance = float('inf')
    

    for i, station_data in chargingStations.items():
        lane = station_data['edge']
        path = nx.dijkstra_path(graph, source, lane)
        distance = sum(graph[path[i]][path[i+1]]['weight'] for i in range(len(path)-1))
        
        
        if distance < smaller_distance:
            smaller_distance = distance
            smaller_path = path
            destination = i
    result = {}
    result['path'] = smaller_path
    result['id'] = destination
    return result

def dict_trip(filename):
    # Abre o arquivo para leitura
    with open(filename, 'r', encoding='utf-8') as file:
        # Lê todas as lines do arquivo
        lines = file.readlines()

        # Inicializa o dicionário para armazenar as informações das viagens
        viagens_dict = {}

        # Itera sobre cada line do arquivo
        for line in lines:
            # Remove espaços em branco e divide a line pelos espaços em branco
            partes = line.strip().split()

            # Inicializa um dicionário para armazenar os attributes da viagem
            attributes = {}

            # Itera sobre cada parte da line
            for parte in partes:
                try:
                    # Divide cada parte pelo sinal de igual para obter o name e o value do attribute
                    name, value = parte.split('=')

                    # Remove as aspas do value
                    value = value.strip('"\'')

                    # Adiciona o attribute ao dicionário, apenas se for um dos attributes desejados
                    if name in ['id', 'depart', 'from', 'to']:
                        attributes[name] = value
                except ValueError:
                    pass

            # Obtém o ID da viagem
            viagem_id = attributes.get('id')

            # Adiciona o dicionário de attributes ao dicionário principal usando o ID da viagem como chave
            viagens_dict[viagem_id] = attributes

    return viagens_dict

def makeFiles (args, approachFiles, folder):
    functions.makeCfgs(args, folder)
    print("MAKE FILES")
    cmd = f"python3 {approachFiles[args.approach]}"
    os.system(cmd)
    print("MAKE ADDS")
    functions.makeAdds(args, folder)   
    functions.sortearCarrosPorPercentual(args.percentage, args.fileToBeRun, args.vehicles, folder)
    
def main():
    # Option handling
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--max", dest="maxVehiclesPerCS", 
                        help="Max amount of vehicle that can recharge simoutaneously in a charging station [default: %(default)s]", metavar="NUMBER")
    parser.add_argument("-t", "--timeOfRecharge", dest="timeOfRecharge", 
                        help="Time electric vehicles will take to recharge [default: %(default)s]", metavar="NUMBER")
    parser.add_argument("-f", "--fileToBeRun", dest="fileToBeRun", 
                        help="Number of the SUMO files that will be run [default: %(default)s]", metavar="NUMBER")
        
    parser.add_argument("-c", "--command", dest="command", default="sumo", 
                    help="The command used to run SUMO [default: %(default)s]", metavar="COMMAND")
    parser.add_argument("-s", "--scenario", dest="scenario", 
                        help="A SUMO configuration file [default: %(default)s]", metavar="FILE")
    parser.add_argument("-n", "--network", dest="network", default="../input/cologne.net.xml", 
                        help="A SUMO network definition file [default: %(default)s]", metavar="FILE")
    parser.add_argument("-qFile", "--qFile", dest="qFile", default="../input/cologne.add.xml", 
                        help="A SUMO additional file [default: %(default)s]", metavar="FILE")
    parser.add_argument("--tripinfo-output", dest="tripinfo_output", 
                        help="Output file for trip information [default: %(default)s]", metavar="FILE")
    parser.add_argument("-p", "--percentage", dest="percentage", default="0", 
                        help="Percentage of cars that will recharge [default: %(default)s]", metavar="NUMBER")
    parser.add_argument("-cs", "--chargingStationsAmount", dest="csAmount", 
                        help="Amount of charging stations", metavar="NUMBER")
    parser.add_argument("-v", "--vehicles", dest="vehicles", default="8000", 
                        help="Number of vehicles in the simulation [default: %(default)s]", metavar="NUMBER")
    parser.add_argument("-a", "--approach", dest="approach", 
                        help="Algorithm used to deploy the charging stations", metavar="STRING")
    
    args = parser.parse_args()
    folder = functions.createExperimentFolder(args)

    approachFiles = {}
    approachFiles["random"] = f"findingRandom.py -cs {args.csAmount} -p {args.percentage} -m {args.maxVehiclesPerCS} -fd {folder}"
    approachFiles["greedy"] = f"findingStationsGreedy.py -cs {args.csAmount} -fd {folder}"
    approachFiles["pseudorandom"] = f"findingPseudoRandom.py -p {args.percentage} -cs {args.csAmount} -m {args.maxVehiclesPerCS} -fd {folder}"
    approachFiles["greedyvoronoi"] = f"findingStationsGreedyVoronoi.py -m {args.maxVehiclesPerCS} -a {args.approach} -fd {folder} -cs {args.csAmount} -f {args.fileToBeRun}"
    #ALL VEHICLES = 179259

    
    sumoBinary = checkBinary(args.command)
    p = str(args.percentage)
 
    graph = generate_graph(args.network)
    
    print("folder: " + folder)
    functions.createReportsFolder(folder)
    nameReport = f"{folder}/reports/REPORT-{args.fileToBeRun}file-{args.timeOfRecharge}time-{args.vehicles}vehicles-{args.maxVehiclesPerCS}maxPerCS"
    str(args.percentage) + "percentage-" + str(args.csAmount) + "cs"
    with open(nameReport, "w") as reportFile:
        reportFile.write("PORCENTAGEM DE VEÍCULOS: " + str(args.percentage) + "\n")
        reportFile.write("NÚMERO DE ESTAÇÕES DE RECARGA: " + str(args.csAmount) + "\n")
        reportFile.flush()
        
        reportFile.write("SIMULAÇÃO: " + str(args.fileToBeRun) + "\n")
        reportFile.flush()
        args.scenario = folder+"/cologne" + str(args.fileToBeRun) + ".sumo.cfg"
        args.csAmountFile = folder+"/cologne" + str(args.fileToBeRun) + ".add.xml"
        logname = folder+"/log" + str(args.fileToBeRun) + str(p)+ "percentage"+ str(args.csAmount) +"cs" + ".xml"

        makeFiles(args, approachFiles, folder)
        
        nameOutput = folder + "/"+ str(args.fileToBeRun) + "simulation" + str(args.percentage) + "percentual" + str(args.csAmount) + "cs.xml" 
        sumoCmd = [sumoBinary, "-c", args.scenario, "--log", logname, "--tripinfo-output", nameOutput]
        initial_time = datetime.datetime.now().strftime("%H:%M:%S")
        initial_date = datetime.date.today().strftime("%d/%m/%Y")
        reportFile.write("INÍCIO DA SIMULAÇÃO\n")
        reportFile.write("hora: " + initial_time + "\n")
        reportFile.write("data: " + initial_date + "\n")
        reportFile.flush()
        
        traci.start(sumoCmd)
        run(args, graph, args.fileToBeRun, folder)
        reportFile.write("FIM DA SIMULAÇÃO\n")
        final_time = datetime.datetime.now().strftime("%H:%M:%S")
        final_date = datetime.date.today().strftime("%d/%m/%Y")
        reportFile.write("hora: " + final_time + "\n")
        reportFile.write("data: " + final_date + "\n")
        #reportFile.write("tempo executado de sumo: " + str(traci.simulation.getTime()) + "\n")
        #reportFile.write("minExpected: " + str(traci.simulation.getMinExpectedNumber()) + "\n\n")
        reportFile.flush()
        sys.stdout.flush()
        traci.close()

  
# this is the main entry point of this script
if __name__ == "__main__": 
    main()
