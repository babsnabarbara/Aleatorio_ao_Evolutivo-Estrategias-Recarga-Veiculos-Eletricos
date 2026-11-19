"""Confere se os resultados das simulações concluídas estão íntegros.

Para cada simulação com relatório de sucesso ("FIM DA SIMULAÇÃO"), abre o
tripinfo e o stop-output, verifica que os XML estão completos e que o
tripinfo tem todos os veículos. Rode da raiz do repositório:

    python3 validar_resultados.py
"""
import glob
import os
import sys
import xml.etree.ElementTree as ET

ESPERADO = 8001  # veículos por simulação (elétricos + não elétricos)

relatorios = [r for r in glob.glob("output/*/*min/*/reports/REPORT-*")
              if not r.endswith(".impasse.txt")]
if not relatorios:
    sys.exit("Nenhum relatório encontrado -- rode da raiz do repositório.")

ok = 0
problemas = []
for i, rep in enumerate(relatorios, 1):
    if i % 100 == 0:
        print(f"... {i} de {len(relatorios)} relatórios", flush=True)
    if "FIM DA SIMULAÇÃO" not in open(rep, encoding="utf-8", errors="replace").read():
        continue
    pasta = os.path.dirname(os.path.dirname(rep))
    r = os.path.basename(rep).split("file")[0].replace("REPORT-", "")
    trips = glob.glob(f"{pasta}/{r}simulation*.xml")
    stops = glob.glob(f"{pasta}/{r}stops*.xml")
    erro = None
    try:
        if len(trips) != 1 or len(stops) != 1:
            erro = f"arquivos: {len(trips)} tripinfo, {len(stops)} stops"
        else:
            n = sum(1 for _, el in ET.iterparse(trips[0]) if el.tag == "tripinfo")
            ET.parse(stops[0])
            if n != ESPERADO:
                erro = f"{n} tripinfo (esperado {ESPERADO})"
    except ET.ParseError as e:
        erro = f"XML corrompido: {e}"
    if erro:
        problemas.append(f"{pasta.split('output/')[1]} rep{r}: {erro}")
    else:
        ok += 1

print(f"\níntegros: {ok} | com problema: {len(problemas)}")
for p in problemas[:40]:
    print("  ", p)
with open("validacao_resultados.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(problemas) + "\n")
