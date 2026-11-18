"""
Cache em disco da seleção de estações por (approach, repetition, cs_amount)
-- usado pelas 3 estratégias com seed (random, pseudorandom, greedyvoronoi)
pra não recalcular a seleção toda vez que uma combinação diferente de
minutes/percentage passar pela mesma (cs_amount, repetition).

Cada arquivo é INDEPENDENTE (não existe cadeia/cascata entre cs_amounts
diferentes) -- as 3 estratégias sorteiam do zero pra cada cs_amount, por
decisão explícita.

NOTA: max_vehicles_per_cs NÃO entra mais na chave (chegou a entrar
temporariamente, depois revertido). Decisão metodológica: a seleção de
ONDE colocar uma estação não depende mais de max_vehicles_per_cs -- a
capacidade real de cada estação é calculada só na hora de gerar o
.add.xml (ver graph_utils.realized_capacity, io_utils.write_add_file),
adaptada à geometria de cada lane escolhida, em vez de influenciar a
escolha da própria lane.
"""
from __future__ import annotations

import config
import io_utils


def _stage_file(approach: str, repetition: int, cs_amount: int):
    return config.station_evolution_dir(approach, repetition) / f"{cs_amount}stations.xml"


def load_stage(approach: str, repetition: int, cs_amount: int) -> set[str] | None:
    """Carrega a seleção já persistida para essa combinação, ou None se
    ainda não foi calculada."""
    path = _stage_file(approach, repetition, cs_amount)
    if not path.exists():
        return None
    return io_utils.read_selected_lanes_file(path)


def save_stage(approach: str, repetition: int, cs_amount: int, stations: set[str]) -> None:
    path = _stage_file(approach, repetition, cs_amount)
    io_utils.write_selected_lanes_file_to(path, stations)

ORIGIN_COLUMNS = ["quadrante_ou_regiao", "trecho", "faixa", "origem",
                  "visitas_do_trecho", "trechos_visitados_na_regiao",
                  "tamanho_do_sorteio", "distancia_ao_centro_m"]


def _origin_file(approach: str, repetition: int, cs_amount: int):
    return config.station_evolution_dir(approach, repetition) / f"{cs_amount}stations_origem.csv"


def save_origins(approach: str, repetition: int, cs_amount: int, rows: list[dict]) -> None:
    """
    Grava, ao lado de <k>stations.xml, o arquivo <k>stations_origem.csv com
    uma linha por estação dizendo COMO ela foi escolhida (greedy e
    greedyvoronoi):
      origem = "visitacao" -> sorteada entre os trechos mais visitados
                              da região (tamanho_do_sorteio = quantos
                              entraram no sorteio, no máximo
                              TOP_VISITED_PER_REGION);
      origem = "fallback"  -> a região não tinha nenhum trecho visitado;
                              usou o trecho mais próximo do centro do
                              quadrante / núcleo da região
                              (distancia_ao_centro_m preenchida).
    """
    import csv
    path = _origin_file(approach, repetition, cs_amount)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ORIGIN_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col, "") for col in ORIGIN_COLUMNS})