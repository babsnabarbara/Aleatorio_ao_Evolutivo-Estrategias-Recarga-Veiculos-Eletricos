"""Checagem da grade completa: o que rodou, o que falhou e quanto recarregou.

Rode da raiz do repositório, DEPOIS do metricas_por_grupo.py:

    python3 metricas_por_grupo.py --percentuais 1 5 10 20 30
    python3 checar_grade.py                      # grade 3: 1 5 10 20 30
    python3 checar_grade.py --percentuais 1 3 5 7 9   # grade 2

Para cada uma das 2.000 simulações esperadas (4 abordagens x 4 tempos x
5 números de estações x 5 percentuais x 5 repetições), confere:
  - se há relatório de sucesso, de falha ou nenhum;
  - se há diagnóstico de impasse (.impasse.txt);
  - se o tripinfo e o stop-output estão íntegros (8.001 veículos);
  - os contadores do monitor gravados no relatório (removidos, recuados...);
  - o % de elétricos com recarga completa (do metricas_por_grupo.csv).

Grava tudo em checagem_grade.csv (uma linha por simulação) e imprime um
resumo curto, que dá para copiar do terminal.
"""
import argparse
import csv
import glob
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

_ap = argparse.ArgumentParser()
_ap.add_argument("--percentuais", nargs="+", type=int, default=[1, 5, 10, 20, 30])
_ap.add_argument("--abordagens", nargs="+", default=["random", "pseudorandom", "greedy", "genetic"])
_ap.add_argument("--repeticoes", nargs="+", type=int, default=[1, 2, 3, 4, 5])
_args = _ap.parse_args()

ABORDAGENS = _args.abordagens
MINUTOS = [10, 20, 40, 60]
ESTACOES = [9, 16, 25, 36, 49]
PERCENTUAIS = _args.percentuais
REPETICOES = _args.repeticoes
VEICULOS = 8001
CONTADORES = ["removido_para_destravar", "removido_no_fim_da_rota", "recuado_para_destravar",
              "movido_eletrico", "movido_comum", "pulou_engarrafamento", "ajuda_troca_de_faixa",
              "passou_do_ponto_de_espera", "removido_fila_na_saida", "espera_esquecida_apagada", "parada_recolocada_apos_mover", "movido_do_autorizado_travado"]


def ler_relatorio(caminho):
    texto = open(caminho, encoding="utf-8", errors="replace").read()
    rep = re.search(r"SIMULAÇÃO \(repetição\): (\d+)", texto)
    erro = re.search(r"^erro: (.*)$", texto, re.M)
    cont = {m.group(1): int(m.group(2))
            for m in re.finditer(r"^MONITOR (\w+): (\d+)", texto, re.M)}
    if "FIM DA SIMULAÇÃO" in texto:
        status = "ok"
    elif "SIMULAÇÃO FALHOU" in texto:
        status = "falhou"
    else:
        status = "incompleto"
    return (int(rep.group(1)) if rep else None), status, (erro.group(1)[:200] if erro else ""), cont


def integro(pasta, rep):
    trips = glob.glob(f"{pasta}/{rep}simulation*.xml")
    stops = glob.glob(f"{pasta}/{rep}stops*.xml")
    if len(trips) != 1 or len(stops) != 1:
        return f"arquivos: {len(trips)} tripinfo, {len(stops)} stops"
    try:
        n = sum(1 for _, el in ET.iterparse(trips[0]) if el.tag == "tripinfo")
        ET.parse(stops[0])
    except ET.ParseError as e:
        return f"XML corrompido: {e}"
    return "" if n == VEICULOS else f"{n} tripinfo (esperado {VEICULOS})"


# % de recarga completa, do metricas_por_grupo.csv
recarga = {}
if os.path.exists("metricas_por_grupo.csv"):
    for r in csv.DictReader(open("metricas_por_grupo.csv", encoding="utf-8")):
        chave = (r["abordagem"], int(r["minutos"]), int(r["estacoes"]),
                 int(r["percentual"]), int(r["repeticao"]))
        recarga[chave] = float(r["pct_recarga_completa"])
else:
    print("AVISO: metricas_por_grupo.csv não encontrado -- rode antes: python3 metricas_por_grupo.py\n")

