#!/usr/bin/env python3
"""
find_longest_success.py

Varre TODOS os arquivos REPORT-* (em output/<approach>/*/*/reports/) de
TODOS os approaches, calcula a duração (INÍCIO -> FIM) de cada simulação
que terminou com SUCESSO ("FIM DA SIMULAÇÃO"), e mostra as mais demoradas
-- útil pra escolher um valor de --max-sim-hours com folga real acima do
que qualquer simulação legítima já levou, em vez de um número arbitrário.

Ignora relatórios de simulação que FALHOU (não tem duração completa
"real" de sucesso).

Uso (a partir de ~/TCC):
    python3 find_longest_success.py
    python3 find_longest_success.py --approach pseudorandom
    python3 find_longest_success.py --top 30
"""
import argparse
import re
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("output")

_HORA_RE = re.compile(r"hora:\s*(\d{2}:\d{2}:\d{2})")
_DATA_RE = re.compile(r"data:\s*(\d{2}/\d{2}/\d{4})")


def parse_report(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    if "FIM DA SIMULAÇÃO" not in text:
        return None  # falhou ou incompleto -- não conta como referência de sucesso

    blocks = text.split("INÍCIO DA SIMULAÇÃO")
    if len(blocks) < 2:
        return None
    after_inicio = blocks[1]

    parts = after_inicio.split("FIM DA SIMULAÇÃO")
    if len(parts) < 2:
        return None
    inicio_text, fim_text = parts[0], parts[1]

    def extract(txt):
        h = _HORA_RE.search(txt)
        d = _DATA_RE.search(txt)
        if not h or not d:
            return None
        return datetime.strptime(f"{d.group(1)} {h.group(1)}", "%d/%m/%Y %H:%M:%S")

    start = extract(inicio_text)
    end = extract(fim_text)
    if not start or not end:
        return None

    duration_s = (end - start).total_seconds()
    if duration_s < 0:
        # simulação cruzou meia-noite e o relatório só guarda hora, não
        # data de mudança -- soma 24h como aproximação razoável
        duration_s += 24 * 3600

    return duration_s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--approach", default=None,
                     help="restringe a um approach (default: todos)")
    ap.add_argument("--top", type=int, default=15,
                     help="quantas das mais demoradas mostrar (default: 15)")
    args = ap.parse_args()

    approaches = (
        [args.approach] if args.approach
        else sorted(d.name for d in OUTPUT_DIR.iterdir() if d.is_dir())
    )

    results = []  # (duration_s, path)
    n_reports = 0
    n_failed_or_unparsed = 0

    for approach in approaches:
        approach_dir = OUTPUT_DIR / approach
        if not approach_dir.is_dir():
            continue
        for report_file in approach_dir.glob("*min/*percentage*cs/reports/REPORT-*"):
            n_reports += 1
            duration_s = parse_report(report_file)
            if duration_s is None:
                n_failed_or_unparsed += 1
                continue
            results.append((duration_s, report_file))

    if not results:
        print("Nenhum REPORT de sucesso encontrado.")
        return

    results.sort(key=lambda r: r[0], reverse=True)

    print(f"{n_reports} relatórios encontrados, {len(results)} com sucesso "
          f"e duração válida ({n_failed_or_unparsed} falharam ou não deu "
          f"pra parsear)\n")

    print(f"Top {min(args.top, len(results))} mais demoradas:")
    print(f"{'duração':<12}{'arquivo'}")
    for duration_s, path in results[: args.top]:
        h = duration_s / 3600
        print(f"{h:<12.2f}{path}")

    max_h = results[0][0] / 3600
    print(f"\nMais demorada com sucesso: {max_h:.2f}h")
    print(f"Sugestão de --max-sim-hours com folga: {max(max_h * 2, max_h + 1):.1f}h "
          f"(2x a mais demorada, ou +1h, o que for maior)")


if __name__ == "__main__":
    main()
