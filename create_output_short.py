"""
create_output_short.py -- vive na RAIZ de TCC/ (não em MD/).

Alguns logs do SUMO (principalmente de jobs que engasgaram/engarrafaram de
verdade -- ver a investigação do job travado por 9+ dias) crescem pra
VÁRIOS GB, porque o SUMO grava um aviso por evento (frenagem de
emergência, teleporte, etc), e num cenário de gridlock isso se repete a
cada passo de simulação, por horas. Isso estoura o limite de 100MB por
arquivo do GitHub -- e sem `sudo` pra instalar git-lfs, a solução é não
mandar o log inteiro.

Esse script cria output_short/ -- uma cópia espelhada de output/ com a
MESMA estrutura de pastas, onde:
    - Todo arquivo que NÃO é log (.add.xml, .cfg, tripinfo, reports/, etc)
      é copiado como está, sem mudança nenhuma.
    - Todo log (log<repetition><percentage>percentage<cs>cs.xml) é
      substituído por um arquivo pequeno, só com o resumo final -- o mesmo
      bloco que analysis_report.py já lê (Simulation ended, Performance,
      Vehicles, Teleports, Emergency Stops, Statistics).

IMPORTANTE sobre performance: mesmo um log de 8GB é lido só pelo FINAL
(os últimos ~500KB, via seek -- nunca carrega o arquivo inteiro na
memória), porque o resumo está sempre no final do arquivo. Isso mantém o
script rápido mesmo com logs enormes.

Uso (de dentro de TCC/, não de MD/):

    python3 create_output_short.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

TCC_ROOT = Path(__file__).resolve().parent
SOURCE_DIR = TCC_ROOT / "output"
DEST_DIR = TCC_ROOT / "output_short"

TAIL_BYTES = 500_000  # 500KB de folga -- o resumo real tem só uns KB
SUMMARY_MARKER = "Simulation ended at time:"


def is_log_file(path: Path) -> bool:
    """Mesmo padrão de nome usado em analysis_report.py/check_durations.py:
    log<repetition><percentage>percentage<cs_amount>cs.xml"""
    return path.name.startswith("log") and path.suffix == ".xml"


def extract_summary(log_path: Path) -> str:
    """
    Lê só os últimos TAIL_BYTES do arquivo (via seek, nunca carrega o
    arquivo inteiro) e devolve o texto a partir de 'Simulation ended at
    time:' até o fim -- ou uma nota clara se esse marcador não aparecer
    nem nesse trecho final (log realmente incompleto/truncado).
    """
    size = log_path.stat().st_size
    with open(log_path, "rb") as f:
        f.seek(max(0, size - TAIL_BYTES))
        tail_bytes = f.read()

    tail_text = tail_bytes.decode("utf-8", errors="replace")
    idx = tail_text.find(SUMMARY_MARKER)

    if idx == -1:
        return (
            f"[log original: {size / (1024*1024):.1f}MB -- "
            f"'{SUMMARY_MARKER}' não encontrado nos últimos "
            f"{TAIL_BYTES // 1000}KB, provavelmente incompleto/travado]\n"
        )

    header = (
        f"[log original: {size / (1024*1024):.1f}MB -- reduzido a só o "
        f"resumo final abaixo]\n\n"
    )
    return header + tail_text[idx:]


def main() -> None:
    if not SOURCE_DIR.exists():
        print(f"'{SOURCE_DIR}' não existe -- rode este script de dentro de TCC/.")
        return

    if DEST_DIR.exists():
        print(f"'{DEST_DIR}' já existe -- apagando pra recomeçar do zero.")
        shutil.rmtree(DEST_DIR)

    total_files = 0
    logs_encolhidos = 0
    bytes_originais = 0
    bytes_finais = 0

    for src_path in SOURCE_DIR.rglob("*"):
        rel_path = src_path.relative_to(SOURCE_DIR)
        dest_path = DEST_DIR / rel_path

        if src_path.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
            continue

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        total_files += 1

        if is_log_file(src_path):
            original_size = src_path.stat().st_size
            summary = extract_summary(src_path)
            dest_path.write_text(summary, encoding="utf-8")

            logs_encolhidos += 1
            bytes_originais += original_size
            bytes_finais += dest_path.stat().st_size

            if logs_encolhidos % 50 == 0:
                print(f"  ... {logs_encolhidos} logs encolhidos até agora")
        else:
            shutil.copy2(src_path, dest_path)

    print(f"\n{total_files} arquivo(s) processados no total.")
    print(f"{logs_encolhidos} log(s) encolhidos.")
    if logs_encolhidos:
        economia_gb = (bytes_originais - bytes_finais) / (1024 ** 3)
        print(
            f"  tamanho original dos logs: {bytes_originais / (1024**3):.2f}GB\n"
            f"  tamanho final dos resumos: {bytes_finais / (1024**2):.2f}MB\n"
            f"  economia: {economia_gb:.2f}GB"
        )
    print(f"\n[pronto -- {DEST_DIR}]")


if __name__ == "__main__":
    main()
