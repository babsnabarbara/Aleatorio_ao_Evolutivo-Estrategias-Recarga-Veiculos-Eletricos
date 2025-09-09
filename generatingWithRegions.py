import random
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
import re
import xml.etree.ElementTree as ET
import random
import networkx as nx
from bs4 import BeautifulSoup
import argparse
import os
from scipy.spatial import Voronoi, voronoi_plot_2d
import matplotlib.pyplot as plt
import numpy as np


# Sorteia um número entre 6 e 252736
def sortear_numero():
    return random.randint(6, 252736)

def extrair_linhas_sorteadas(arquivo_xml, numeros_sorteados):
    tree = ET.parse(arquivo_xml)
    root = tree.getroot()
    linhas_sorteadas = []

    # Cria a estrutura do XML para as linhas sorteadas
    novo_root = ET.Element('routes')
    novo_root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    novo_root.set('xsi:noNamespaceSchemaLocation', 'http://sumo.dlr.de/xsd/routes_file.xsd')
    for idx, elemento in enumerate(root):
        if idx in numeros_sorteados:
            novo_root.append(elemento)

    # Converte o novo ElementTree em uma string XML
    novo_xml_str = ET.tostring(novo_root,encoding='utf-8')

    # Formata a string XML usando xml.dom.minidom
    parsed_novo_xml = minidom.parseString(novo_xml_str)
    linhas_sorteadas.append(parsed_novo_xml.toprettyxml(indent="\t",newl=" ", encoding="utf-8"))

    return linhas_sorteadas


def sortCarsAndTrips(numberOfCars, fromRoute):
    # Número de linhas aleatórias a serem lidas

    # Nome do arquivo XML original
    nome_arquivo_xml = '../input/cologne6to8.trips.xml'

    inputFolder = "../input/"
    outputFolder = "../output/greedyvoronoi/"+str(numberOfCars)+"/"
    outputNet = "rotas"
    netInCgFile = "cologne"
    outputName = inputFolder + netInCgFile + ".net.xml"

    f = open(inputFolder + "electric_vehicle.xml", "r")
    electric_type = ""
    for line in f:
        electric_type+= line
    f.close()

    for i in range(fromRoute,fromRoute+10):
        # Lista de números sorteados
        numeros_sorteados = [sortear_numero() for _ in range(numberOfCars)]
        # Extrai as linhas correspondentes aos números sorteados
        linhas_sorteadas = extrair_linhas_sorteadas(nome_arquivo_xml, numeros_sorteados)

        # Cria um novo arquivo XML com as linhas sorteadas e quebra de linha
        output = outputFolder + outputNet + str(i) + ".trips.xml"
        nome_arquivo_novo = output
        with open(nome_arquivo_novo, 'w', encoding='utf-8') as arquivo_novo:
            for linha_xml_bytes in linhas_sorteadas:
                linha_xml_str = linha_xml_bytes.decode('utf-8')  # Converte bytes em string
                arquivo_novo.write(linha_xml_str)  # Escreve a string no arquivonha

        file = ""
        file+= electric_type + "\n"

        f = open(output, "r")
        lines = f.readlines()
        i = 0
        for line in lines:
            if "<trip" not in line:
                file += line
            else:
                
                idAttribute = r'id="([^"]+)"'
                #dAttribute = r'depart="([^"]+)"'
                fAttribute = r'from="([^"]+)"'
                tAttribute = r'to="([^"]+)"'
                
                idMatch = re.search(idAttribute, line)
                #dMatch = re.search(dAttribute, line)
                fMatch = re.search(fAttribute, line)
                tMatch = re.search(tAttribute, line)
                
                file += f'    <trip id="{idMatch.group(1)}" depart="0" from="{fMatch.group(1)}" to="{tMatch.group(1)}" type="electric_vehicle"/>\n'
                i += 1

        f.close()
        f = open(output, "w")
        f.seek(0)
        f.truncate()
        f.seek(0)
        f.write(file)
        f.close()

