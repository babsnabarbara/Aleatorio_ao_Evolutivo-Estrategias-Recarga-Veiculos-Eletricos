"""
Agrupa as visitas de input/mostVisited.xml (contadas por FAIXA/lane) por
TRECHO (edge = vértice do grafo) e grava input/mostVisitedEdges.xml:

    <mostVisitedEdges>
        <edge id="-10070371#4" count="12" lanes="1"/>
        ...
    </mostVisitedEdges>

count = soma das visitas de todas as faixas do trecho; lanes = quantas
faixas do trecho aparecem em mostVisited.xml. Ordenado por count
decrescente (empate: id).

Usado por greedy e greedyvoronoi (via load()). O arquivo é (re)gerado
automaticamente se não existir ou se mostVisited.xml for mais novo que ele.
Para gerar na mão:

    python MD/most_visited_edges.py
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import config


def edge_of(lane_id: str) -> str:
    """'-10070371#4_0' -> '-10070371#4' (tira só o último '_<índice>')."""
    return lane_id.rsplit("_", 1)[0]


def build(source: Path = None, target: Path = None) -> Path:
    source = Path(source) if source else config.MOST_VISITED_FILE
    target = Path(target) if target else config.MOST_VISITED_EDGES_FILE

    counts: dict[str, int] = defaultdict(int)
    lanes: dict[str, int] = defaultdict(int)
    for lane_elem in ET.parse(source).getroot().findall(".//lane"):
        lane_id = lane_elem.get("id")
        if lane_id is None:
            continue
        edge = edge_of(lane_id)
        counts[edge] += int(lane_elem.get("count") or 0)
        lanes[edge] += 1

    root = ET.Element("mostVisitedEdges")
    for edge in sorted(counts, key=lambda e: (-counts[e], e)):
        ET.SubElement(root, "edge", id=edge, count=str(counts[edge]),
                      lanes=str(lanes[edge]))
    if hasattr(ET, "indent"):  # Python 3.9+; só deixa o arquivo legível
        ET.indent(root, space="    ")
    ET.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)
    return target


@lru_cache(maxsize=1)
def load() -> dict[str, int]:
    """{edge_id: visitas}, ordenado por visitas decrescente (empate: id)."""
    source, target = config.MOST_VISITED_FILE, config.MOST_VISITED_EDGES_FILE
    if not target.exists() or target.stat().st_mtime < source.stat().st_mtime:
        build(source, target)
    edges = {e.get("id"): int(e.get("count"))
             for e in ET.parse(target).getroot().findall("edge")}
    return dict(sorted(edges.items(), key=lambda item: (-item[1], item[0])))


def top_visited(edges, visits: dict[str, int], n: int) -> list[str]:
    """Os `n` trechos de `edges` com mais visitas (só os com visita > 0),
    em ordem decrescente de visitas; empate desfeito pelo id, para o
    resultado não depender da ordem de iteração de conjuntos."""
    visited = [e for e in edges if visits.get(e, 0) > 0]
    visited.sort(key=lambda e: (-visits[e], e))
    return visited[:n]


if __name__ == "__main__":
    out = build()
    print(f"gerado: {out} ({len(load.__wrapped__())} trechos)")