linhas = []
total = len(ABORDAGENS) * len(MINUTOS) * len(ESTACOES) * len(PERCENTUAIS) * len(REPETICOES)
feitas = 0
for ap in ABORDAGENS:
    for mi in MINUTOS:
        for cs in ESTACOES:
            for pct in PERCENTUAIS:
                pasta = f"output/{ap}/{mi}min/{pct}percentage{cs}cs"
                relatorios = {}
                for f in glob.glob(f"{pasta}/reports/REPORT-*"):
                    if f.endswith(".impasse.txt"):
                        continue
                    rep, status, erro, cont = ler_relatorio(f)
                    if rep is None:
                        rep = int(os.path.basename(f).split("file")[0].replace("REPORT-", ""))
                    relatorios[rep] = (f, status, erro, cont)
                for rep in REPETICOES:
                    feitas += 1
                    if feitas % 250 == 0:
                        print(f"... {feitas} de {total}", flush=True)
                    f, status, erro, cont = relatorios.get(rep, (None, "sem_relatorio", "", {}))
                    impasse = bool(f and os.path.exists(f + ".impasse.txt"))
                    problema = integro(pasta, rep) if status == "ok" else ""
                    linha = {"abordagem": ap, "minutos": mi, "estacoes": cs, "percentual": pct,
                             "repeticao": rep, "status": status, "impasse": impasse,
                             "arquivos_com_problema": problema, "erro": erro,
                             "pct_recarga_completa": recarga.get((ap, mi, cs, pct, rep), "")}
                    for c in CONTADORES:
                        linha[c] = cont.get(c, "")
                    linhas.append(linha)

with open("checagem_grade.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(linhas[0]))
    w.writeheader()
    w.writerows(linhas)

# ----------------------------------------------------------------- resumo
print("\n=== 1. Situação das simulações (esperado: 500 por abordagem) ===")
print(f"{'abordagem':14s} {'ok':>5s} {'falhou':>7s} {'sem rel.':>9s} {'impasse':>8s} {'arq.ruins':>10s}")
for ap in ABORDAGENS:
    ls = [l for l in linhas if l["abordagem"] == ap]
    c = Counter(l["status"] for l in ls)
    print(f"{ap:14s} {c['ok']:5d} {c['falhou'] + c['incompleto']:7d} {c['sem_relatorio']:9d} "
          f"{sum(l['impasse'] for l in ls):8d} {sum(bool(l['arquivos_com_problema']) for l in ls):10d}")

ruins = [l for l in linhas if l["status"] != "ok" or l["arquivos_com_problema"]]
if ruins:
    print(f"\n=== 2. Simulações com problema ({len(ruins)}) ===")
    for l in ruins[:40]:
        print(f"  {l['abordagem']} {l['minutos']}min {l['estacoes']}cs {l['percentual']}% rep{l['repeticao']}: "
              f"{l['status']}{' IMPASSE' if l['impasse'] else ''} "
              f"{l['arquivos_com_problema'] or l['erro'][:120]}")
    if len(ruins) > 40:
        print(f"  ... e mais {len(ruins) - 40} (ver checagem_grade.csv)")
else:
    print("\n=== 2. Nenhuma simulação com problema ===")

print("\n=== 3. Recarga completa por abordagem (% dos elétricos, por simulação) ===")
print(f"{'abordagem':14s} {'média':>6s} {'mín':>6s} {'100%':>6s} {'>=99%':>6s} {'95-99%':>7s} {'<95%':>5s} {'<80%':>5s}")
for ap in ABORDAGENS:
    v = [l["pct_recarga_completa"] for l in linhas
         if l["abordagem"] == ap and l["status"] == "ok" and l["pct_recarga_completa"] != ""]
    if not v:
        print(f"{ap:14s} sem dados")
        continue
    print(f"{ap:14s} {sum(v) / len(v):6.1f} {min(v):6.1f} {sum(x == 100 for x in v):6d} "
          f"{sum(x >= 99 for x in v):6d} {sum(95 <= x < 99 for x in v):7d} "
          f"{sum(x < 95 for x in v):5d} {sum(x < 80 for x in v):5d}")

print("\n=== 4. Recarga completa média por abordagem e tempo de recarga (%) ===")
print(f"{'abordagem':14s}" + "".join(f"{m:>8d}min" for m in MINUTOS))
for ap in ABORDAGENS:
    vals = []
    for m in MINUTOS:
        v = [l["pct_recarga_completa"] for l in linhas if l["abordagem"] == ap and l["minutos"] == m
             and l["status"] == "ok" and l["pct_recarga_completa"] != ""]
        vals.append(f"{sum(v) / len(v):11.1f}" if v else f"{'-':>11s}")
    print(f"{ap:14s}" + "".join(vals))

print("\n=== 5. Intervenção do monitor (soma em todas as simulações da abordagem) ===")
print(f"{'abordagem':14s}" + "".join(f"{c[:12]:>13s}" for c in CONTADORES))
for ap in ABORDAGENS:
    s = defaultdict(int)
    for l in linhas:
        if l["abordagem"] == ap:
            for c in CONTADORES:
                if l[c] != "":
                    s[c] += l[c]
    print(f"{ap:14s}" + "".join(f"{s[c]:13d}" for c in CONTADORES))

piores = sorted((l for l in linhas if l["pct_recarga_completa"] != ""),
                key=lambda l: l["pct_recarga_completa"])[:15]
print("\n=== 6. As 15 simulações com menor recarga completa ===")
for l in piores:
    print(f"  {l['pct_recarga_completa']:6.2f}%  {l['abordagem']} {l['minutos']}min {l['estacoes']}cs "
          f"{l['percentual']}% rep{l['repeticao']}  removidos={l['removido_para_destravar']}")

print("\nDetalhe por simulação: checagem_grade.csv")
