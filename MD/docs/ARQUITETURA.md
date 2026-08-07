# Simulação de Estações de Recarga — Documentação da Refatoração

> Projeto: alocação de estações de recarga para veículos elétricos na malha viária
> de Colônia (SUMO/TraCI), comparando 4 estratégias de posicionamento.
> Este documento descreve a arquitetura **refatorada** (em construção) e as
> decisões que a justificam, em contraste com o código original.

---

## 1. Visão geral

O projeto testa 4 estratégias diferentes de posicionamento de estações de
recarga (`random`, `pseudorandom`, `greedy`, `greedyvoronoi`) sobre o mapa de
Colônia, simulando no SUMO o comportamento do tráfego com uma fração dos
veículos precisando recarregar. O experimento varia:

- **approach** — qual estratégia de posicionamento (4 opções, 1 por servidor)
- **minutes** — tempo de recarga por veículo: 10, 20, 40, 60 min
- **cs_amount** (estações) — 9, 16, 25, 36, 49
- **percentage** — % de veículos que recarregam: 5, 10, 15, 20, 25, 30
- **repetition** — 5 repetições por combinação (1..5)

Total por approach: `4 × 5 × 6 × 5 = 600` simulações. `2400` no total,
distribuídas manualmente em 4 servidores (1 approach por servidor).

### Por que refatorar

O código original (`main.py`, `findingX.py`, `generatingX.py`, `functions.py`
etc.) cresceu organicamente: a mesma lógica (construção do grafo, escrita de
`.cfg`/`.add.xml`, sorteio de trips) foi copiada e colada em 5-7 arquivos
diferentes, com pequenas divergências de bug entre as cópias, e um pipeline
inteiro (`generatingGreedy.py`/`generatingWithRegions.py`) ficou obsoleto e
quebrado sem que isso fosse óbvio. Um levantamento função-por-função de todos
os arquivos originais identificou ~30 funções mortas (nunca chamadas) e vários
bugs reais (ver seção 7).

---

## 2. Estrutura no disco

```
TCC/
├── input/                       # config.INPUT_DIR -- dados de entrada, imutáveis
│   ├── cologne.net.xml
│   ├── cologne6to8.trips.xml
│   ├── electric_vehicle.xml
│   ├── mostVisited.xml
│   ├── cologne_landmark_distances.txt
│   └── lanesInEachQuadrant/
│       └── 49quadrants.xml      # uma das 5 malhas geradas por quadrants.py (9,16,25,36,49)
└── MD/                          # config.MD_ROOT -- todo o código roda daqui
    ├── config.py
    ├── graph_utils.py
    ├── io_utils.py
    ├── seed_registry.py
    ├── sim_job.py
    ├── station_strategies/
    │   ├── __init__.py
    │   ├── base.py
    │   ├── evolution.py
    │   ├── random_strategy.py
    │   ├── pseudorandom_strategy.py
    │   ├── greedy_strategy.py
    │   └── greedy_voronoi_strategy.py
    ├── simulation.py            # PENDENTE
    ├── cli.py                   # PENDENTE
    └── output/                  # config.OUTPUT_DIR
        └── <approach>/...       # ver seção 6
```

Todos os paths em `config.py` são derivados de `Path(__file__).resolve().parent`
— não dependem de onde/como o script é chamado (o código original tinha
`"../input"`, `"../../input"`, `"../../../input"` conflitantes entre arquivos,
dependendo da profundidade de quem chamava).

---

## 3. Módulos

### `config.py`
Fonte única de verdade para paths e para o grid do experimento
(`APPROACHES`, `MINUTES_RECHARGING`, `STATIONS_AMOUNTS`, `PERCENTAGES`,
`REPETITIONS`), além de constantes de infraestrutura do SUMO
(`CHARGING_POWER_W`, `CHARGE_DELAY_S`, `ROUTING_THREADS` etc.) que antes
estavam hardcoded e duplicadas em vários arquivos.

### `seed_registry.py`
Duas seeds **independentes** por approach (ver seção 5):

