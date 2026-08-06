"""
Duas seeds independentes por approach, com escopos diferentes de propósito:

    - Seed de ESTAÇÃO (StationSeedRegistry): uma por REPETITION só.
      Representa "uma evolução da infraestrutura de recarga da cidade" --
      NÃO varia com cs_amount (é o que permite crescer 9->16->25->36->49
      mantendo as posições antigas), nem com percentage/minutes (a posição
      física de uma estação não deveria depender de quantos veículos
      recarregam nem de quanto tempo demora a recarga).

    - Seed de TRIPS (TripSeedRegistry): por (percentage, repetition).
      Independente da seed de estação -- qual % de veículos é sorteada
      pra recarregar não tem relação com onde as estações estão.

Antes da mudança que você pediu, uma seed só cobria (cs, percentage,
repetition) e controlava estação+trips juntos no mesmo stream aleatório.
Separar em duas seeds resolve dois problemas ao mesmo tempo:
    1. Permite a seed de estação ser estável através de cs_amount
       (necessário pro crescimento incremental).
    2. Evita que mudar a seed de estação (agora compartilhada entre TODOS
       os cs_amount de uma repetition) afete acidentalmente o sorteio de
       trips, que deveria continuar variando por percentage.

Concorrência e escrita atômica: mesma lógica de antes (arquivo temporário
+ os.replace).
"""
from __future__ import annotations

import json
import os
import random
import secrets
from pathlib import Path
from typing import Dict

import config


class _JsonSeedRegistry:
    """Base genérica: carrega/persiste um mapa {chave: seed} em disco."""

    def __init__(self, path: Path):
        self.path = path
        self._data: Dict[str, int] = self._load()

    def _load(self) -> Dict[str, int]:
        if not self.path.exists():
            return {}
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, sort_keys=True)
        os.replace(tmp_path, self.path)

    def _get_or_create(self, key: str) -> int:
        if key in self._data:
            return self._data[key]
        new_seed = secrets.randbits(32)
        self._data[key] = new_seed
        self._save()
        return new_seed


class StationSeedRegistry(_JsonSeedRegistry):
    """Seed de estação. Por padrão, 1 por repetition, compartilhada por
    TODOS os cs_amount/percentage/minutes dessa repetition -- usada pelos
    approaches com crescimento incremental (random, pseudorandom), onde
    representa uma única 'evolução da cidade'. Para approaches sem
    crescimento incremental (greedyvoronoi), veja o parâmetro cs_amount de
    get_or_create/apply -- cada cs_amount ganha sua própria seed."""

    def __init__(self, approach: str):
        self.approach = approach
        super().__init__(config.station_seed_registry_file(approach))

    def get_or_create(self, repetition: int, cs_amount: int | None = None) -> int:
        """
        Por padrão (cs_amount=None), a chave é só a repetition -- é o modo
        usado por approaches com crescimento incremental (random,
        pseudorandom): uma seed cobre TODOS os cs_amount dessa repetition,
        já que tiers maiores reaproveitam as estações dos tiers menores.

        Se cs_amount for passado, a chave inclui o cs_amount -- usado por
        approaches SEM crescimento incremental (greedyvoronoi): cada
        tamanho de estação sorteia do zero, então precisa da sua própria
        seed independente (senão 9 e 16 estações do greedyvoronoi
        acabariam usando exatamente os mesmos pontos iniciais do RNG).
        """
        key = f"{repetition}rep" if cs_amount is None else f"{repetition}rep_{cs_amount}cs"
        return self._get_or_create(key)

    def apply(self, repetition: int, cs_amount: int | None = None) -> int:
        """Busca/gera a seed de estação e popula random/np.random.
        Chame isso ANTES de qualquer chamada a station_strategies para
        essa repetition (e, para approaches sem crescimento incremental,
        também para esse cs_amount especificamente)."""
        seed = self.get_or_create(repetition, cs_amount)
        _seed_global_rngs(seed)
        return seed


class TripSeedRegistry(_JsonSeedRegistry):
    """Seed de sorteio de trips: por (percentage, repetition) -- não
    depende de cs_amount nem de minutes."""

    def __init__(self, approach: str):
        self.approach = approach
        super().__init__(config.trip_seed_registry_file(approach))

    def get_or_create(self, percentage: int, repetition: int) -> int:
        return self._get_or_create(f"{percentage}pct_{repetition}rep")

    def apply(self, percentage: int, repetition: int) -> int:
        """Busca/gera a seed de trips e popula random/np.random. Chame
        isso ANTES de io_utils.sample_trips(...)."""
        seed = self.get_or_create(percentage, repetition)
        _seed_global_rngs(seed)
        return seed


def _seed_global_rngs(seed: int) -> None:
    random.seed(seed)
    try:
        import numpy as np  # usado por greedy_voronoi_strategy (Voronoi)
        np.random.seed(seed % (2**32 - 1))
    except ImportError:
        pass