def makeCfgs(percentage, newFolder, amountOfCars):
    print("makecfgs")
    
    for i in range(1, 6):
        sortearCarrosPorPercentual("../input/cologne6to8.trips.xml", percentage, i, amountOfCars, newFolder)
        inputFolder = "../../../input/"
        outputNet = "cologne"
        outputName = inputFolder + "cologne.net.xml"
        outputFolder = "../output/greedyvoronoi/" + newFolder + "/"
        cfg = outputFolder + outputNet + str(i) + ".sumo.cfg"
        routeFile =  inputFolder + "cologne6to8.trips.xml"
        f = open(cfg, "w")
        line = '<?xml version="1.0" encoding="UTF-8"?>\n'
        f.write(line)
        line = '<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">\n'
        f.write(line)
        line = "\t<input>\n"
        f.write(line)
        line = "\t\t<net-file value=\"" + outputName + "\"/>\n"
        f.write(line)
        line = "\t\t<route-files value=\""+ "cologne6to8-"+str(i)+".trips.xml" "\"/>\n"
        f.write(line)
        line = "\t\t<additional-files value=\"" + "cologne"+ str(i)+".add.xml\"" + "/>\n"
        f.write(line)
        line = "\t</input>\n"
        f.write(line)
        line = "\t<time>\n"
        f.write(line)
        line = '\t\t<begin value="21600"/>\n'
        f.write(line)
        line = '\t</time>\n'
        f.write(line)


        line = "\t<routing>\n"
        f.write(line)
        line = '\t\t<routing-algorithm value="astar"/>\n'
        f.write(line)
        line = '\t\t<astar.landmark-distances value="'+ inputFolder+'cologne_landmark_distances.txt"/>\n'
        f.write(line)
        line = '\t\t<device.rerouting.period value="300"/>\n'
        f.write(line)
        line = '\t\t<device.rerouting.adaptation-steps value="18"/>\n'
        f.write(line)
        line = '\t\t<device.rerouting.adaptation-interval value="10"/>\n'
        f.write(line)
        line = '\t\t<device.rerouting.threads value="4"/>\n'
        f.write(line)
        line = "\t</routing>\n"
        f.write(line)


        line = "\t<report>\n"
        f.write(line)
        line = '\t\t<verbose value="true"/>\n'
        f.write(line)
        line = '\t\t<log value="cologne6to8.log"/>\n'
        f.write(line)
        line = '\t\t<duration-log.statistics value="true"/>\n'
        f.write(line)
        line = '\t\t<no-step-log value="true"/>\n'
        f.write(line)
        line = "\t</report>\n"
        f.write(line)

        line = "</configuration>"
        f.write(line)
        f.close()
        
def getMostVisitedLanes(file_path):#vai retornar as lanes mais visitadas e quantas visitas cada uma teve
    # Analisar a string XML
    tree = ET.parse(file_path)
    root = tree.getroot()
    # Inicializar um dicionário para armazenar id e count de cada lane
    lanes_dict = {}

    # Iterar sobre elementos 'lane'
    for lane_elem in root.findall('.//lane'):
        # Obter atributos 'id' e 'count'
        lane_id = lane_elem.get('id')
        count = lane_elem.get('count')

        # Adicionar ao dicionário
        lanes_dict[lane_id] = {'count': count}

    return lanes_dict
def getLanesInEachQuadrant(file): #quais lanes estão localizadas em cada quadrante
    
    quadrantsFile = file
    tree = ET.parse (quadrantsFile)
    root = tree.getroot()

    quadrantsAndLanes = {}
    
    for quadrante in root.findall('.//quadrante'):
        lanes = list()
        x = quadrante.get('x')
        y = quadrante.get('y')
        for lane in quadrante.findall('lane'):
            lanes.append(lane.text)
        quadrantsAndLanes[(x, y)] = {'lanes': lanes}
    return quadrantsAndLanes

def setRegionFlags(regions): #quais lanes estão localizadas em cada quadrante
    regionFlags = {}
    for region in regions:
        regionFlags[region] = {'isFull': False}
    return regionFlags