- `StationSeedRegistry` — uma seed por `repetition`, representa uma
  "evolução da cidade" completa (todos os `cs_amount`, `percentage`,
  `minutes` de uma repetição compartilham a mesma seed de estação).
- `TripSeedRegistry` — uma seed por `(percentage, repetition)`, usada só no
  sorteio de veículos que recarregam.

Cada registro é persistido em JSON (`seeds_stations_registry.json`,
`seeds_trips_registry.json`), com escrita atômica (`os.replace`). A seed é
sorteada (`secrets.randbits`) na primeira vez que a chave aparece, e
reaproveitada sempre depois — isso é o que permite reexecutar manualmente uma
simulação que o SUMO derrubou no meio, de forma bit-a-bit idêntica.

### `sim_job.py`
`SimJob`: dataclass que representa uma simulação específica
`(approach, minutes, cs_amount, percentage, repetition, vehicles,
max_vehicles_per_cs, seed)`. Todos os paths de output de um job (`.cfg`,
`.add.xml`, `.trips.xml`, `selectedLanes/`, `sortedCars-N/`, `reports/`) são
propriedades derivadas daqui — nunca string concatenada na mão. Também
resolve o manifesto (`write_manifest`/`from_manifest`), usado para
reexecução manual de um job específico.

### `graph_utils.py`
Construção do grafo de roteamento a partir do `.net.xml` (substituindo as 7
cópias que existiam no código original), mais os helpers:
- `list_connections()` — tags `<connection>` cruas (usado pelo `random`)
- `lane_lengths()` — comprimento de cada lane, lido estaticamente do
  `.net.xml` (substitui a checagem `traci.lane.getLength` que exigia SUMO
  já rodando)
- `default_graph()` / `get_giant_component()` — cache por processo,
  componente fortemente conexo

### `io_utils.py`
Leitura/escrita de todos os arquivos que o SUMO consome: `.sumo.cfg`,
`.add.xml`, arquivo de lanes selecionadas, sorteio de trips por percentual,
e leitura do comprimento do veículo (`vehicle_length`, do
`electric_vehicle.xml`). Escrita via `xml.etree.ElementTree` (não mais
`f.write()` linha a linha) e sempre atômica (arquivo `.tmp` + `replace`).

### `station_strategies/`
Uma estratégia por approach, todas com a mesma assinatura
`select_charging_points(job: SimJob, graph) -> set[str]`, registradas em
`station_strategies.REGISTRY`. Isso substitui o
`os.system("python3 findingX.py ...")` do `main.py` original por uma
chamada direta em processo.

- **`random_strategy.py`** — sorteia trincas de `<connection>`, valida
  ciclo alcançável no grafo, aceita a lane do meio.
- **`pseudorandom_strategy.py`** — usa a malha de quadrantes do mesmo
  tamanho que `cs_amount` (`lanesInEachQuadrant/9quadrants.xml` para 9
  estações, `16quadrants.xml` para 16, ...), sorteia 3 lanes por quadrante
  e valida ciclo + capacidade mínima (`lane_length / vehicle_length >=
  max_vehicles_per_cs`). Sem crescimento incremental (ver seção 5.3).
- **`greedy_strategy.py`** — determinística, sem seed: associa as lanes
  mais visitadas (`mostVisited.xml`) à primeira quadrante ainda vazia que
  as contém.
- **`greedy_voronoi_strategy.py`** — sorteia pontos aleatórios, monta um
  diagrama de Voronoi (scipy), associa lanes mais visitadas às regiões.
- **`evolution.py`** — mecanismo compartilhado de cache/cascata do
  crescimento incremental (ver seção 5).

---

## 4. `simulation.py` e `cli.py`

| Arquivo | Papel |
|---|---|
| **`simulation.py`** | Núcleo de simulação migrado de `main.py` (`run`/`decide`/`reroute`/`dict_trip`/`readChargingStations`). Import de `traci`/`sumolib` é tardio (só dentro de `run_simulation`) -- não exige `SUMO_HOME` para importar o módulo ou usar as funções puras. |
| **`cli.py`** | Entrypoint único: `cli.py batch --approach X` (gera+roda o grid inteiro, combinação por combinação) e `cli.py run --from-manifest ...` / `cli.py run --approach ... --minutes ... [--skip-generation]` (uma simulação específica, para reexecução manual). |

