"""
metricas_por_grupo.py

Calcula, para TODAS as simulações já rodadas, as métricas de tráfego
separadas em três grupos:

    - eletricos:     veículos sorteados para recarregar (sortedCars)
    - nao_eletricos: todos os outros
    - geral:         todos os veículos juntos

A fonte é o tripinfo de cada simulação (uma linha por veículo), e não o
resumo do log do SUMO, que só traz a média geral.

Métricas por grupo (médias por veículo):
    duration             tempo de viagem, da saída à chegada (s); nos
                         elétricos inclui o tempo parado na estação
    duration_sem_parada  duration - stopTime (s): tempo de viagem sem a recarga
    route_length         distância percorrida (m)
    waiting_time         tempo parado ou quase parado no trânsito (s); NÃO
                         inclui a parada programada, mas inclui a espera na
                         fila da estação
    time_loss            tempo perdido em relação à velocidade ideal (s);
                         também não inclui a parada programada
    depart_delay         atraso para entrar na via (s)
    stop_time            tempo parado em paradas programadas (s) -- soma recarga
                         E espera na fila (as duas são paradas)
    recarga_s            tempo na parkingArea (s), do stop-output
    espera_fila_s        tempo nas paradas de espera da fila (s), do stop-output
    espera_total_s       waiting_time + espera_fila_s (s)
    duration_sem_recarga duration - recarga_s (s)
(recarga_s/espera_fila_s exigem o <rep>stops<pct>percentual<cs>cs.xml gerado
por --stop-output; sem ele, toda parada conta como recarga.)
e, só para os elétricos:
    pct_recarga_completa % dos elétricos com recarga_s >= minutos * 60

Só usa a biblioteca padrão do Python.

Uso (a partir da raiz do repositório):
    python3 metricas_por_grupo.py
    python3 metricas_por_grupo.py --output-dir output --approach random genetic

Gera:
    metricas_por_grupo.csv           uma linha por simulação
    metricas_por_grupo_resumo.txt    médias por abordagem (e por parâmetro)
"""
import argparse
import csv
import re
import statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

APPROACHES = ["random", "pseudorandom", "greedy", "greedyvoronoi", "genetic", "geneticpure"]
GRUPOS = ["eletricos", "nao_eletricos", "geral"]
METRICAS = ["duration", "duration_sem_parada", "route_length", "waiting_time",
            "time_loss", "depart_delay", "stop_time",
            "recarga_s", "espera_fila_s", "espera_total_s", "duration_sem_recarga"]
ATRIBUTOS = {"duration": "duration", "route_length": "routeLength",
             "waiting_time": "waitingTime", "time_loss": "timeLoss",
             "depart_delay": "departDelay", "stop_time": "stopTime"}
DIR_RE = re.compile(r"^(\d+)percentage(\d+)cs$")
TRIP_ID_RE = re.compile(r'<trip id="([^"]+)"')


def ler_paradas(arquivo: Path) -> dict[str, tuple[float, float]]:
    """stop-output -> {veículo: (tempo na parkingArea, tempo em outras paradas)}.
    A parada na parkingArea é a recarga; as outras são a espera na fila
    (paradas dadas pelo stuck_monitor antes das vagas)."""
    acc = defaultdict(lambda: [0.0, 0.0])
    for st in ET.parse(arquivo).getroot().iter("stopinfo"):
        dur = float(st.get("ended")) - float(st.get("started"))
        acc[st.get("id")][0 if st.get("parkingArea") else 1] += dur
    return {k: (a, b) for k, (a, b) in acc.items()}


def ler_tripinfo(arquivo: Path, paradas: dict | None = None) -> dict[str, dict[str, float]]:
    raiz = ET.parse(arquivo).getroot()
    dados = {}
    for t in raiz.iter("tripinfo"):
        v = {nome: float(t.get(attr, "0")) for nome, attr in ATRIBUTOS.items()}
        v["duration_sem_parada"] = v["duration"] - v["stop_time"]
        if paradas is not None:
            recarga, fila = paradas.get(t.get("id"), (0.0, 0.0))
        else:  # simulações antigas, sem stop-output: tudo conta como recarga
            recarga, fila = v["stop_time"], 0.0
        v["recarga_s"] = recarga
        v["espera_fila_s"] = fila
        # waitingTime do SUMO não conta tempo em paradas; a espera na fila
        # agora é uma parada (stuck_monitor), então soma as duas
        v["espera_total_s"] = v["waiting_time"] + fila
        v["duration_sem_recarga"] = v["duration"] - recarga
        dados[t.get("id")] = v
    return dados


