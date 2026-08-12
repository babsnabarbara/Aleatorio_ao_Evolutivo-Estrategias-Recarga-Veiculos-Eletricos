"""
Entrypoint único do pipeline -- substitui main.py + running.py/teste.py +
os.system("python3 findingX.py ...")/os.system("python3 generatingX.py ...").

Dois modos:

    python3 cli.py batch --approach greedy [--workers 5] [--vehicles 8000] ...
        Gera e roda o grid INTEIRO desse approach (config.MINUTES_RECHARGING
        x config.STATIONS_AMOUNTS x config.PERCENTAGES x config.REPETITIONS).
        Para cada combinação (minutes, cs_amount, percentage): gera os 5
        jobs (repetições) primeiro, depois roda os 5 em paralelo -- nessa
        ordem, sempre. Isso garante que, se o SUMO travar no meio de uma
        combinação, todas as combinações ANTERIORES já estão 100%
        geradas E simuladas, e as POSTERIORES nem começaram a ser geradas
        -- nada fica "meio gerado" perdido no ar.

    python3 cli.py run --approach greedy --minutes 10 --cs 16 --percentage 20 --repetition 3
        Roda (ou reroda) UMA simulação específica, com os parâmetros
        passados direto -- útil pra reexecutar manualmente um job que o
        SUMO derrubou. Ou, mais simples ainda:

    python3 cli.py run --from-manifest output/greedy/jobs/greedy_10min_16cs_20pct_3rep.json
        Mesma coisa, mas lendo os parâmetros (INCLUSIVE a seed) do
        manifesto já gravado na fase de geração -- garante que a
        reexecução é bit-a-bit idêntica à tentativa que falhou. Some
        --skip-generation se os arquivos (.cfg/.add/.trips) já existem em
        disco e você só quer re-rodar o SUMO, sem regerar nada.

ORDEM DE EXECUÇÃO (assumida, não confirmada com você): loop aninhado
natural `minutes > cs_amount > percentage`, sequencial entre combinações;
dentro de uma combinação, as 5 repetições rodam em paralelo. Isso é
diferente do running.py original, que executava na ordem INVERSA dos loops
por causa de um pop() no fim da lista -- se você quer preservar o
comportamento antigo, ou uma ordem diferente, é só avisar.

PARALELISMO: por padrão, até 5 processos simultâneos (uma por repetição --
é o máximo que uma combinação tem pra paralelizar). Em um servidor de 48
cores isso deixa bastante capacidade ociosa; se quiser aproveitar mais,
--workers pode ser usado mas não adianta além de 5 dentro do desenho atual
(uma combinação por vez). Rodar mais de uma combinação ao mesmo tempo é
possível mas não implementado aqui -- ver docs/ARQUITETURA.md.
"""
from __future__ import annotations

import argparse
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import config
import graph_utils
import io_utils
import simulation
import station_strategies
from seed_registry import StationSeedRegistry, TripSeedRegistry
from sim_job import SimJob

log = logging.getLogger("cli")


def _default_workers() -> int:
    """Fallback simples (só CPU) usado fora do batch() -- ex: no `run`
    single-job, onde não faz sentido calcular RAM disponível pra 1 job só."""
    available = os.cpu_count() or 1
    return max(1, min(available, len(config.REPETITIONS)))


def _auto_workers(total_jobs: int) -> int:
    """
    Calcula quantos processos SUMO rodar em paralelo, considerando CPU E
    RAM disponíveis -- RAM costuma ser o gargalo real (cada instância do
    SUMO carrega o mapa inteiro de Colônia na memória; já vimos um batch
    inteiro morrer com BrokenProcessPool num PC com pouca RAM disponível).

    ESTIMATED_RAM_PER_JOB_GB é um valor conservador, ainda NÃO medido com
    precisão para uma simulação de 8000 veículos (só testamos memória com
    simulações bem menores). Se rodar `free -h` num terminal separado
    durante um batch e ver que cada processo consome bem menos ou bem mais
    que isso, ajuste essa constante.
    """
    ESTIMATED_RAM_PER_JOB_GB = 2.0
    SAFETY_MARGIN_GB = 4.0  # reserva pro SO e outros programas abertos

    cpu_available = os.cpu_count() or 1
    cpu_based = max(1, cpu_available - 2)  # deixa 2 threads de folga pro SO

    ram_based = cpu_based  # fallback se não der pra ler /proc/meminfo
    try:
        meminfo: dict[str, str] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                meminfo[key] = rest.strip()
        available_kb = int(meminfo["MemAvailable"].split()[0])
        available_gb = available_kb / (1024 * 1024)
        usable_gb = max(0.0, available_gb - SAFETY_MARGIN_GB)
        ram_based = max(1, int(usable_gb / ESTIMATED_RAM_PER_JOB_GB))
    except (FileNotFoundError, KeyError, ValueError):
        pass  # não é Linux, ou /proc/meminfo não disponível -- usa só CPU

    return max(1, min(cpu_based, ram_based, total_jobs))