### Duas correções importantes feitas em `simulation.py`

1. **Silenciamento de erro do original**: `main.py` capturava `traci.exceptions.FatalTraCIError` com um `print` e devolvia sucesso mesmo assim -- o relatório era escrito como "FIM DA SIMULAÇÃO" normalmente, sem jeito de saber de fora que aquela simulação específica tinha travado. Agora o erro é gravado no relatório **e relançado**, permitindo ao `cli.py` (e a você) saber exatamente quais jobs precisam ser reexecutados.
2. **Parsing de `sortedCarsN.xml`**: o `dict_trip` original usava `split()`/`strip()` por espaço, que corrompia o último atributo da linha quando não havia espaço antes de `/>` (`to="e52"/>` virava `e52"/>`). Trocado por regex por atributo.

### Decisões assumidas em `cli.py` (sem confirmação explícita seguindo em frente)

- **Ordem de execução**: loop aninhado natural `minutes > cs_amount > percentage`, sequencial entre combinações, 5 repetições em paralelo dentro de cada uma. O `running.py` original executava na ordem **inversa** dessa (por causa de um `pop()` no fim da lista) -- se você quiser preservar esse comportamento ou definir outra ordem, é só avisar que ajusto.
- **Paralelismo**: por padrão, até 5 processos simultâneos por combinação (uma por repetição -- é o máximo que dá pra paralelizar dentro de uma combinação, dado o desenho "gera o conjunto, depois roda o conjunto" que você pediu). Isso deixa boa parte dos 48 cores ociosa a maior parte do tempo; se quiser aproveitar mais hardware, dá pra evoluir para gerar/rodar mais de uma combinação ao mesmo tempo, mas isso não está implementado ainda.
- **Porta TraCI**: `traci.start(cmd, port=job.port)` com `job.port=None` por padrão -- o próprio TraCI escolhe uma porta livre por processo, o que já evita conflito entre simulações paralelas sem nenhuma coordenação manual.

---

## 5. Pendente

Só housekeeping, não mais código novo:
- Apagar os arquivos legados já substituídos (`findingX.py`, `generatingX.py`, `running.py`, `teste.py`, `main.py`, `functions.py`, `generating_genetic.py` vazio).
- `genetic_algorithm.py` não foi integrado ao `station_strategies/` -- ele já é bastante autocontido/limpo; se quiser, dá pra empacotar como uma 5ª estratégia depois.

---

## 5. Modelo de seeds e crescimento incremental

### 5.1 Duas seeds desacopladas

| Seed | Escopo | Controla |
|---|---|---|
| **Seed de estação** | `(approach, repetition)` para `random`; `(approach, repetition, cs_amount)` para `pseudorandom`/`greedyvoronoi` (ver 5.3) | Onde as estações ficam. |
| **Seed de trips** | `(approach, percentage, repetition)` | Quais veículos são sorteados para recarregar. Independente de `cs_amount`/`minutes`. |

Justificativa: a posição de uma estação não deveria depender de quantos
veículos recarregam nem de quanto tempo demora a recarga; e vice-versa. Antes
da refatoração, uma única seed cobria tudo junto, o que impedia comparações
"limpas" entre variações de um único parâmetro.

### 5.2 Por que "10min" e "20min" têm a mesma seleção de estação

`minutes` (tempo de recarga) nunca entra na seed de estação nem na de trips —
então, para uma dada `(cs_amount, percentage, repetition)`, as 4 pastas
`10min/20min/40min/60min` têm exatamente a mesma seleção de estações e os
mesmos veículos sorteados. A única variável que muda entre elas é a duração
de recarga em si (`traci.vehicle.setChargingStationStop(..., duration=...)`).
Isso viabiliza uma **comparação pareada**: qualquer diferença de resultado
entre `10min` e `20min` só pode vir do tempo de recarga.

