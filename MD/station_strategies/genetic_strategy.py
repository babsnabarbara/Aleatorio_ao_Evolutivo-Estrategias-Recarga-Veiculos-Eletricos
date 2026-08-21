"""
Approach 'genetic' -- NÃO calcula nada, só LÊ o resultado de um algoritmo
genético que já rodou fora deste pipeline (script separado, rodado uma
vez por cs_amount x seed, salvando em
input/exhaustive_genetic<cs_amount>/resultado_final_k<cs_amount>_seed<seed>.json).

Diferente dos outros 4 approaches: não sorteia nada, não usa
StationSeedRegistry, não passa por station_strategies/evolution.py (não
tem sentido "cachear" algo que já É um arquivo estático em disco). A única
responsabilidade daqui é: dado (cs_amount, repetition), decidir qual seed
do GA usar e converter o resultado (lista de edge ids) para o formato de
lane id que o resto do pipeline espera (<edge_id>_0 -- primeira lane de
cada edge; o GA opera no nível de rua/edge, não de lane específica).

Usa o campo "solucao_final_refinada" do JSON (pós-refinamento), não
"solucao_ga" (saída bruta, pré-refinamento) -- decisão explícita.

Sempre aceita as posições exatas do GA, sem filtrar por
capacidade/comprimento de lane -- a capacidade real de cada estação é
calculada depois, na hora de gerar o .add.xml (ver
graph_utils.realized_capacity), adaptada à geometria de cada lane. Isso é
especialmente importante aqui: como as posições vêm de um algoritmo
externo já publicado, não faz sentido rejeitar ou alterar o que ele
decidiu por um critério (comprimento de rua) que ele nunca considerou.

O `graph` recebido aqui já vem restrito ao componente gigante do mapa
(ver cli.py/graph_utils.default_giant_graph) -- mesmo componente que o
script original do algoritmo genético usa internamente
(get_giant_component/candidate_nodes), então a checagem "edge existe no
grafo" abaixo já é consistente com o universo de candidatos que o próprio
GA usou pra gerar essas posições, e com os outros 4 approaches (que agora
também só escolhem estações dentro desse mesmo componente).
"""
from __future__ import annotations

import json

import networkx as nx

import config
from sim_job import SimJob


def _seed_for_repetition(repetition: int) -> int:
    if not (1 <= repetition <= len(config.GENETIC_SEEDS)):
        raise ValueError(
            f"repetition={repetition} fora do intervalo suportado pelo "
            f"approach genetic (só existem {len(config.GENETIC_SEEDS)} "
            f"seeds pré-computadas: {config.GENETIC_SEEDS})."
        )
    return config.GENETIC_SEEDS[repetition - 1]


def select_charging_points(job: SimJob, graph: nx.DiGraph) -> set[str]:
    seed = _seed_for_repetition(job.repetition)
    result_file = config.genetic_result_file(job.cs_amount, seed)

    if not result_file.exists():
        raise FileNotFoundError(
            f"{result_file} não existe -- confirme que o algoritmo genético "
            f"já rodou para cs_amount={job.cs_amount} com seed={seed}, e "
            f"que o resultado foi copiado para essa pasta. Rode "
            f"`python3 check_genetic_files.py` para ver de uma vez quais "
            f"arquivos faltam em TODOS os cs_amount/seeds, antes de disparar "
            f"um batch inteiro (evita descobrir um por um, job a job)."
        )

    with open(result_file, encoding="utf-8") as f:
        data = json.load(f)

    num_estacoes = data.get("num_estacoes")
    if num_estacoes != job.cs_amount:
        raise ValueError(
            f"{result_file} diz num_estacoes={num_estacoes}, mas o job "
            f"pediu cs_amount={job.cs_amount} -- arquivo na pasta errada?"
        )

    edge_ids = data["solucao_final_refinada"]
    if len(edge_ids) != job.cs_amount:
        raise ValueError(
            f"{result_file} tem {len(edge_ids)} estações em "
            f"'solucao_final_refinada', esperado {job.cs_amount}."
        )

    missing = [e for e in edge_ids if e not in graph]
    if missing:
        raise ValueError(
            f"{result_file}: {len(missing)} edge(s) de 'solucao_final_refinada' "
            f"não pertencem ao componente gigante do grafo atual (net.xml "
            f"mudou desde que o GA rodou? Ou o `graph` recebido aqui não é "
            f"o componente gigante -- ver cli.py/graph_utils.default_giant_graph): "
            f"{missing}"
        )

    return {f"{edge_id}_0" for edge_id in edge_ids}