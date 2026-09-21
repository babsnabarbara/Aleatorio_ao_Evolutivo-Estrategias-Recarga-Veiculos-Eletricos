"""
compare_progress.py -- vive na RAIZ de TCC/ (não em MD/).

Compara o desempenho (stat_duration -- tempo médio de viagem, a métrica
principal) entre dois approaches, usando os CSVs já gerados por
analysis_report.py. Pensado especificamente pra comparar um approach que
ainda está rodando (dado parcial, tipo o pseudorandom no meio do batch)
contra outro já completo (tipo o random) -- só compara as combinações
(minutes, cs_amount, percentage, repetition) que já existem nos DOIS
lados, pra não comparar coisa incompleta com completa injustamente.

Uso (de dentro de TCC/):

    # 1. gera/atualiza o CSV do approach que está rodando, com o que já saiu até agora
    python3 MD/analysis_report.py --approach pseudorandom

    # 2. compara com outro approach -- se os CSVs dele já estiverem em
    #    output/analysis/<approach>/, não precisa de mais nada:
    python3 compare_progress.py --a pseudorandom --b random

    # se os CSVs do outro approach vieram de outra máquina (ex: um .zip
    # baixado e extraído aqui), aponta o caminho manualmente:
    python3 compare_progress.py --a pseudorandom --b random --b-dir ./random_reference/random
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

TCC_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TCC_ROOT / "MD"))

import config  # noqa: E402


def _load_approach_csvs(approach: str, override_dir: Path | None) -> list[dict]:
    directory = override_dir if override_dir else (config.OUTPUT_DIR / "analysis" / approach)
    if not directory.exists():
        print(f"AVISO: '{directory}' não existe -- 0 linhas carregadas para '{approach}'.")
        return []

    rows: list[dict] = []
    for csv_path in sorted(directory.glob("*min.csv")):
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            rows.extend(reader)
    return rows


def _key(row: dict) -> tuple:
    return (row["minutes"], row["cs_amount"], row["percentage"], row["repetition"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", required=True, help="Approach A (ex: o que está rodando agora)")
    parser.add_argument("--b", required=True, help="Approach B (ex: o já completo)")
    parser.add_argument("--a-dir", type=Path, default=None,
                         help="Pasta com os CSVs de A, se não for output/analysis/<a>/ padrão")
    parser.add_argument("--b-dir", type=Path, default=None,
                         help="Pasta com os CSVs de B, se não for output/analysis/<b>/ padrão")
    args = parser.parse_args()

    rows_a = _load_approach_csvs(args.a, args.a_dir)
    rows_b = _load_approach_csvs(args.b, args.b_dir)

    if not rows_a:
        print(f"Nada carregado para '{args.a}' -- rode analysis_report.py primeiro.")
        return
    if not rows_b:
        print(f"Nada carregado para '{args.b}' -- confirme o caminho com --b-dir.")
        return

    by_key_a = {_key(r): r for r in rows_a}
    by_key_b = {_key(r): r for r in rows_b}

    common_keys = set(by_key_a) & set(by_key_b)
    print(f"'{args.a}': {len(rows_a)} linha(s) carregadas")
    print(f"'{args.b}': {len(rows_b)} linha(s) carregadas")
    print(f"combinações em comum (mesma minutes/cs/percentage/repetition nos dois): "
          f"{len(common_keys)}\n")

    if not common_keys:
        print("Nenhuma combinação em comum ainda -- espera o approach em "
              "andamento avançar mais, ou confirme que os parâmetros batem.")
        return

    # --- comparação pareada, só nas combinações que existem nos dois ---
    dur_a, dur_b = [], []
    vitorias_a = vitorias_b = empates = 0
    for key in common_keys:
        da = float(by_key_a[key]["stat_duration"])
        db = float(by_key_b[key]["stat_duration"])
        dur_a.append(da)
        dur_b.append(db)
        if da < db:
            vitorias_a += 1
        elif db < da:
            vitorias_b += 1
        else:
            empates += 1

    media_a = sum(dur_a) / len(dur_a) / 60
    media_b = sum(dur_b) / len(dur_b) / 60
    diff_pct = (media_a - media_b) / media_b * 100

    print(f"=== comparação pareada ({len(common_keys)} combinações) ===")
    print(f"  {args.a}: média stat_duration = {media_a:.2f} min")
    print(f"  {args.b}: média stat_duration = {media_b:.2f} min")
    print(f"  diferença: {args.a} está {'pior' if diff_pct > 0 else 'melhor'} "
          f"em {abs(diff_pct):.1f}%")
    print(f"\n  '{args.a}' venceu (menor tempo) em {vitorias_a}/{len(common_keys)} combinações")
    print(f"  '{args.b}' venceu (menor tempo) em {vitorias_b}/{len(common_keys)} combinações")
    if empates:
        print(f"  empates: {empates}")

    # --- quebra por minutes, se houver combinações suficientes em cada ---
    minutes_presentes = sorted({k[0] for k in common_keys}, key=int)
    if len(minutes_presentes) > 1:
        print(f"\n=== quebra por minutes ===")
        for minutes in minutes_presentes:
            keys_desse_minutes = [k for k in common_keys if k[0] == minutes]
            da = [float(by_key_a[k]["stat_duration"]) for k in keys_desse_minutes]
            db = [float(by_key_b[k]["stat_duration"]) for k in keys_desse_minutes]
            ma, mb = sum(da) / len(da) / 60, sum(db) / len(db) / 60
            print(f"  {minutes}min ({len(keys_desse_minutes)} combinações): "
                  f"{args.a}={ma:.2f}min  {args.b}={mb:.2f}min")

    # --- quebra por cs_amount -- o artigo original mostrou que a vantagem
    # do pseudo-random sobre o random não é uniforme: mais forte em
    # cs pequeno, encolhe (e até inverte) em cs grande (36, 49). Essa
    # quebra ajuda a ver se o pipeline atual reproduz esse mesmo padrão. ---
    cs_presentes = sorted({k[1] for k in common_keys}, key=int)
    if len(cs_presentes) > 1:
        print(f"\n=== quebra por cs_amount ===")
        for cs in cs_presentes:
            keys_desse_cs = [k for k in common_keys if k[1] == cs]
            da = [float(by_key_a[k]["stat_duration"]) for k in keys_desse_cs]
            db = [float(by_key_b[k]["stat_duration"]) for k in keys_desse_cs]
            ma, mb = sum(da) / len(da) / 60, sum(db) / len(db) / 60
            diff_pct = (ma - mb) / mb * 100
            situacao = "melhor" if diff_pct < 0 else "pior"
            vit_a = sum(1 for k in keys_desse_cs
                        if float(by_key_a[k]["stat_duration"]) < float(by_key_b[k]["stat_duration"]))
            vit_b = sum(1 for k in keys_desse_cs
                        if float(by_key_b[k]["stat_duration"]) < float(by_key_a[k]["stat_duration"]))
            print(f"  {cs}cs ({len(keys_desse_cs)} combinações): "
                  f"{args.a}={ma:.2f}min  {args.b}={mb:.2f}min  "
                  f"-- {args.a} {abs(diff_pct):.1f}% {situacao}  "
                  f"(vitórias: {args.a}={vit_a}  {args.b}={vit_b})")


if __name__ == "__main__":
    main()
