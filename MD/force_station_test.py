"""
force_station_test.py -- diagnóstico manual: gera e roda UMA simulação com
uma lane específica forçada como a única estação de recarga, ignorando
completamente a station strategy (random/pseudorandom/etc). Útil pra testar
comportamento de capacidade (parkingArea + roadsideCapacity) numa lane
curta escolhida à mão, sem depender do sorteio.

Edite LANE_ID, MAX_VEHICLES_PER_CS e os outros parâmetros abaixo antes de
rodar. Depois:

    cd MD/
    python3 force_station_test.py
"""
from __future__ import annotations

import config
import io_utils
import simulation
from sim_job import SimJob

# ---------------------------------------------------------------------------
# EDITE AQUI
# ---------------------------------------------------------------------------
LANE_ID = "-241721325#1_0"   # ex: "24449420_0"
MAX_VEHICLES_PER_CS = 20                     # propositalmente alto p/ testar overflow
MINUTES = 60
PERCENTAGE = 50                              # alto, p/ forçar vários carros na mesma estação
REPETITION = 1
VEHICLES = 98                             # usa o arquivo de trips pequeno, se já tiver trocado
SUMO_COMMAND = "sumo-gui"
# ---------------------------------------------------------------------------

job = SimJob(
    approach="random",  # só rótulo p/ organizar pastas -- a estratégia real nunca é chamada
    minutes=MINUTES, cs_amount=1, percentage=PERCENTAGE, repetition=REPETITION,
    vehicles=VEHICLES, max_vehicles_per_cs=MAX_VEHICLES_PER_CS, seed=0,
)
job.ensure_dirs()

lanes = {LANE_ID}
io_utils.write_selected_lanes_file(job, lanes)
io_utils.write_add_file(job, lanes)   # aqui que o roadsideCapacity=MAX_VEHICLES_PER_CS entra
io_utils.sample_trips(job)
io_utils.write_cfg_file(job)

print(f"Rodando com estação forçada em '{LANE_ID}', capacidade={MAX_VEHICLES_PER_CS}...")
simulation.run_simulation(job, sumo_command=SUMO_COMMAND)
