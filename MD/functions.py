import traci
import argparse
import random
import os
import xml.etree.ElementTree as ET
import xml

def createExperimentFolder(args):
    path = f"../output/{args.approach}/"
    newFolder = str(args.percentage) + "percentage" + str(args.csAmount) + "cs" 
    if not os.path.exists(newFolder):
        os.system("mkdir " + path + newFolder)
        os.system ("mkdir "+ path + newFolder + "/selectedLanes")
        os.system ("mkdir "+ path + newFolder + f"/sortedCars-{args.vehicles}")
    return path + newFolder

def createReportsFolder(folder):
    if not os.path.exists(folder+"/reports"):
        os.system(f"cd {folder} && mkdir reports")
  

def sortearCarrosPorPercentual(percentage, numberFile, amountOfCars, folder):
    filename = "../input/cologne6to8.trips.xml"
    # Abre o arquivo original para leitura
    quantidade = int((float(percentage)/100) * int(amountOfCars))
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
        nome_arquivo_sorteadas = f"{folder}/sortedCars-{amountOfCars}/sortedCars{str(numberFile)}.xml"
        with open(nome_arquivo_sorteadas, 'w', encoding='utf-8') as file_sorteadas:
            file_sorteadas.write('\n'.join(linhas_sorteadas))

        # Cria um novo arquivo que é uma cópia do arquivo original, mas sem as linhas sorteadas
        nome_arquivo_sem_sorteadas = f"{folder}/cologne6to8-{str(numberFile)}.trips.xml"
        linhas_sem_sorteadas = [linha for linha in linhas if linha.strip() not in linhas_sorteadas]
        with open(nome_arquivo_sem_sorteadas, 'w', encoding='utf-8') as file_sem_sorteadas:
            file_sem_sorteadas.write(''.join(linhas_sem_sorteadas))

def makeCfgs(args, folder):
    #amountOfCars = 179259
    
    inputFolder = "../../../input/"
    outputName = inputFolder + "cologne.net.xml"
    actualFile = f"cologne{args.fileToBeRun}.sumo.cfg"
    
    f = open(folder + "/"+ actualFile, "w")
    line = '<?xml version="1.0" encoding="UTF-8"?>\n'
    f.write(line)
    line = '<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">\n'
    f.write(line)
    line = "\t<input>\n"
    f.write(line)
    line = "\t\t<net-file value=\"" + outputName + "\"/>\n"
    f.write(line)
    line = "\t\t<route-files value=\""+ "cologne6to8-"+str(args.fileToBeRun)+".trips.xml" "\"/>\n"
    f.write(line)
    line = "\t\t<additional-files value=\"" + "cologne"+ str(args.fileToBeRun)+".add.xml\"" + "/>\n"
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

#for voronoi and greedy until now
def extract_lanes_from_xml(xml_file):
    lanes = set()
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for lane in root.findall('.//lane'):
            lanes.add(lane.text)
    except ET.ParseError:
        print("Erro ao analisar o arquivo XML.")
  
    return lanes

#for voronoi and greedy until now
def makeAdds(args, folder):
    if args.csAmount != 0:
        stationPoints = extract_lanes_from_xml(str(folder + f"/selectedLanes/{args.fileToBeRun}chargingstations.xml"))
    outputNet = "cologne"
    add =  str(folder) + "/" + outputNet + str(args.fileToBeRun) + ".add.xml"
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

def createSelectedCSFiles(lanes, file, folder):
    print("vai CRIAR")
    quadrant_elem = ET.Element("cs")

    for lane_id in lanes:
        lane_elem = ET.SubElement(quadrant_elem, "lane")
        lane_elem.text = str(lane_id)

    # Criar uma string formatada com a representação indentada do XML
    xml_str = xml.dom.minidom.parseString(ET.tostring(quadrant_elem)).toprettyxml(indent="    ")

    # Gravar a string formatada no arquivo
    path = folder
    createdDir = "/selectedLanes/"
    if not os.path.exists(path + createdDir):
        cmd = f"mkdir {path}{createdDir}"
        os.system(cmd)
    path = path + createdDir
    file =f"{file}chargingstations.xml"
    with open(path + file, "w", encoding="utf-8") as file_obj:
        file_obj.write(xml_str)

