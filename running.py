import psutil
import argparse
import subprocess
import os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--approaches", dest="approaches")
    parser.add_argument("-v", "--amountOfVehicles", dest="amountOfVehicles")
    arg = parser.parse_args()


    stations = [9, 16, 25, 36, 49]
    minutes_recharging = [10, 20, 40, 60]
    approaches = arg.approaches.split()
    print (approaches)
    command_lines = []
    #currentDir = os.getcwd()
    #os.chdir(currentDir)

    for approach in approaches:
        for minutes in minutes_recharging:  
            for station in stations:
                for percentage in range(5, 31, 5):
                    for repetition in range(1,6):
                        command_lines.append(
                            #python3 main.py -t TIMEOFRC -f 1 -p PERCENTAGE -v amountOFVEHUCLES -a APPROACH
                            f"cd MD && python3 main.py -t {minutes} -f {repetition} -p {percentage} -a {approach} -v {arg.amountOfVehicles} -cs {station} > {station}stations-{percentage}percentage-{minutes}min.log 2>&1"
                        )
                
        

    currentDir = os.getcwd()
    with open('checkingUp.txt', 'a') as log_file:
        while len(command_lines):
                if psutil.cpu_percent(interval=5) < 90.0:
                    popped = command_lines.pop()
                    log_file.write(popped + '\n')
                    print(f"{popped}, \n")
                    subprocess.Popen(popped, shell=True, cwd=currentDir)
                    log_file.flush()
                else:
                     print("not")
        log_file.write('DONE')
        log_file.flush()
if __name__ == "__main__":
    main()