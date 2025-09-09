import psutil
import argparse
import subprocess
import os

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-a", "--approaches", dest="approaches")
    parser.add_argument("-v", "--amountOfVehicles", dest="amountOfVehicles")
    arg = parser.parse_args()



    cmd = f"cd MD && python3 main.py -t 60 -f 1 -p 30 -a random -v 2000 -cs 49> 49stations-5percentage-5min.log 2>&1"
                    
            

    os.system(cmd)
if __name__ == "__main__":
    main()