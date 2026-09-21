#!/usr/bin/env python3
"""
scan_all_capacities.py

Varre TODOS os .add.xml já gerados (output/<approach>/<minutes>min/
<percentage>percentage<cs>cs/cologne<repetition>.add.xml), de TODOS os
approaches presentes, e reporta o roadsideCapacity de cada estação --
separando jobs que JÁ TERMINARAM (têm REPORT-... em reports/) dos que
ainda estão RODANDO/INCOMPLETOS (add.xml existe, mas REPORT- não).

Objetivo: checar empiricamente se estações de capacidade muito baixa
aparecem só no pseudorandom (e só nos jobs que travaram) ou se os outros
approaches também geram esse tipo de estação sem que isso tenha causado
problema -- evidência concreta pra decisão metodológica sobre o filtro.

Uso (a partir de ~/TCC):
    python3 scan_all_capacities.py
    python3 scan_all_capacities.py --threshold 6
    python3 scan_all_capacities.py --approach pseudorandom
"""
import argparse
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict

OUTPUT_DIR = Path("output")


def find_combo_dirs(approach_dir: Path):
    # output/<approach>/<minutes>min/<percentage>percentage<cs>cs/
    for minutes_dir in sorted(approach_dir.glob("*min")):
        if not minutes_dir.is_dir():
            continue
        for combo_dir in sorted(minutes_dir.glob("*percentage*cs")):
            if combo_dir.is_dir():
                yield combo_dir


def parse_combo_name(combo_dir: Path, minutes_dir: Path):
    m = re.match(r"(\d+)percentage(\d+)cs", combo_dir.name)
    minutes = re.match(r"(\d+)min", minutes_dir.name)
    if not m or not minutes:
        return None
    return {
        "minutes": int(minutes.group(1)),
        "percentage": int(m.group(1)),
        "cs_amount": int(m.group(2)),
    }


def is_completed(combo_dir: Path, repetition: int) -> bool:
    reports_dir = combo_dir / "reports"
    if not reports_dir.is_dir():
        return False
    prefix = f"REPORT-{repetition}file-"
    return any(p.name.startswith(prefix) for p in reports_dir.iterdir())


def capacities_in_addfile(addfile: Path):
    caps = []
    try:
        root = ET.parse(addfile).getroot()
    except ET.ParseError:
        return None  # arquivo truncado/corrompido (job pode estar sendo escrito agora)
    for pa in root.findall(".//parkingArea"):
        cap = pa.get("roadsideCapacity")
        if cap is not None:
            caps.append(int(cap))
    return caps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=int, default=6,
                     help="capacidade mínima considerada 'ok' (default: 6, "
                          "igual ao DEFAULT_MAX_VEHICLES_PER_CS do projeto)")
    ap.add_argument("--approach", default=None,
                     help="restringe a um approach só (default: todos os "
                          "encontrados em output/)")
    args = ap.parse_args()

    approaches = (
        [args.approach] if args.approach
        else sorted(d.name for d in OUTPUT_DIR.iterdir()
                    if d.is_dir() and any(d.glob("*min")))
    )

    # summary[approach][status] = list of min-capacity values (um por job)
    summary = defaultdict(lambda: defaultdict(list))
    # flagged: jobs com alguma estação abaixo do threshold
    flagged = []
    n_jobs_total = 0
    n_addfiles_unreadable = 0

    for approach in approaches:
        approach_dir = OUTPUT_DIR / approach
        if not approach_dir.is_dir():
            print(f"(aviso: output/{approach} não existe, pulando)")
            continue

        for minutes_dir in sorted(approach_dir.glob("*min")):
            for combo_dir in sorted(minutes_dir.glob("*percentage*cs")):
                info = parse_combo_name(combo_dir, minutes_dir)
                if info is None:
                    continue
                for addfile in sorted(combo_dir.glob("cologne*.add.xml")):
                    rep_match = re.match(r"cologne(\d+)\.add\.xml", addfile.name)
                    if not rep_match:
                        continue
                    repetition = int(rep_match.group(1))
                    n_jobs_total += 1

                    caps = capacities_in_addfile(addfile)
                    if caps is None:
                        n_addfiles_unreadable += 1
                        continue
                    if not caps:
                        continue

                    status = "completo" if is_completed(combo_dir, repetition) else "rodando/incompleto"
                    min_cap = min(caps)
                    summary[approach][status].append(min_cap)

                    if min_cap < args.threshold:
                        flagged.append({
                            "approach": approach,
                            "status": status,
                            "minutes": info["minutes"],
                            "percentage": info["percentage"],
                            "cs_amount": info["cs_amount"],
                            "repetition": repetition,
                            "min_cap": min_cap,
                            "n_below": sum(1 for c in caps if c < args.threshold),
                            "n_total": len(caps),
                            "path": str(addfile),
                        })

    print(f"Jobs escaneados: {n_jobs_total} (limiar: capacidade >= {args.threshold})")
    if n_addfiles_unreadable:
        print(f"(aviso: {n_addfiles_unreadable} .add.xml não puderam ser lidos -- "
              f"provavelmente sendo escritos agora por um job em andamento)")
    print()

    print("=" * 78)
    print("RESUMO POR APPROACH / STATUS (capacidade mínima entre os jobs)")
    print("=" * 78)
    header = f"{'approach':<16}{'status':<20}{'n_jobs':<8}{'min':<6}{'média':<8}{'máx':<6}{'abaixo_limiar':<14}"
    print(header)
    print("-" * len(header))
    for approach in sorted(summary):
        for status in sorted(summary[approach]):
            vals = summary[approach][status]
            n_abaixo = sum(1 for v in vals if v < args.threshold)
            print(f"{approach:<16}{status:<20}{len(vals):<8}{min(vals):<6}"
                  f"{sum(vals)/len(vals):<8.1f}{max(vals):<6}{n_abaixo:<14}")
    print()

    if flagged:
        print("=" * 78)
        print(f"JOBS COM ALGUMA ESTAÇÃO ABAIXO DO LIMIAR ({args.threshold}):")
        print("=" * 78)
        flagged.sort(key=lambda f: f["min_cap"])
        for f in flagged:
            print(f"  [{f['status']:<19}] {f['approach']:<14} "
                  f"{f['minutes']}min/{f['percentage']}pct/{f['cs_amount']}cs "
                  f"rep{f['repetition']} -- min_cap={f['min_cap']} "
                  f"({f['n_below']}/{f['n_total']} estações abaixo)")
    else:
        print(f"Nenhum job com estação abaixo de {args.threshold} veículos de capacidade.")


if __name__ == "__main__":
    main()
