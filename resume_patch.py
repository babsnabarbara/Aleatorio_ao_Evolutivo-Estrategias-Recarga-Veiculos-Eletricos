import pathlib

path = pathlib.Path("MD/cli.py")
text = path.read_text(encoding="utf-8")

old1 = '''    return failed


# ---------------------------------------------------------------------------
# Modo batch -- grid inteiro
# ---------------------------------------------------------------------------
def batch(approach: str, workers: int | None, vehicles: int, max_vehicles_per_cs: int,
          sumo_command: str, routing_threads: int | None,
          minutes_list=None, cs_list=None, percentages_list=None,
          repetitions_list=None, max_sim_hours: float | None = None) -> None:'''

new1 = '''    return failed


def _is_successfully_completed(job: SimJob) -> bool:
    """True se já existe um REPORT de SUCESSO ('FIM DA SIMULAÇÃO') para
    este job -- usado por batch() para pular jobs já concluídos numa
    reexecução, em vez de refazer o grid inteiro do zero (job.report_file
    é sempre o MESMO caminho fixo, sobrescrito a cada tentativa -- ver
    simulation.py::_write_report -- então checar seu conteúdo reflete
    sempre o resultado da tentativa mais recente)."""
    report_file = job.report_file
    if not report_file.exists():
        return False
    try:
        content = report_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return "FIM DA SIMULAÇÃO" in content


# ---------------------------------------------------------------------------
# Modo batch -- grid inteiro
# ---------------------------------------------------------------------------
def batch(approach: str, workers: int | None, vehicles: int, max_vehicles_per_cs: int,
          sumo_command: str, routing_threads: int | None,
          minutes_list=None, cs_list=None, percentages_list=None,
          repetitions_list=None, max_sim_hours: float | None = None,
          force_rerun_all: bool = False) -> None:'''

assert text.count(old1) == 1, "bloco 1 não encontrado (ou duplicado) -- avise antes de continuar"
text = text.replace(old1, new1)

old2 = '''        resolved_workers = workers if workers is not None else _auto_workers(len(all_jobs))
        log.info(
            f"{len(all_jobs)} job(s) gerados, rodando com {resolved_workers} "
            f"workers em paralelo "
            f"({'auto-detectado por CPU+RAM' if workers is None else 'fixo via --workers'})"
        )

        jobs_by_manifest_id = {job.manifest_id: job for job in all_jobs}
        all_failed = run_combo(all_jobs, workers=resolved_workers, sumo_command=sumo_command,
                                max_sim_hours=max_sim_hours)'''

new2 = '''        jobs_by_manifest_id = {job.manifest_id: job for job in all_jobs}

        # FIX: reexecutar `batch` não deve repetir jobs que já têm REPORT
        # de sucesso -- antes disso, rodar `batch` de novo sempre refazia
        # o grid inteiro (inclusive jobs concluídos há dias), caro demais
        # pra usar como forma de "só terminar o que falta" depois de matar
        # um processo travado manualmente. --force-rerun-all restaura o
        # comportamento antigo (roda tudo, mesmo já concluído).
        if force_rerun_all:
            pending_jobs = all_jobs
        else:
            pending_jobs = [job for job in all_jobs if not _is_successfully_completed(job)]
            n_skipped = len(all_jobs) - len(pending_jobs)
            if n_skipped:
                log.info(
                    f"{n_skipped} job(s) já têm relatório de sucesso -- "
                    f"pulando (use --force-rerun-all pra ignorar isso)"
                )

        if not pending_jobs:
            log.info("Nada a fazer -- todos os jobs do grid já têm relatório de sucesso.")
            all_failed: list[str] = []
        else:
            resolved_workers = workers if workers is not None else _auto_workers(len(pending_jobs))
            log.info(
                f"{len(pending_jobs)} job(s) pendentes, rodando com "
                f"{resolved_workers} workers em paralelo "
                f"({'auto-detectado por CPU+RAM' if workers is None else 'fixo via --workers'})"
            )
            all_failed = run_combo(pending_jobs, workers=resolved_workers, sumo_command=sumo_command,
                                    max_sim_hours=max_sim_hours)'''

assert text.count(old2) == 1, "bloco 2 não encontrado (ou duplicado) -- avise antes de continuar"
text = text.replace(old2, new2)

old3 = '''    p_run = sub.add_parser("run", help="Roda (ou reroda) UMA simulação específica")'''

new3 = '''    p_batch.add_argument(
        "--force-rerun-all", action="store_true",
        help="Ignora relatórios de sucesso já existentes e roda o grid "
             "inteiro de novo, mesmo jobs já concluídos (comportamento "
             "antigo do batch, antes do skip automático).",
    )

    p_run = sub.add_parser("run", help="Roda (ou reroda) UMA simulação específica")'''

assert text.count(old3) == 1, "bloco 3 não encontrado (ou duplicado) -- avise antes de continuar"
text = text.replace(old3, new3)

old4 = '''    if args.mode == "batch":
        batch(args.approach, args.workers, args.vehicles, args.max_vehicles_per_cs,
              args.sumo_command, args.routing_threads,
              minutes_list=args.minutes_list, cs_list=args.cs_list,
              percentages_list=args.percentages_list, repetitions_list=args.repetitions_list,
              max_sim_hours=args.max_sim_hours)'''

new4 = '''    if args.mode == "batch":
        batch(args.approach, args.workers, args.vehicles, args.max_vehicles_per_cs,
              args.sumo_command, args.routing_threads,
              minutes_list=args.minutes_list, cs_list=args.cs_list,
              percentages_list=args.percentages_list, repetitions_list=args.repetitions_list,
              max_sim_hours=args.max_sim_hours, force_rerun_all=args.force_rerun_all)'''

assert text.count(old4) == 1, "bloco 4 não encontrado (ou duplicado) -- avise antes de continuar"
text = text.replace(old4, new4)

path.write_text(text, encoding="utf-8")
print("OK -- cli.py atualizado")