def createVeronoiDiagram(netfile, numberOfRegions, folderToVoronoiImage):
    print("beginningCreate")
    # Carregar o arquivo XML
    tree = ET.parse(netfile)
    root = tree.getroot()
    regions = list()
    # Coordenadas do mapa
    conv_boundary = root.find(".//location").attrib["convBoundary"]
    conv_boundary = list(map(float, conv_boundary.split(',')))

    # Número desejado de células Voronoi
    num_cells = numberOfRegions  # Substitua pelo número desejado

    # Sortear pontos aleatórios dentro das delimitações do mapa

    random_points = np.random.uniform([conv_boundary[0], conv_boundary[1]],
                                    [conv_boundary[2], conv_boundary[3]], size=(num_cells, 2))
    print ("random: ", random_points)
    # Criar o Diagrama de Voronoi
    vor = Voronoi(random_points)
    # Visualizar o Diagrama de Voronoi
    
    voronoi_plot_2d(vor)
    # Adicionar rótulos para cada ponto com o número da região
    for point, region_index in zip(random_points, vor.point_region):
        plt.text(point[0], point[1], f'Região {region_index}', color='red', ha='center', va='center')
        regions.append(region_index)
    #plt.xlim([conv_boundary[0], conv_boundary[2]])
    #plt.ylim([conv_boundary[1], conv_boundary[3]])
    plt.savefig("../output/greedyvoronoi/"+folderToVoronoiImage + "/voronoi.png")
    #print("\nregions up here: ",regions)
    #print("beforeshowing")
    #plt.show()
    #print("aftershowing")
    return vor, regions

def findRegion(lane, vor):
    #for i in lane: #só vai receber uma lane, o for vai executar uma vez, e ele só existe 
    coords = lane['coords']

    #print("lane: ", lane)
    regions = set()
    for coord in coords:
        strCoord = coord.split(' ')
        specific_coordinates = np.array([float(strCoord[0]), float(strCoord[1])]) #falta colocar coords aqui
        # Encontrar a região de Voronoi associada às coordenadas específicas
        region_index = vor.point_region[np.argmin(np.linalg.norm(vor.points - specific_coordinates, axis=1))]
        regions.add(region_index)
    return regions

def getLanesAndCoordinates(netfile):
    with open(netfile, "r") as file:
        xml_content = file.read()
    root = ET.fromstring(xml_content)

    # Obtendo a lista de edges com suas respectivas lanes
    edges = root.findall(".//edge[@type]")
    lanes = {}

    for edge in edges:
    
        for lane in edge.findall("./lane"):
            lane_id = f"{lane.attrib['id']}"
            coords = lane.attrib["shape"].split(',')
            lanes[lane_id] = {}
            if ' ' in coords[0]:
                lanes[lane_id]['coords'] = coords 
            else:
                coords.pop(0)
                coords.pop()
                lanes[lane_id]['coords'] = coords 
          

    return lanes

def findValidChargingPoints(netfile, numberOfRegions, folderToVoronoiImage):

    mostVisitedLanes = getMostVisitedLanes("../input/mostVisited.xml")
    vor, regions = createVeronoiDiagram("../input/cologne.net.xml",numberOfRegions, folderToVoronoiImage)
    regionFlags = setRegionFlags(regions)
    lanesAndCoords = getLanesAndCoordinates("../input/cologne.net.xml")

    chargingPoints = set()
    regionsFull = 0
    #print("foi ate aqui")
    for lane_id, lane_info in mostVisitedLanes.items():
        if regionsFull >= numberOfRegions:
            break

        if regionsFull < numberOfRegions:
            regionsFound = findRegion(lanesAndCoords[lane_id], vor)
            for i in regionsFound:

                if (regionFlags[i]['isFull'] == False) and (lane_id not in chargingPoints):
                    regionFlags[i]['isFull'] = True
                    chargingPoints.add(lane_id)
                    regionsFull+=1
                    #print("lane: ", lane_id, ", count: ",  lane_info['count']   )
                    break
    if len(chargingPoints) < numberOfRegions:
        with open("../output/greedyvoronoi/"+folderToVoronoiImage+'/FLAGARCHIVE.txt', 'w') as arquivo:
            arquivo.write('não deu certo')
    else:
        with open("../output/greedyvoronoi/"+folderToVoronoiImage+'/FLAGARCHIVE.txt', 'w') as arquivo:
            arquivo.write('deu certo')

    return chargingPoints

def extract_lanes_from_xml(xml_file):
    lanes = set()
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for lane in root.findall('lane'):
            lanes.add(lane.text)
    except ET.ParseError:
        print("Erro ao analisar o arquivo XML.")
    return lanes

