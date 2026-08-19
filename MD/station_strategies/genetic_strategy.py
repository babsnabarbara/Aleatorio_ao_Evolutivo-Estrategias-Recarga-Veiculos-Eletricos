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
"""
from __future__ import annotations

import json

import networkx as nx

import config
import graph_utils
import io_utils
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
            f"que o resultado foi copiado para essa pasta."
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
            f"não existem no grafo atual (net.xml mudou desde que o GA rodou?): "
            f"{missing}"
        )

    lanes = {f"{edge_id}_0" for edge_id in edge_ids}

    # FIX: comprovado empiricamente que uma lane curta demais causa "skips
    # stop" + teleporte em runtime (ver graph_utils.has_min_capacity). Como
    # essas posições vêm de fora (já decididas pelo GA), não há candidato
    # alternativo pra tentar -- só valida e avisa claramente, em vez de
    # filtrar silenciosamente (silenciar aqui mudaria o resultado do GA sem
    # você saber).
    lane_lengths = graph_utils.lane_lengths()
    veh_length = io_utils.vehicle_length("soulEV65")
    too_short = [
        lane for lane in lanes
        if not graph_utils.has_min_capacity(lane, job.max_vehicles_per_cs, lane_lengths, veh_length)
    ]
    if too_short:
        raise ValueError(
            f"{result_file}: {len(too_short)} lane(s) escolhidas pelo GA não "
            f"têm comprimento suficiente para max_vehicles_per_cs="
            f"{job.max_vehicles_per_cs}: {too_short}. O GA não considera esse "
            f"critério na otimização -- ou reduza max_vehicles_per_cs pra "
            f"essa rodada, ou aceite que essas posições podem causar "
            f"'skips stop'/teleporte na simulação."
        )

    return lanes