"""
SimJob: a unidade atômica de uma simulação -- uma combinação específica de
(approach, minutes, cs_amount, percentage, repetition).

A mesma dataclass e a mesma função de execução (em simulation.py, ainda por
escrever) servem tanto para:
    - a fase de geração em lote (gera os N jobs de uma combinação e os
      arquivos de cada um),
    - a fase de execução em lote,
    - a reexecução manual de UM job específico via `--from-manifest`,
sem duplicar lógica entre esses três casos -- é isso que garante que uma
reexecução manual seja bit-a-bit igual à execução original que crashou.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import config


@dataclass
class SimJob:
    approach: str
    minutes: int              # timeOfRecharge
    cs_amount: int
    percentage: int
    repetition: int           # fileToBeRun (1..5)
    vehicles: int
    max_vehicles_per_cs: int
    seed: int                 # decidido uma vez via SeedRegistry, fixo depois
    trip_seed: int | None = None  # seed do sorteio de trips (TripSeedRegistry) --
                                    # opcional só para manifestos antigos sem o campo
    port: int | None = None   # porta TraCI -- atribuída na hora de rodar,
                               # não na geração (ver runner)

    # -- paths derivados, sempre a partir de config.py, nunca hardcoded ----
    @property
    def folder(self) -> Path:
        return config.experiment_folder(
            self.approach, self.minutes, self.percentage, self.cs_amount
        )

    @property
    def selected_lanes_dir(self) -> Path:
        return config.selected_lanes_dir(self.folder)

    @property
    def sorted_cars_dir(self) -> Path:
        return config.sorted_cars_dir(self.folder, self.vehicles)

    @property
    def reports_dir(self) -> Path:
        return config.reports_dir(self.folder)

    # arquivos individuais desta repetição, no padrão que já existe hoje
    @property
    def selected_lanes_file(self) -> Path:
        return self.selected_lanes_dir / f"{self.repetition}chargingstations.xml"

    @property
    def sorted_cars_file(self) -> Path:
        return self.sorted_cars_dir / f"sortedCars{self.repetition}.xml"

    @property
    def cfg_file(self) -> Path:
        return self.folder / f"cologne{self.repetition}.sumo.cfg"

    @property
    def add_file(self) -> Path:
        return self.folder / f"cologne{self.repetition}.add.xml"

    @property
    def trips_file(self) -> Path:
        return self.folder / f"cologne6to8-{self.repetition}.trips.xml"

    @property
    def log_file(self) -> Path:
        return self.folder / f"log{self.repetition}{self.percentage}percentage{self.cs_amount}cs.xml"

    @property
    def tripinfo_output_file(self) -> Path:
        return (
            self.folder
            / f"{self.repetition}simulation{self.percentage}percentual{self.cs_amount}cs.xml"
        )

    @property
    def battery_output_file(self) -> Path:
        """
        XML com o estado da bateria (capacidade atual, potência de carga
        etc.) de cada veículo elétrico a cada passo de simulação --
        --battery-output do SUMO. É o jeito mais direto de conferir se os
        carros estão recarregando de verdade: a `actualBatteryCapacity` de
        um veículo deveria SUBIR durante o intervalo em que ele está parado
        na estação (setChargingStationStop), não só mostrar que ele parou
        no lugar certo.
        """
        return (
            self.folder
            / f"{self.repetition}battery{self.percentage}percentage{self.cs_amount}cs.xml"
        )

    @property
    def report_file(self) -> Path:
        return (
            self.reports_dir
            / f"REPORT-{self.repetition}file-{self.minutes}time-"
              f"{self.vehicles}vehicles-{self.max_vehicles_per_cs}maxPerCS"
        )

    # -- manifesto -----------------------------------------------------
    @property
    def manifest_id(self) -> str:
        return (
            f"{self.approach}_{self.minutes}min_{self.cs_amount}cs_"
            f"{self.percentage}pct_{self.repetition}rep"
        )

    @property
    def manifest_path(self) -> Path:
        return config.jobs_dir(self.approach) / f"{self.manifest_id}.json"

    def write_manifest(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def from_manifest(cls, path: Path) -> "SimJob":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    def ensure_dirs(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.selected_lanes_dir.mkdir(parents=True, exist_ok=True)
        self.sorted_cars_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def is_generated(self) -> bool:
        """Os artefatos de geração (cfg/add/trips/selected lanes/sorted cars)
        já existem em disco? Usado por --skip-generation."""
        return all(
            p.exists()
            for p in (
                self.cfg_file,
                self.add_file,
                self.trips_file,
                self.selected_lanes_file,
                self.sorted_cars_file,
            )
        )