def _setup_logging(approach: str) -> None:
    log_file = config.OUTPUT_DIR / approach / "cli.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )


# ---------------------------------------------------------------------------
# Fase 1 -- geração
# ---------------------------------------------------------------------------
def _station_seed_key(approach: str, cs_amount: int) -> int | None:
    """Todos os approaches com seed (random, pseudorandom, greedyvoronoi)
    sorteiam de forma independente por cs_amount agora -- então a chave
    da seed de estação sempre inclui cs_amount. `greedy` não usa seed
    nenhuma (é determinístico), então o valor aqui simplesmente não é
    consultado nesse caso."""
    return cs_amount


def generate_combo(approach: str, minutes: int, cs_amount: int, percentage: int,
                    vehicles: int, max_vehicles_per_cs: int,
                    routing_threads: int | None = None) -> list[SimJob]:
    graph = graph_utils.default_graph()
    strategy = station_strategies.get_strategy(approach)
    station_reg = StationSeedRegistry(approach)
    trip_reg = TripSeedRegistry(approach)

    jobs = []
    for repetition in config.REPETITIONS:
        cs_key = _station_seed_key(approach, cs_amount)
        # get_or_create só busca/cria o VALOR da seed, sem reaplicar no RNG --
        # o reseed de verdade só acontece logo abaixo, e só se for preciso
        # gerar algo. Isso evita reaplicar (e, pior, sobrescrever o manifesto
        # com um valor errado) quando o job já foi gerado antes.
        station_seed = station_reg.get_or_create(repetition, cs_key)
        trip_seed = trip_reg.get_or_create(percentage, repetition)

        job = SimJob(
            approach=approach, minutes=minutes, cs_amount=cs_amount,
            percentage=percentage, repetition=repetition, vehicles=vehicles,
            max_vehicles_per_cs=max_vehicles_per_cs, seed=station_seed,
            trip_seed=trip_seed,
        )
        job.ensure_dirs()

        if not job.is_generated():
            stations = strategy(job, graph)  # reseeda a RNG de estação internamente
            io_utils.write_selected_lanes_file(job, stations)
            io_utils.write_add_file(job, stations)

            trip_reg.apply(percentage, repetition)  # reseeda a RNG de trips agora
            io_utils.sample_trips(job)

            io_utils.write_cfg_file(job, routing_threads=routing_threads)
            log.info(f"gerado: {job.manifest_id}")
        else:
            log.info(f"já gerado (reaproveitado): {job.manifest_id}")

        job.write_manifest()
        jobs.append(job)
    return jobs


# ---------------------------------------------------------------------------
# Fase 2 -- execução (multiprocessing)
# ---------------------------------------------------------------------------
_worker_graph = None


def _init_worker() -> None:
    global _worker_graph
    _worker_graph = graph_utils.default_graph()


def _run_job_in_worker(manifest_path_str: str, sumo_command: str) -> tuple[str, str | None]:
    """Roda dentro do processo worker. Devolve (manifest_id, erro_ou_None)
    -- nunca deixa a exceção vazar pro ProcessPoolExecutor, pra um job com
    problema não derrubar o resto do lote."""
    job = SimJob.from_manifest(Path(manifest_path_str))
    try:
        simulation.run_simulation(job, graph=_worker_graph, sumo_command=sumo_command)
        return job.manifest_id, None
    except Exception as exc:  # noqa: BLE001 -- queremos capturar qualquer falha do SUMO
        return job.manifest_id, f"{type(exc).__name__}: {exc}"


def run_combo(jobs: list[SimJob], workers: int, sumo_command: str) -> list[str]:
    """Roda uma lista de jobs em paralelo (pode ser de uma combinação só,
    ou do grid inteiro -- ver batch()). Devolve a lista de manifest_ids
    que FALHARAM (vazia se tudo deu certo)."""
    manifest_paths = [str(j.manifest_path) for j in jobs]
    workers = max(1, min(workers, len(jobs)))
    failed: list[str] = []
    total = len(jobs)
    done = 0

    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        futures = {
            pool.submit(_run_job_in_worker, path, sumo_command): path
            for path in manifest_paths
        }
        for future in as_completed(futures):
            manifest_id, error = future.result()
            done += 1
            if error is None:
                log.info(f"OK ({done}/{total}): {manifest_id}")
            else:
                log.error(f"FALHOU ({done}/{total}): {manifest_id} -- {error}")
                failed.append(manifest_id)
    return failed


