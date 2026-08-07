"""
Suporte compartilhado para o crescimento incremental de estações entre os
tiers de cs_amount (9 -> 16 -> 25 -> 36 -> 49) dentro de uma mesma seed de
estação (uma "evolução da cidade").

Cada estratégia que usa seed (random, pseudorandom, greedyvoronoi) delega
a este módulo:
    1. descobrir o tier anterior e carregar suas estações já persistidas
       (nunca recalcular o que já foi decidido antes);
    2. persistir o resultado do tier atual assim que ele é calculado, para
       os próximos tiers (e as próximas vezes que esse mesmo tier for
       pedido, por qualquer combinação de percentage/minutes) reaproveitarem
       sem recomputar.

Isso é o que garante, por construção (não por coincidência de algoritmo),
os requisitos:
    - estações já instaladas permanecem exatamente nas mesmas posições;
    - ao aumentar cs_amount, só as estações novas são sorteadas;
    - nenhuma estação existente é removida ou reposicionada.
"""
from __future__ import annotations

from typing import Callable

import config
import io_utils


def previous_tier(cs_amount: int) -> int | None:
    """O maior valor em config.STATIONS_AMOUNTS estritamente menor que
    cs_amount, ou None se cs_amount já é o menor tier (9)."""
    smaller = [c for c in config.STATIONS_AMOUNTS if c < cs_amount]
    return max(smaller) if smaller else None


def _stage_file(approach: str, repetition: int, cs_amount: int):
    return config.station_evolution_dir(approach, repetition) / f"{cs_amount}stations.xml"


def load_stage(approach: str, repetition: int, cs_amount: int) -> set[str] | None:
    """Carrega a seleção já persistida para esse tier, ou None se ainda
    não foi calculada."""
    path = _stage_file(approach, repetition, cs_amount)
    if not path.exists():
        return None
    return io_utils.read_selected_lanes_file(path)


def save_stage(approach: str, repetition: int, cs_amount: int, stations: set[str]) -> None:
    path = _stage_file(approach, repetition, cs_amount)
    io_utils.write_selected_lanes_file_to(path, stations)


# Assinatura que cada estratégia implementa: recebe o conjunto já escolhido
# (pode ser vazio, no primeiro tier) e o NÚMERO TOTAL desejado neste tier;
# devolve o conjunto completo (extends -- nunca remove elementos de
# `already_chosen`).
ExtendFn = Callable[["set[str]", int], "set[str]"]


def get_or_extend(approach: str, repetition: int, cs_amount: int, extend_fn: ExtendFn) -> set[str]:
    """
    Ponto de entrada único usado por cada estratégia:
        1. Se este tier já foi calculado antes (por qualquer job de
           qualquer percentage/minutes que já tenha passado por aqui),
           reaproveita do disco -- não recalcula, não regarante nada.
        2. Senão, recursivamente garante que o tier ANTERIOR já existe
           (efeito cascata: pedir 49 sem nunca ter gerado 9/16/25/36 gera
           a cadeia inteira, na ordem certa, uma vez só).
        3. Chama `extend_fn(already_chosen, cs_amount)` para obter só as
           estações NOVAS deste tier, e persiste o resultado completo.
    """
    cached = load_stage(approach, repetition, cs_amount)
    if cached is not None:
        if len(cached) != cs_amount:
            raise RuntimeError(
                f"Estágio {cs_amount}stations.xml de {approach}/seed_{repetition} "
                f"corrompido: tem {len(cached)} estações, esperava {cs_amount}."
            )
        return cached

    prev = previous_tier(cs_amount)
    already_chosen: set[str] = set()
    if prev is not None:
        already_chosen = get_or_extend(approach, repetition, prev, extend_fn)

    result = extend_fn(set(already_chosen), cs_amount)

    if not already_chosen.issubset(result):
        raise RuntimeError(
            f"Violação da regra de evolução incremental em {approach}/seed_{repetition}: "
            f"o tier {cs_amount} não manteve todas as estações do tier anterior "
            f"({prev}). Faltando: {already_chosen - result}"
        )
    if len(result) != cs_amount:
        raise RuntimeError(
            f"extend_fn de {approach} devolveu {len(result)} estações, "
            f"esperava exatamente {cs_amount} (job seed_{repetition})."
        )

    save_stage(approach, repetition, cs_amount, result)
    return result
