"""
check_genetic_files.py -- confere se todos os arquivos de resultado do
algoritmo genético já existem (input/exhaustive_genetic<cs>/
resultado_final_k<cs>_seed<seed>.json, para cada cs_amount x seed), e
avisa exatamente o que falta.

NÃO roda o genetic_algorithm.py sozinho -- decisão explícita, dado que uma
única seed pode levar horas (às vezes bem mais, dependendo do cs_amount).
Esse script só faz a checagem rápida (segundos), pra você saber com
antecedência o que precisa rodar manualmente antes de disparar
`cli.py batch --approach genetic`.

Uso (de dentro de MD/):

    python3 check_genetic_files.py
"""
from __future__ import annotations

import config


def main() -> None:
    faltando: list[tuple[int, int]] = []
    existentes = 0

    for cs_amount in config.STATIONS_AMOUNTS:
        for seed in config.GENETIC_SEEDS:
            result_file = config.genetic_result_file(cs_amount, seed)
            if result_file.exists():
                existentes += 1
            else:
                faltando.append((cs_amount, seed))

    total = len(config.STATIONS_AMOUNTS) * len(config.GENETIC_SEEDS)
    print(f"{existentes}/{total} arquivo(s) de resultado do GA já existem.\n")

    if not faltando:
        print("Tudo pronto -- pode rodar `cli.py batch --approach genetic` sem restrições.")
        return

    print(f"FALTAM {len(faltando)} arquivo(s):\n")

    # agrupa por cs_amount, pra ficar fácil ver quais pastas precisam de trabalho
    por_cs: dict[int, list[int]] = {}
    for cs_amount, seed in faltando:
        por_cs.setdefault(cs_amount, []).append(seed)

    for cs_amount in sorted(por_cs):
        seeds = sorted(por_cs[cs_amount])
        pasta = config.INPUT_DIR / f"exhaustive_genetic{cs_amount}"
        print(f"  cs_amount={cs_amount} -- faltam as seeds {seeds}")
        print(f"    pasta: {pasta}")
        if len(seeds) == len(config.GENETIC_SEEDS):
            print(f"    (nenhuma seed rodada ainda pra esse cs_amount)")
        print()

    print(
        "Pra gerar os que faltam, entre na pasta de cada cs_amount listado\n"
        "acima e rode o genetic_algorithm.py de lá (script próprio, roda fora\n"
        "deste pipeline -- ver a lista SEEDS_PARA_TESTAR dentro do script se\n"
        "quiser rodar só as seeds específicas que faltam, em vez de todas as\n"
        "5 de novo). Lembre-se: cada seed pode levar horas -- não é uma\n"
        "espera curta."
    )
    print(
        "\nEnquanto isso, `cli.py batch --approach genetic` só vai funcionar\n"
        "pros cs_amount que já estiverem 100% completos (todas as 5 seeds);\n"
        "os outros vão falhar job a job com FileNotFoundError, avisando qual\n"
        "seed específica está faltando."
    )


if __name__ == "__main__":
    main()
