"""Por que alguns elétricos não completam a recarga?

Rode da raiz do repositório:

    python3 causas_sem_recarga.py

Para cada elétrico sem recarga completa, olha o tripinfo e o stop-output e
o põe numa destas categorias:
  - removido no meio da viagem: o monitor o tirou da simulação antes do
    destino (tripinfo com vaporized="0"; regras de destravamento);
  - chegou sem recarregar: terminou a viagem sem nenhuma parada na estação;
  - recarga parcial: parou na estação, mas menos que o tempo de recarga.
Para os removidos, diz também se já tinham esperado na fila.

Imprime um resumo por abordagem, por número de estações e por percentual,
e grava causas_sem_recarga.csv (uma linha por simulação).
"""
import csv
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ABORDAGENS = ["random", "pseudorandom", "greedy", "greedyvoronoi", "genetic"]
DIR_RE = re.compile(r"^(\d+)percentage(\d+)cs$")
TRIP_ID_RE = re.compile(r'<trip id="([^"]+)"')
CATS = ["removido", "chegou_sem_recarregar", "recarga_parcial"]

linhas = []
for ap in ABORDAGENS:
    for pasta_min in sorted(Path("output", ap).glob("*min")):
        minutos = int(pasta_min.name.removesuffix("min"))
        for pasta in sorted(pasta_min.iterdir()):
            m = DIR_RE.match(pasta.name)
            if not m:
                continue
            pct, cs = int(m.group(1)), int(m.group(2))
            for rep in range(1, 6):
                f_sorted = pasta / "sortedCars-8000" / f"sortedCars{rep}.xml"
                f_trip = pasta / f"{rep}simulation{pct}percentual{cs}cs.xml"
                f_stops = pasta / f"{rep}stops{pct}percentual{cs}cs.xml"
                if not (f_sorted.exists() and f_trip.exists() and f_stops.exists()):
                    continue
                evs = set(TRIP_ID_RE.findall(f_sorted.read_text(errors="ignore")))
                recarga, fila = defaultdict(float), defaultdict(float)
                for st in ET.parse(f_stops).getroot().iter("stopinfo"):
                    d = float(st.get("ended")) - float(st.get("started"))
                    (recarga if st.get("parkingArea") else fila)[st.get("id")] += d
                cont = dict.fromkeys(CATS, 0)
                removido_com_fila = 0
                alvo = minutos * 60
                for t in ET.parse(f_trip).getroot().iter("tripinfo"):
                    v = t.get("id")
                    if v not in evs or recarga[v] >= alvo:
                        continue
                    if t.get("vaporized") == "0":
                        cont["removido"] += 1
                        removido_com_fila += fila[v] > 0
                    elif recarga[v] == 0:
                        cont["chegou_sem_recarregar"] += 1
                    else:
                        cont["recarga_parcial"] += 1
                linhas.append({"abordagem": ap, "minutos": minutos, "estacoes": cs, "percentual": pct,
                               "repeticao": rep, "eletricos": len(evs),
                               "sem_recarga": sum(cont.values()), **cont,
                               "removido_depois_de_esperar_na_fila": removido_com_fila})
    print(f"[{ap}] {sum(l['abordagem'] == ap for l in linhas)} simulações lidas", flush=True)

with open("causas_sem_recarga.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(linhas[0]))
    w.writeheader()
    w.writerows(linhas)


def tabela(titulo, chave, valores):
    print(f"\n=== {titulo} ===")
    print(f"{'':14s} {'elétricos':>10s} {'sem rec.':>9s} {'%':>6s} {'removidos':>10s} "
          f"{'chegou s/':>10s} {'parcial':>8s} {'remov. após fila':>17s}")
    for val in valores:
        ls = [l for l in linhas if l[chave] == val]
        if not ls:
            continue
        ev = sum(l["eletricos"] for l in ls)
        sem = sum(l["sem_recarga"] for l in ls)
        print(f"{str(val):14s} {ev:10d} {sem:9d} {100 * sem / ev:6.2f} "
              f"{sum(l['removido'] for l in ls):10d} {sum(l['chegou_sem_recarregar'] for l in ls):10d} "
              f"{sum(l['recarga_parcial'] for l in ls):8d} "
              f"{sum(l['removido_depois_de_esperar_na_fila'] for l in ls):17d}")


tabela("Por abordagem", "abordagem", ABORDAGENS)
tabela("Por número de estações", "estacoes", [9, 16, 25, 36, 49])
tabela("Por percentual que recarrega", "percentual", [1, 3, 5, 7, 9])
tabela("Por tempo de recarga (min)", "minutos", [10, 20, 40, 60])

total = sum(l["sem_recarga"] for l in linhas)
pior = sorted(linhas, key=lambda l: -l["sem_recarga"])
acum, n = 0, 0
for l in pior:
    if acum >= total / 2:
        break
    acum += l["sem_recarga"]
    n += 1
print(f"\nConcentração: metade dos elétricos sem recarga ({acum} de {total}) está em "
      f"{n} das {len(linhas)} simulações.")
print("\nDetalhe por simulação: causas_sem_recarga.csv")
