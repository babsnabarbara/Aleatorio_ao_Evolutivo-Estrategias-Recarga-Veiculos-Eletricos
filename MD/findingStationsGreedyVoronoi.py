import networkx as nx
import xml.etree.ElementTree as ET
import os
import xml.dom.minidom
from scipy.spatial import Voronoi, voronoi_plot_2d
import matplotlib.pyplot as plt
import numpy as np
import argparse
import traci
import functions

def getMostVisitedLanes(file_path):#vai retornar as lanes mais visitadas e quantas visitas cada uma teve
    # Analisar a string XML
    tree = ET.parse(file_path)
    root = tree.getroot()
    # Inicializar um dicionário para armazenar id e count de cada lane
    lanes_dict = {}

    # Iterar sobre elementos 'lane'
    for lane_elem in root.findall('.//lane'):
        # Obter atributos 'id' e 'cgount'
        lane_id = lane_elem.get('id')
        count = lane_elem.get('count')

        # Adicionar ao dicionário
        lanes_dict[lane_id] = {'count': count}

    return lanes_dict

def createVeronoiDiagram(netfile, numberOfRegions, folderToVoronoiImage):
    #print("beginningCreate")
    # Carregar o arquivo XML
    tree = ET.parse(netfile)
    root = tree.getroot()
    regions = list()
    # Coordenadas do mapa
    conv_boundary = root.find(".//location").attrib["convBoundary"]
    print(f"CONV BOUNDARY: {conv_boundary}")
    conv_boundary = list(map(float, conv_boundary.split(',')))

    # Número desejado de células Voronoi
    num_cells = int(numberOfRegions)  # Substitua pelo número desejado

    # Sortear pontos aleatórios dentro das delimitações do mapa
    print(f"PRINTING VALUES: {[conv_boundary[0], conv_boundary[1]], [conv_boundary[2], conv_boundary[3]]}")
    random_points = np.random.uniform([conv_boundary[0], conv_boundary[1]], [conv_boundary[2], conv_boundary[3]], size=(num_cells, 2))
    #print ("random: ", random_points)
    # Criar o Diagrama de Voronoi
    vor = Voronoi(random_points)
    # Visualizar o Diagrama de Voronoi
    #fig, ax = plt.subplots()
    voronoi_plot_2d(vor, line_colors='k',line_style='--', show_vertices='False')
    # Adicionar rótulos para cada ponto com o número da região
    for point, region_index in zip(random_points, vor.point_region):
        plt.text(point[0], point[1], f'Região {region_index}', color='red', ha='center', va='center')
        regions.append(region_index)

    plt.savefig("../output/"+folderToVoronoiImage + "/"+str(numberOfRegions)+"regions.png")

    return vor, regions

def setRegionFlags(regions): #quais lanes estão localizadas em cada quadrante
    regionFlags = {}
    for region in regions:
        regionFlags[region] = {'isFull': False}
    return regionFlags

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

def findRegion(lane, vor):
    #for i in lane: #só vai receber uma lane, o for vai executar uma vez, e ele só existe 
    coords = lane['coords']

    #print("lane: ", lane)
    regions = set()
    for coord in coords:
        strCoord = coord.split(' ')
        specific_coordinates = np.array([float(strCoord[0]), float(strCoord[1])]) 
        # Encontrar a região de Voronoi associada às coordenadas específicas
        region_index = vor.point_region[np.argmin(np.linalg.norm(vor.points - specific_coordinates, axis=1))]
        regions.add(region_index)
    return regions

def findCSinRegions(numberOfRegions, folderToVoronoiImage):

    mostVisitedLanes = getMostVisitedLanes("../input/mostVisited.xml")
    vor, regions = createVeronoiDiagram("../input/cologne.net.xml" ,numberOfRegions, folderToVoronoiImage)
    #print("regions: ", regions)
    regionFlags = setRegionFlags(regions)
    #print ("regionFlags: ", regionFlags)
    lanesAndCoords = getLanesAndCoordinates("../input/cologne.net.xml")

    chargingPoints = set()
    regionsFull = 0
    lanesUsed = {}
  
    for lane_id, lane_info in mostVisitedLanes.items():
        if regionsFull >= int(numberOfRegions):
            break
         
        regionsFound = findRegion(lanesAndCoords[lane_id], vor)
        
        for i in regionsFound:

            if (regionFlags[i]['isFull'] == False) and (lane_id not in chargingPoints):
                regionFlags[i]['isFull'] = True
                chargingPoints.add(lane_id)
                regionsFull+=1
                lanesUsed[lane_id] = lanesAndCoords[lane_id]
                break

    if len(chargingPoints) < int(numberOfRegions):
        with open("../output/"+folderToVoronoiImage+'/FLAGARCHIVE-'+str(numberOfRegions)+'regions.txt', 'w') as arquivo:
            arquivo.write('não deu certo')
    else:
        with open("../output/"+folderToVoronoiImage+'/FLAGARCHIVE-'+str(numberOfRegions)+'regions.txt', 'w') as arquivo:
            arquivo.write('deu certo')

    return chargingPoints

def createSelectedCSFiles(lanes, num_quadrants, approach):
    quadrant_elem = ET.Element("cs")

    for lane_id in lanes:
        lane_elem = ET.SubElement(quadrant_elem, "lane")
        lane_elem.text = str(lane_id)

    # Criar uma string formatada com a representação indentada do XML
    xml_str = xml.dom.minidom.parseString(ET.tostring(quadrant_elem)).toprettyxml(indent="    ")

    # Gravar a string formatada no arquivo
    path = f"../output/{approach}"
    if not os.path(path):
        cmd = f"mkdir {path}"
        createdDir = "/selectedLanes/"
        os.system(cmd)
    path = path + createdDir
    file =f"{num_quadrants}chargingstations.xml"
    with open(path + file, "w", encoding="utf-8") as file_obj:
        file_obj.write(xml_str)

def main ():
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--max", dest="maxVehiclesPerCS", help="Max amount of vehicle that can recharge simoutaneously in a charging station [default: %(default)s]", metavar="NUMBER")
    parser.add_argument("-a", "--approach", dest="approach", help="Algorithm used to deploy the charging stations", metavar="STRING")
    parser.add_argument("-fd", "--folder", dest="folder", help="Path to folder", metavar="STRING")
    parser.add_argument("-cs", "--cs", dest="cs", help="Will the car reroute to a charging station or not [default: %(default)s]", metavar="COMMAND")
    parser.add_argument("-f", "--fileToBeRun", dest="fileToBeRun", 
                        help="Number of the SUMO files that will be run [default: %(default)s]", metavar="NUMBER")
        
    args = parser.parse_args()
    pathToVoronoiStations = "../output/greedyvoronoi/voronoiStations"
    if not os.path.exists(pathToVoronoiStations):
        cmd = "mkdir ../output/greedyvoronoi/voronoiStations"
        os.system(cmd)

    validStations = findCSinRegions(args.cs, pathToVoronoiStations)
    functions.createSelectedCSFiles(validStations, args.fileToBeRun, args.folder)

 

# this is the main entry point of this script
if __name__ == "__main__": 
    main()