# ---------------------------------------------------------------------------
# Modo batch -- grid inteiro
# ---------------------------------------------------------------------------
def batch(approach: str, workers: int | None, vehicles: int, max_vehicles_per_cs: int,
          sumo_command: str, routing_threads: int | None,
          minutes_list=None, cs_list=None, percentages_list=None,
          repetitions_list=None) -> None:
    minutes_values = minutes_list or config.MINUTES_RECHARGING
    cs_values = cs_list or config.STATIONS_AMOUNTS
    percentage_values = percentages_list or config.PERCENTAGES
    repetition_values = repetitions_list or config.REPETITIONS

    # generate_combo/run_combo usam config.REPETITIONS internamente (fixo,
    # não recebem por parâmetro) -- pra permitir encolher também as
    # repetições num teste local, sobrescrevemos temporariamente aqui e
    # devolvemos ao valor original no final, mesmo se der erro no meio.
    original_repetitions = config.REPETITIONS
    config.REPETITIONS = tuple(repetition_values)

    _setup_logging(approach)
    total_combos = len(minutes_values) * len(cs_values) * len(percentage_values)
    log.info(f"=== batch: approach={approach} | {total_combos} combinações x "
             f"{len(repetition_values)} repetições ===")
    if (minutes_list, cs_list, percentages_list, repetitions_list) != (None, None, None, None):
        log.info(
            f"    (grid customizado pra teste -- minutes={minutes_values}, "
            f"cs={cs_values}, percentages={percentage_values}, "
            f"repetitions={repetition_values})"
        )

    try:
        # Geração continua sequencial (rápida -- só escreve arquivo, não
        # roda SUMO), mas agora TODOS os jobs do grid inteiro são
        # acumulados numa lista só, em vez de rodados combinação por
        # combinação. Isso é o que permite os processos ficarem ocupados
        # o tempo todo: assim que um job termina, o pool já pega o
        # próximo disponível (de QUALQUER combinação), em vez de esperar
        # os 5 jobs da combinação atual terminarem antes de começar a
        # próxima -- é isso que deixava a CPU ociosa em servidores com
        # muito mais que 5 núcleos livres.
        all_jobs: list[SimJob] = []
        for minutes in minutes_values:
            for cs_amount in cs_values:
                for percentage in percentage_values:
                    jobs = generate_combo(
                        approach, minutes, cs_amount, percentage,
                        vehicles, max_vehicles_per_cs, routing_threads,
                    )
                    all_jobs.extend(jobs)

        resolved_workers = workers if workers is not None else _auto_workers(len(all_jobs))
        log.info(
            f"{len(all_jobs)} job(s) gerados, rodando com {resolved_workers} "
            f"workers em paralelo "
            f"({'auto-detectado por CPU+RAM' if workers is None else 'fixo via --workers'})"
        )

        all_failed = run_combo(all_jobs, workers=resolved_workers, sumo_command=sumo_command)
    finally:
        config.REPETITIONS = original_repetitions

    log.info(f"=== batch concluído: {len(all_failed)} job(s) falharam ===")
    for manifest_id in all_failed:
        log.error(f"  precisa reexecutar: {manifest_id}")


