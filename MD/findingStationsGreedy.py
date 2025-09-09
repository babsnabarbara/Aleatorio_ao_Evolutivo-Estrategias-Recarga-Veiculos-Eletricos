import networkx as nx
import xml.etree.ElementTree as ET
import random
from bs4 import BeautifulSoup
import os
import xml.dom.minidom
import argparse
import functions

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
def getLanesInEachQuadrant(file): #quais lanes estão localizadas em cada quadrant
    
    quadrantsFile = file
    tree = ET.parse (quadrantsFile)
    root = tree.getroot()

    quadrantsAndLanes = {}
    
    for quadrant in root.findall('.//quadrant'):
        lanes = list()
        x = quadrant.get('x')
        y = quadrant.get('y')
        for lane in quadrant.findall('lane'):
            lanes.append(lane.text)
        quadrantsAndLanes[(x, y)] = {'lanes': lanes}
    return quadrantsAndLanes

def setQuadrantsFlags(file): #quais lanes estão localizadas em cada quadrant
    quadrantsFile = file
    tree = ET.parse (quadrantsFile)
    root = tree.getroot()

    quadrantsFlags = {}
    
    for quadrant in root.findall('.//quadrant'):
        x = quadrant.get('x')
        y = quadrant.get('y')
        quadrantsFlags[(x, y)] = {'isFull': False}
    return quadrantsFlags

def createQuadrantCSFile(lanes, num_quadrants):
    quadrant_elem = ET.Element("quadrant")

    for lane_id in lanes:
        lane_elem = ET.SubElement(quadrant_elem, "lane")
        lane_elem.text = str(lane_id)

    # Criar uma string formatada com a representação indentada do XML
    xml_str = xml.dom.minidom.parseString(ET.tostring(quadrant_elem)).toprettyxml(indent="    ")


    # Gravar a string formatada no arquivo
    with open(f"../input/mostVisitedLanesInEachQuadrant/{num_quadrants}quadrants.xml", "w", encoding="utf-8") as file_obj:
        file_obj.write(xml_str)

def findCSInQuadrants(netfile, quadrants):
    f = open(netfile)
    f.close()


    mostVisitedLanes = getMostVisitedLanes("../input/mostVisited.xml")
    quadrantsFile = "../input/lanesInEachQuadrant/"+str(quadrants)+"quadrants.xml"
    lanesInQuadrants = getLanesInEachQuadrant(quadrantsFile)
    quadrantsFlags = setQuadrantsFlags(quadrantsFile)
    
    numberOfQuadrants= len(quadrantsFlags)
    chargingPoints = set()
    quadrantsFull = 0

    for lane_id, lane_info in mostVisitedLanes.items():
        if quadrantsFull >= numberOfQuadrants:
            break

        for key, info in lanesInQuadrants.items():
            if (lane_id not in chargingPoints) and (quadrantsFlags[key]['isFull'] == False):
                quadrantsFlags[key] = {'isFull': True}
                chargingPoints.add(lane_id)
                quadrantsFull+=1
                break
               
    
    return chargingPoints

def main ():

    parser = argparse.ArgumentParser()
    parser.add_argument("-cs", "--cs", dest="cs", help="Will the car reroute to a charging station or not [default: %(default)s]", metavar="COMMAND")
    parser.add_argument("-fd", "--folder", dest="folder", help="Folder path [default: %(default)s]", metavar="STRING")
    args = parser.parse_args()

    pathTomostVisitedLanesInEachQuadrant = "../input/mostVisitedLanesInEachQuadrant/9quadrants.xml"
    if not os.path.exists(pathTomostVisitedLanesInEachQuadrant):
        cmd = "mkdir ../input/mostVisitedLanesInEachQuadrant"
        os.system(cmd)
    
    for i in range (1, 6):
        validStations = findCSInQuadrants('../input/cologne.net.xml', args.cs)
        functions.createSelectedCSFiles(validStations, i, args.folder)
 

# this is the main entry point of this script
if __name__ == "__main__": 
    main()