def makeAdds(pathToStations, newFolder):
    
    stationPoints = extract_lanes_from_xml(pathToStations)

    for i in range(1, 6):
        outputNet = "cologne"
        outputFolder = "../output/greedyvoronoi/"
        add = outputFolder + newFolder + "/" + outputNet + str(i) + ".add.xml"
        f = open(add, "w")
        line = '<?xml version="1.0" encoding="UTF-8"?>\n'
        f.write(line)
        line = '<additional xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/additional_file.xsd">\n'
        f.write(line)
        for i, station in enumerate(stationPoints):
            line = '\t<chargingStation id="' + str(i) + '" name="chargingStation" lane="' + station + '" power="20000.00" chargeInTransit="1" chargeDelay="100"/>\n'
            f.write(line)
        line = '</additional>\n'
        f.write(line)

        f.close()

def sortearCarrosPorPercentual(filename, porcentagem, numberFile, amountOfCars, newFolder):
    # Abre o arquivo original para leitura
    quantidade = int((porcentagem/100) * amountOfCars)
    with open(filename, 'r', encoding='utf-8') as file_origem:
        # Lê todas as linhas do arquivo
        linhas = file_origem.readlines()

        # Filtra as linhas que contêm a tag <trip
        linhas_com_trip = [linha.strip() for linha in linhas if '<trip' in linha]
        #print ("linhascomtrip: ", linhas_com_trip)
        # Verifica se o número de linhas com a tag é maior ou igual a x
    
        # Sorteia x linhas com a tag
        linhas_sorteadas = set(random.sample(linhas_com_trip, quantidade))
        #print("\n\n linhas sorteadas: ", linhas_sorteadas)

        # Cria um novo arquivo contendo apenas as linhas sorteadas
        nome_arquivo_sorteadas = "../output/greedyvoronoi/"+ newFolder+"/sortedCars" + str(numberFile) + ".xml"
        with open(nome_arquivo_sorteadas, 'w', encoding='utf-8') as file_sorteadas:
            file_sorteadas.write('\n'.join(linhas_sorteadas))

        # Cria um novo arquivo que é uma cópia do arquivo original, mas sem as linhas sorteadas
        nome_arquivo_sem_sorteadas = '../output/greedyvoronoi/'+newFolder+'/cologne6to8-' + str(numberFile) + ".trips.xml"
        linhas_sem_sorteadas = [linha for linha in linhas if linha.strip() not in linhas_sorteadas]
        with open(nome_arquivo_sem_sorteadas, 'w', encoding='utf-8') as file_sem_sorteadas:
            file_sem_sorteadas.write(''.join(linhas_sem_sorteadas))


def main ():
    print("beforeparsing")
    parser = argparse.ArgumentParser()
    
    
    parser.add_argument("-v", "--vehicles", dest="vehicles", help="Will the car reroute to a charging station or not [default: %(default)s]", metavar="COMMAND")
    parser.add_argument("-p", "--percentage", dest="percentage", help="Will the car reroute to a charging station or not [default: %(default)s]", metavar="COMMAND")
    parser.add_argument("-cs", "--chargingStationsAmount", dest="csAmount", help="Amount of charging stations", metavar="NUMBER")
    parser.add_argument("-m", "--max", dest="maxVehiclesPerCS", help="Max amount of vehicle that can recharge simoutaneously in a charging station [default: %(default)s]", metavar="NUMBER")
    parser.add_argument("-a", "--approach", dest="approach", 
                        help="Algorithm used to deploy the charging stations", metavar="STRING")
    args = parser.parse_args()

    cmd = f"python3 findingStationsGreedyVoronoi.py -m {args.maxVehiclesPerCS} -a {args.approach}"
    os.system (cmd)
    
    newFolder = str(args.percentage) + "percentage" + str(args.csAmount) + "cs" 
    os.system("mkdir ../output/greedyvoronoi/" + newFolder)
    
    makeCfgs(int(args.percentage), newFolder, int(args.vehicles))

    pathToStations = "../output/greedyvoronoi/voronoiStations/"+str(args.csAmount)+"chargingstations"
    print("path: ", pathToStations)
    makeAdds(pathToStations, newFolder)
 

# this is the main entry point of this script
if __name__ == "__main__": 
    main()