> No código original, `minutes` não entrava no nome da pasta de output
> (`{percentage}percentage{cs}cs/`), então rodar o mesmo `(percentage, cs,
> repetition)` duas vezes com `minutes` diferentes **sobrescrevia** o
> `.cfg`/`.add.xml`/`.trips.xml`/tripinfo da execução anterior — só o
> `REPORT-...{time}time...` (que tinha `time` no nome) sobrevivia intacto,
> descrevendo arquivos que já não existiam mais. Corrigido adicionando o
> nível `<minutes>min/` na estrutura de pastas.

### 5.3 Crescimento incremental de estações (9 → 16 → 25 → 36 → 49)

Requisito: cada seed representa uma "evolução da cidade" — ao aumentar o
número de estações, as posições já escolhidas **nunca mudam**, só se
adicionam novas.

| Tier | Estações totais | Novas nesta etapa |
|---|---|---|
| 1 | 9 | 9 (do zero) |
| 2 | 16 | +7 |
| 3 | 25 | +9 |
| 4 | 36 | +11 |
| 5 | 49 | +13 |

Mecanismo (`station_strategies/evolution.py`):

1. Cada estágio é persistido em
   `output/<approach>/stations_evolution/seed_<repetition>/<cs>stations.xml`
   — independente de `percentage`/`minutes` (a seleção de estação não
   depende deles).
2. Ao pedir um `cs_amount`, o sistema verifica se esse estágio já existe em
   disco. Se sim, devolve direto (sem recalcular).
3. Se não existe, garante recursivamente que o estágio **anterior** (o maior
   valor de `STATIONS_AMOUNTS` menor que o pedido) já existe, e pede à
   estratégia só a diferença (`extend_fn(already_chosen, target)`).
4. Cada `extend_fn` tem a garantia: nunca remove nada de `already_chosen`,
   só adiciona até atingir `target`.
5. Depois de calculado, valida com um `assert`/erro explícito que o
   resultado contém o estágio anterior por inteiro, e persiste.

Isso significa que pedir diretamente `cs_amount=25` (sem nunca ter gerado 9
ou 16 antes) já constrói a cadeia inteira sozinho, na ordem certa, uma vez só
— não precisa gerar tier por tier manualmente.

**Por que cada approach ficou diferente:**

- **`random`**: **tem crescimento incremental**. O algoritmo já era, por
  natureza, uma amostragem sequencial sem nenhuma dependência do `target`
  nas decisões de aceitar/rejeitar um candidato — reaproveitar
  `already_chosen` e continuar sorteando "encaixa" sem mudança estrutural.
  Usa `StationSeedRegistry.apply(repetition)` (seed só por repetição,
  compartilhada entre todos os `cs_amount`).
- **`pseudorandom`**: **sem crescimento incremental, revertido por decisão
  explícita** (mesma razão do `greedyvoronoi` abaixo). Usa a malha de
  quadrantes do mesmo tamanho que `cs_amount` (`9quadrants.xml` para 9,
  `16quadrants.xml` para 16, ...) — malhas espaciais sem relação entre si,
  então nem a mesma seed preserva as estações antigas ao crescer (a
  sequência de números aleatórios é igual, mas aplicada a uma estrutura de
  dados diferente a cada tamanho). Seed por `(repetition, cs_amount)`,
  igual ao `greedyvoronoi`.
- **`greedyvoronoi`**: **sem crescimento incremental, por decisão explícita** —
  cada `cs_amount` sorteia seu próprio diagrama de Voronoi do zero, de
  forma independente (mesmo comportamento do código original). A seed de
  estação, para este approach, inclui `cs_amount` na chave
  (`StationSeedRegistry.apply(repetition, cs_amount)`). Isso ainda garante
  que `10min/20min/40min/60min` de um mesmo `(cs_amount, repetition)` usem
  a mesma seleção entre si (comparação pareada no tempo de recarga), só
  não entre `cs_amount` diferentes.
