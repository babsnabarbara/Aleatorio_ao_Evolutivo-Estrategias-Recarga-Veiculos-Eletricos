"""
Toda estratégia é um módulo que expõe uma função com esta assinatura:

    select_charging_points(job: SimJob, graph: nx.DiGraph) -> set[str]

`graph` é passado de fora (não recalculado dentro da estratégia) porque
montá-lo é caro (~70 mil nós) -- quem orquestra (cli.py/runner) monta uma
vez por worker e reaproveita entre combinações, do mesmo jeito que já é
feito em genetic_algorithm.py hoje.

A seed do job já deve ter sido aplicada (via seed_registry.apply(...)) por
quem chama, ANTES de chamar select_charging_points -- as estratégias usam
random/np.random globais, não recebem a seed como argumento.

`station_strategies.REGISTRY` (em __init__.py) mapeia o nome do approach
("random", "pseudorandom", "greedy", "greedyvoronoi") para a função
correspondente -- é isso que substitui os antigos
`os.system("python3 findingX.py ...")` por uma chamada direta em processo.
"""
from __future__ import annotations

from typing import Callable

import networkx as nx

from sim_job import SimJob

StationStrategy = Callable[[SimJob, nx.DiGraph], "set[str]"]
