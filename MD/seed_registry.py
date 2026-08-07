"""
Duas seeds independentes por approach, com escopos diferentes de propósito:

    - Seed de ESTAÇÃO (StationSeedRegistry): por (repetition, cs_amount).
      Cada approach com seed (random, pseudorandom, greedyvoronoi) sorteia
      a seleção de estações de forma independente pra cada `cs_amount` --
      não há relação entre as estações escolhidas para tamanhos
      diferentes. A seed NÃO varia com percentage/minutes (a posição
      física de uma estação não deveria depender de quantos veículos
      recarregam nem de quanto tempo demora a recarga) -- só entre
      cs_amount diferentes.

    - Seed de TRIPS (TripSeedRegistry): por (percentage, repetition).
      Independente da seed de estação -- qual % de veículos é sorteada
      pra recarregar não tem relação com onde as estações estão.

Duas seeds separadas, em vez de uma seed única cobrindo tudo, porque
onde a estação fica não deveria depender de quantos veículos recarregam
(e vice-versa) -- misturar os dois faria mudar `percentage` alterar
acidentalmente a posição das estações também.

Concorrência e escrita atômica: arquivo temporário + os.replace.
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
    """Seed de estação, por (repetition, cs_amount). Cada approach com
    seed sorteia de forma independente pra cada cs_amount -- não existe
    relação entre a seleção de estações de tamanhos diferentes em nenhum
    dos 3 approaches (random, pseudorandom, greedyvoronoi)."""

    def __init__(self, approach: str):
        self.approach = approach
        super().__init__(config.station_seed_registry_file(approach))

    def get_or_create(self, repetition: int, cs_amount: int | None = None) -> int:
        """
        A chave normalmente inclui `cs_amount` -- é assim que os 3
        approaches com seed chamam isso hoje (cada cs_amount sorteia do
        zero, de forma independente). `cs_amount=None` ainda é aceito por
        compatibilidade (chave só por repetition), mas nenhum approach usa
        esse caminho atualmente.
        """
        key = f"{repetition}rep" if cs_amount is None else f"{repetition}rep_{cs_amount}cs"
        return self._get_or_create(key)

    def apply(self, repetition: int, cs_amount: int | None = None) -> int:
        """Busca/gera a seed de estação e popula random/np.random.
        Chame isso ANTES de qualquer chamada a station_strategies para
        essa (repetition, cs_amount)."""
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