- **`greedy`**: fora do escopo dessas mudanças (não usa seed — é
  determinístico já). Estruturalmente tem o mesmo problema de malha
  variável por `cs_amount`, mas não foi alterado por não ter sido pedido.

Tanto `pseudorandom` quanto `greedyvoronoi` cacheiam o resultado em disco
por `(approach, repetition, cs_amount)` (mesmo local de arquivo que os
estágios do `random`, só que aqui cada `cs_amount` é independente, não uma
cadeia) — não recalculam à toa entre `percentage`/`minutes` diferentes.

---

## 6. Estrutura de output

```
output/<approach>/
├── seeds_stations_registry.json      # {"1rep": 3271958341, "2rep": ..., ...}
├── seeds_trips_registry.json         # {"20pct_1rep": ..., ...}
├── stations_evolution/
│   └── seed_<repetition>/
│       ├── 9stations.xml
│       ├── 16stations.xml
│       ├── 25stations.xml
│       ├── 36stations.xml
│       ├── 49stations.xml
│       └── (greedyvoronoi grava um estágio por cs_amount aqui também, mas sem cadeia entre eles)
├── jobs/                             # manifestos de cada SimJob (reexecução manual) -- PENDENTE (cli.py)
└── <minutes>min/
    └── <percentage>percentage<cs>cs/
        ├── cologneN.add.xml
        ├── cologneN.sumo.cfg
        ├── cologne6to8-N.trips.xml
        ├── Nsimulation<percentage>percentual<cs>cs.xml   # tripinfo do SUMO
        ├── logN<percentage>percentage<cs>cs.xml           # log do SUMO
        ├── reports/REPORT-Nfile-Ttime-Vvehicles-Mmax...
        ├── selectedLanes/Nchargingstations.xml            # cópia do estágio compartilhado, para este job
        └── sortedCars-<vehicles>/sortedCarsN.xml

output/greedyvoronoi/voronoiStations/       # diagnóstico (png + flag) por seed_<repetition>_<cs>stations
```

Essa é a mesma estrutura de pastas do projeto atual (confirmada a partir do
seu `output.zip`), com dois acréscimos: o nível `<minutes>min/` (seção 5.2) e
`stations_evolution/` (seção 5.3).

---

## 7. Bugs do código original corrigidos na refatoração

| # | Onde | Bug | Correção |
|---|---|---|---|
| 1 | `findingPseudoRandom.py`, `findingRandom.py`, `generatingGreedy.py`, `generatingPseudoRandom.py` | ~4 cópias de `sortear_numero`/`extrair_linhas_sorteadas`/`sortCarsAndTrips` nunca chamadas (código morto) | Removido; substituído por `io_utils.sample_trips` |
| 2 | `main.py` | ~11 funções mortas (bateria, tripinfo, `originalRoute`) — chamadas comentadas em `run()` | Não migradas para `simulation.py` |
| 3 | `findingStationsGreedyVoronoi.py` | `createSelectedCSFiles` local duplicada e quebrada (`os.path(path)` não é chamável) | Removida; usa só `io_utils.write_selected_lanes_file` |
| 4 | `generatingGreedy.py`, `generatingWithRegions.py` | Chamavam `findingStationsGreedy.py`/`findingStationsGreedyVoronoi.py` via subprocess sem passar `-cs`/`-fd`/`-f` obrigatórios → crash garantido | Pipeline descontinuado; `station_strategies/` chama direto em processo, sem subprocess |
| 5 | Vários arquivos | Paths relativos (`"../input"`, `"../../input"`, `"../../../input"`) dependentes de quem chamava o script | `config.py` ancorado em `Path(__file__)` |
| 6 | `findingPseudoRandom.py` | Checagem de capacidade da estação via `traci.lane.getLength`/`traci.vehicletype.getLength` — exige SUMO já rodando | `graph_utils.lane_lengths()` + `io_utils.vehicle_length()`, leitura estática do XML |
| 7 | `findingStationsGreedyVoronoi.py` | PNG de diagnóstico salvo em path global por `cs_amount`, sobrescrito a cada repetição | Nome inclui `seed_<repetition>_<cs>stations` |
| 8 | `findingRandom.py` | Pool de `cs*5` candidatos gerado uma vez, 5 repetições reaproveitando os mesmos primeiros elementos → repetições idênticas | Cada repetição sorteia de forma independente (seed própria) |
| 9 | `functions.py` vs `generatingGreedy.py` | Duas versões de `extract_lanes_from_xml` (`.//lane` recursivo vs `lane` direto), resultados diferentes para o mesmo tipo de arquivo | Unificado em `io_utils.read_selected_lanes_file` (recursivo) |
| 10 | `running.py` | Nome do log não inclui `approach`/`repetition` → execuções concorrentes sobrescrevem o log umas das outras | A ser resolvido no manifesto de job do `cli.py` (pendente) |
| 11 | `running.py` | `command_lines.pop()` executa na ordem **inversa** dos loops de geração (LIFO) | A definir explicitamente no `cli.py` (pendente) |
| 12 | `teste.py` | `-cs 49> arquivo.log` sem espaço antes do `>` — bash interpreta como redirecionamento do file descriptor 49, não do stdout | N/A (script de teste manual, não migrado) |
| 13 | `output.zip` (evidência) | `cologneNone.sumo.cfg`, `REPORT-Nonefile-...` — argumentos obrigatórios faltando viraram `None` no nome do arquivo, sem erro | `SimJob` é uma dataclass tipada; falha cedo se faltar campo |