# ---------------------------------------------------------------------------
# Modo run -- um job só (manual/recovery)
# ---------------------------------------------------------------------------
def run_single(args: argparse.Namespace) -> None:
    if args.from_manifest:
        job = SimJob.from_manifest(Path(args.from_manifest))
    else:
        station_reg = StationSeedRegistry(args.approach)
        seed = args.seed
        if seed is None:
            seed = station_reg.apply(args.repetition, _station_seed_key(args.approach, args.cs))
        job = SimJob(
            approach=args.approach, minutes=args.minutes, cs_amount=args.cs,
            percentage=args.percentage, repetition=args.repetition,
            vehicles=args.vehicles, max_vehicles_per_cs=args.max_vehicles_per_cs,
            seed=seed,
        )
        job.ensure_dirs()

    _setup_logging(job.approach)

    needs_generation = not (args.skip_generation and job.is_generated())
    if needs_generation:
        graph = graph_utils.default_graph()
        strategy = station_strategies.get_strategy(job.approach)
        stations = strategy(job, graph)
        io_utils.write_selected_lanes_file(job, stations)
        io_utils.write_add_file(job, stations)

        trip_reg = TripSeedRegistry(job.approach)
        job.trip_seed = trip_reg.apply(job.percentage, job.repetition)
        io_utils.sample_trips(job)

        io_utils.write_cfg_file(job)
        job.write_manifest()
        log.info(f"gerado: {job.manifest_id}")
    else:
        log.info(f"--skip-generation: reaproveitando arquivos já gerados de {job.manifest_id}")

    simulation.run_simulation(job, sumo_command=args.sumo_command)
    log.info(f"OK: {job.manifest_id}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline de simulação de estações de recarga")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_batch = sub.add_parser("batch", help="Gera e roda o grid inteiro (ou um subconjunto) de um approach")
    p_batch.add_argument("--approach", required=True, choices=config.APPROACHES)
    p_batch.add_argument("--workers", type=int, default=None,
                          help="Processos simultâneos rodando ao mesmo tempo, "
                               "no grid inteiro (default: auto-detectado por "
                               "CPU e RAM disponíveis -- ver _auto_workers em "
                               "cli.py). Passe um número pra fixar manualmente.")
    p_batch.add_argument("--vehicles", type=int, default=config.DEFAULT_VEHICLES)
    p_batch.add_argument("--max-vehicles-per-cs", type=int, default=config.DEFAULT_MAX_VEHICLES_PER_CS)
    p_batch.add_argument("--sumo-command", default="sumo")
    p_batch.add_argument(
        "--minutes", type=int, nargs="+", default=None, dest="minutes_list",
        help=f"Quais valores de tempo de recarga rodar (default: todos -- "
             f"{list(config.MINUTES_RECHARGING)})",
    )
    p_batch.add_argument(
        "--cs", type=int, nargs="+", default=None, dest="cs_list",
        choices=list(config.STATIONS_AMOUNTS),
        help=f"Quais quantidades de estação rodar (default: todos -- "
             f"{list(config.STATIONS_AMOUNTS)})",
    )
    p_batch.add_argument(
        "--percentage", type=int, nargs="+", default=None, dest="percentages_list",
        help=f"Quais porcentagens de veículos rodar (default: todos -- "
             f"{list(config.PERCENTAGES)})",
    )
    p_batch.add_argument(
        "--repetition", type=int, nargs="+", default=None, dest="repetitions_list",
        help=f"Quais repetições rodar (default: todas -- {list(config.REPETITIONS)})",
    )
    p_batch.add_argument("--routing-threads", type=int, default=None,
                          help="Sobrescreve config.ROUTING_THREADS (ajuste fino para "
                               "quando várias simulações rodam ao mesmo tempo)")

    p_run = sub.add_parser("run", help="Roda (ou reroda) UMA simulação específica")
    p_run.add_argument("--from-manifest", type=str, default=None)
    p_run.add_argument("--approach", choices=config.APPROACHES)
    p_run.add_argument("--minutes", type=int)
    p_run.add_argument("--cs", type=int)
    p_run.add_argument("--percentage", type=int)
    p_run.add_argument("--repetition", type=int)
    p_run.add_argument("--vehicles", type=int, default=config.DEFAULT_VEHICLES)
    p_run.add_argument("--max-vehicles-per-cs", type=int, default=config.DEFAULT_MAX_VEHICLES_PER_CS)
    p_run.add_argument("--seed", type=int, default=None,
                        help="Sobrescreve a seed de estação em vez de buscar/gerar no registro")
    p_run.add_argument("--skip-generation", action="store_true",
                        help="Não regera .cfg/.add/.trips se já existirem -- só roda o SUMO")
    p_run.add_argument("--sumo-command", default="sumo")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.mode == "batch":
        batch(args.approach, args.workers, args.vehicles, args.max_vehicles_per_cs,
              args.sumo_command, args.routing_threads,
              minutes_list=args.minutes_list, cs_list=args.cs_list,
              percentages_list=args.percentages_list, repetitions_list=args.repetitions_list)
    elif args.mode == "run":
        if not args.from_manifest and not all(
            v is not None for v in (args.approach, args.minutes, args.cs, args.percentage, args.repetition)
        ):
            parser.error(
                "'run' precisa de --from-manifest OU de "
                "--approach/--minutes/--cs/--percentage/--repetition juntos."
            )
        run_single(args)


if __name__ == "__main__":
    main()