def concluida(pasta: Path, rep: int, minutos: int) -> bool:
    """True se o REPORT da repetição diz 'FIM DA SIMULAÇÃO'. Uma simulação
    abortada (impasse, limite de tempo) ou ainda rodando pode ter tripinfo
    parcial, que entraria nas médias só com os veículos que chegaram."""
    for r in (pasta / "reports").glob(f"REPORT-{rep}file-{minutos}time-*"):
        if r.name.endswith(".impasse.txt"):
            continue
        if "FIM DA SIMULAÇÃO" in r.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def medias(valores: list[dict[str, float]]) -> dict[str, float]:
    if not valores:
        return {m: float("nan") for m in METRICAS}
    return {m: statistics.fmean(v[m] for v in valores) for m in METRICAS}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", default="output")
    ap.add_argument("--vehicles", type=int, default=8000)
    ap.add_argument("--approach", nargs="+", default=APPROACHES)
    ap.add_argument("--percentuais", nargs="+", type=int, default=None,
                    help="só esses percentuais (ex.: 1 5 10 20 30)")
    ap.add_argument("--repeticoes", nargs="+", type=int, default=list(range(1, 11)),
                    help="repetições a ler (default 1..10; as que não existem são ignoradas)")
    ap.add_argument("--incluir-incompletos", action="store_true",
                    help="inclui simulações sem 'FIM DA SIMULAÇÃO' no REPORT "
                         "(falhas, impasses, ainda rodando) -- por padrão ficam de fora")
    args = ap.parse_args()

    base = Path(args.output_dir)
    linhas, problemas = [], []

    for approach in args.approach:
        pasta_ap = base / approach
        if not pasta_ap.is_dir():
            print(f"[{approach}] pasta não encontrada, pulando")
            continue
        for pasta_min in sorted(pasta_ap.glob("*min")):
            minutos = int(pasta_min.name.removesuffix("min"))
            for pasta in sorted(pasta_min.iterdir()):
                m = DIR_RE.match(pasta.name)
                if not m:
                    continue
                pct, cs = int(m.group(1)), int(m.group(2))
                if args.percentuais and pct not in args.percentuais:
                    continue
                for rep in args.repeticoes:
                    f_sorted = pasta / f"sortedCars-{args.vehicles}" / f"sortedCars{rep}.xml"
                    f_trip = pasta / f"{rep}simulation{pct}percentual{cs}cs.xml"
                    ident = f"{approach}_{minutos}min_{cs}cs_{pct}pct_{rep}rep"
                    if not f_sorted.exists() or not f_trip.exists():
                        problemas.append(f"{ident}: arquivo ausente")
                        continue
                    if not args.incluir_incompletos and not concluida(pasta, rep, minutos):
                        problemas.append(f"{ident}: sem 'FIM DA SIMULAÇÃO' (falhou ou ainda rodando)")
                        continue
                    if "git-lfs" in f_trip.read_text(errors="ignore")[:200]:
                        problemas.append(f"{ident}: tripinfo é ponteiro do Git LFS")
                        continue
                    try:
                        eletricos = set(TRIP_ID_RE.findall(f_sorted.read_text(errors="ignore")))
                        f_stops = pasta / f"{rep}stops{pct}percentual{cs}cs.xml"
                        paradas = ler_paradas(f_stops) if f_stops.exists() else None
                        trips = ler_tripinfo(f_trip, paradas)
                    except ET.ParseError as e:
                        problemas.append(f"{ident}: tripinfo ilegível ({e})")
                        continue
                    grupo_ev = [v for k, v in trips.items() if k in eletricos]
                    grupo_comum = [v for k, v in trips.items() if k not in eletricos]
                    alvo = minutos * 60
                    linha = {
                        "abordagem": approach, "minutos": minutos, "percentual": pct,
                        "estacoes": cs, "repeticao": rep,
                        "n_eletricos": len(grupo_ev), "n_nao_eletricos": len(grupo_comum),
                        "eletricos_sem_tripinfo": len(eletricos - trips.keys()),
                        "tem_stop_output": paradas is not None,
                        "pct_recarga_completa": round(
                            100 * sum(1 for v in grupo_ev if v["recarga_s"] >= alvo) / len(grupo_ev), 2
                        ) if grupo_ev else float("nan"),
                    }
                    for nome, grupo in [("eletricos", grupo_ev), ("nao_eletricos", grupo_comum),
                                        ("geral", grupo_ev + grupo_comum)]:
                        for met, val in medias(grupo).items():
                            linha[f"{nome}_{met}"] = round(val, 2)
                    linhas.append(linha)
            n = sum(1 for l in linhas if l["abordagem"] == approach)
            print(f"[{approach}] {n} simulações lidas")

    if not linhas:
        print("Nenhuma simulação lida.")
        return

    with open("metricas_por_grupo.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)

    # ---------------- resumo ----------------
    principais = ["espera_total_s", "time_loss", "duration_sem_recarga", "route_length"]

    def bloco(chave, titulo):
        acc = defaultdict(list)
        for l in linhas:
            acc[chave(l)].append(l)
        out = [f"== {titulo} =="]
        for k in sorted(acc):
            ls = acc[k]
            rotulo = " | ".join(str(x) for x in (k if isinstance(k, tuple) else (k,)))
            rec = statistics.fmean(l["pct_recarga_completa"] for l in ls)
            out.append(f"  {rotulo}  (n={len(ls)}, recarga completa {rec:.1f}%)")
            for g in GRUPOS:
                partes = [f"{met}={statistics.fmean(l[f'{g}_{met}'] for l in ls):.1f}"
                          for met in principais]
                out.append(f"      {g:<14} " + "  ".join(partes))
        return out

    out = ["Métricas por grupo (médias por veículo, depois média entre simulações)",
           "espera_total_s (no trânsito + na fila), time_loss e duration_sem_recarga em s; route_length em m", ""]
    out += bloco(lambda l: l["abordagem"], "Por abordagem")
    for nome, campo in [("percentual de elétricos", "percentual"), ("nº de estações", "estacoes"),
                        ("tempo de recarga (min)", "minutos")]:
        out.append("")
        out += bloco(lambda l, c=campo: (l["abordagem"], l[c]), f"Por abordagem e {nome}")
    if problemas:
        out += ["", f"== Problemas ({len(problemas)}) =="] + ["  " + p for p in problemas[:50]]
    texto = "\n".join(out)
    Path("metricas_por_grupo_resumo.txt").write_text(texto + "\n")
    print()
    print("\n".join(out[: 3 + 4 * len({l['abordagem'] for l in linhas}) + 2]))
    print("... (resumo completo em metricas_por_grupo_resumo.txt)")


if __name__ == "__main__":
    main()