---

## 8. Grid de experimentos (referência rápida)

```python
APPROACHES = ("random", "pseudorandom", "greedy", "greedyvoronoi")
MINUTES_RECHARGING = (10, 20, 40, 60)
STATIONS_AMOUNTS = (9, 16, 25, 36, 49)
PERCENTAGES = (5, 10, 15, 20, 25, 30)
REPETITIONS = (1, 2, 3, 4, 5)
```

4 servidores, 1 approach fixo por servidor. Por servidor:
`4 × 5 × 6 × 5 = 600` simulações. Total: `2400`.

---

## 10. Como rodar

Dentro de `TCC/MD/`, com `SUMO_HOME` definido e `sumo`/`sumo-gui` no PATH:

```bash
# Roda o grid inteiro de um approach (1 processo por servidor, 1 approach cada)
python3 cli.py batch --approach greedy
python3 cli.py batch --approach greedyvoronoi --workers 5

# Reexecuta manualmente um job específico que falhou (lido do manifesto gravado)
python3 cli.py run --from-manifest output/greedy/jobs/greedy_10min_16cs_20pct_3rep.json

# Reexecuta um job específico sem regerar os arquivos (.cfg/.add/.trips já existem)
python3 cli.py run --from-manifest output/greedy/jobs/greedy_10min_16cs_20pct_3rep.json --skip-generation

# Roda uma simulação pontual direto por parâmetros (sem depender de manifesto)
python3 cli.py run --approach random --minutes 20 --cs 25 --percentage 15 --repetition 2
```

Ao final de um `batch`, o log (`output/<approach>/cli.log`) termina com a lista exata de
`manifest_id`s que falharam, prontos para reexecutar com `run --from-manifest`.

## 11. Glossário

- **Job (`SimJob`)** — uma combinação específica `(approach, minutes,
  cs_amount, percentage, repetition)`; a unidade atômica de trabalho.
- **Tier** — um valor de `cs_amount` dentro da sequência incremental de uma
  seed de estação (9 → 16 → 25 → 36 → 49).
- **Evolução (da cidade)** — a sequência completa de tiers de uma mesma
  seed de estação; representa um cenário plausível de expansão da
  infraestrutura de recarga.
- **Estratégia (`station_strategies`)** — o algoritmo de posicionamento de
  estações de um approach.
- **Manifesto** — o JSON de um `SimJob`, persistido para permitir
  reexecução manual determinística caso o SUMO trave no meio de uma
  simulação (mecanismo do `cli.py`, pendente).
