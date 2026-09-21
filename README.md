# Do Aleatório ao Evolutivo: Comparação de Estratégias de Posicionamento de Estações de Recarga para Veículos Elétricos

Pipeline de simulação e análise para comparar estratégias de posicionamento de estações de recarga (charging stations) para veículos elétricos em uma malha viária urbana real, usando o simulador de tráfego [SUMO](https://sumo.dlr.de/) via TraCI.

## O que o projeto faz

Dada uma malha viária (a rede de Colônia/Cologne, incluída em `input/cologne.net.xml`) e um fluxo de tráfego real (`input/cologne6to8.trips.xml`), o projeto:

1. Escolhe um conjunto de faixas (lanes) da malha para receberem estações de recarga, segundo 5 estratégias diferentes.
2. Roda uma simulação de tráfego completa no SUMO, com uma fração dos veículos precisando recarregar durante o trajeto.
3. Registra métricas de desempenho da simulação (tempo de rota, tempo de espera, engarrafamentos, etc.).
4. Repete esse processo em grade, variando percentual de veículos elétricos, quantidade de estações e janela de recarga, com múltiplas repetições por combinação.
5. Analisa os resultados estatisticamente para comparar as estratégias entre si e contra uma baseline sem estações.

## Estratégias de posicionamento

| Estratégia | Ideia |
|---|---|
| `random` | Sorteia faixas aleatoriamente entre as conexões da malha. |
| `pseudorandom` | Sorteia faixas aleatoriamente dentro de quadrantes geográficos da malha, distribuindo estações espacialmente. |
| `greedy` | Escolhe as faixas mais visitadas pelo tráfego em cada quadrante, com fallback para o centro geométrico do quadrante quando não há dado de visitação. |
| `greedyvoronoi` | Particiona a malha em regiões de Voronoi e escolhe, em cada região, a faixa mais visitada (ou a mais próxima do núcleo da região, como fallback). |
| `genetic` | Usa um algoritmo genético (evoluindo populações de conjuntos de estações) para maximizar uma função de fitness sobre a cobertura da malha. |

Em todas as estratégias, uma estação só é posicionada em uma faixa que tenha conexão de saída própria — evitando que um veículo fique permanentemente preso ao parar para recarregar.

## Estrutura do projeto

```
input/
├── cologne.net.xml                      # malha viária (rede SUMO) de Colônia
├── cologne6to8.trips.xml                # fluxo de veículos usado na simulação
├── cologne6to8.sumocfg                  # arquivo de configuração da simulação (SUMO)
├── electric_vehicle.xml                 # parâmetros do modelo de veículo elétrico
├── cologne_landmark_distances.txt       # distâncias de referência na malha
├── lanesInEachQuadrant/                 # faixas de cada quadrante, uma lista por cs_amount (9/16/25/36/49)
├── mostVisitedLanesInEachQuadrant/      # ranking de faixas mais visitadas por quadrante (usado pelo greedy/greedyvoronoi)
└── exhaustive_genetic{9,16,25,36,49}/   # checkpoints e resultados do grid search do algoritmo genético, por cs_amount

MD/
├── cli.py                       # ponto de entrada: comandos `batch` (roda a grade inteira) e `run` (roda um job específico)
├── config.py                    # parâmetros do experimento: grade (janelas, percentuais, cs_amounts, repetições), caminhos, timeouts
├── sim_job.py                   # define um job de simulação (approach, cs_amount, percentage, repetition) e seu manifesto
├── simulation.py                # roda uma simulação individual via TraCI, aplicando as estações escolhidas
├── graph_utils.py                # constrói o grafo da malha (componente fortemente conexo) e a conectividade de faixas específicas
├── seed_registry.py             # controla as seeds de sorteio de trips, garantindo reprodutibilidade entre execuções
├── quadrants.py                 # divide a malha viária em quadrantes geográficos
├── quadrants_check.py           # valida a atribuição de faixas aos quadrantes
├── io_utils.py                  # utilitários de leitura/escrita de arquivos do projeto
└── station_strategies/
    ├── __init__.py               # registro das 5 estratégias disponíveis
    ├── base.py                   # interface comum que toda estratégia de posicionamento implementa
    ├── evolution.py               # cache das seleções de estação por seed/repetição (stations_evolution/)
    ├── random_strategy.py         # estratégia `random`
    ├── pseudorandom_strategy.py   # estratégia `pseudorandom`
    ├── greedy_strategy.py         # estratégia `greedy`
    ├── greedy_voronoi_strategy.py # estratégia `greedyvoronoi`
    └── genetic_strategy.py        # estratégia `genetic`

output/                          # gerado pelas execuções, organizado por approach/janela/percentual/cs_amount
```

## Como rodar

```bash
cd MD
python3 cli.py batch --approach <random|pseudorandom|greedy|greedyvoronoi|genetic>
python3 cli.py run --approach <approach> --minutes <10|20|40|60> --percentage <5..30> --cs-amount <9|16|25|36|49> --repetition <1..5>
```

O comando `batch` gera e roda a grade inteira (ou o que ainda estiver pendente) para uma abordagem; `run` executa uma única combinação específica.

Flags úteis do `batch`:
- `--workers N` — número de simulações em paralelo (por padrão, detectado automaticamente por CPU e RAM disponíveis).
- `--force-rerun-all` — reprocessa todos os jobs da grade, mesmo os que já têm relatório de sucesso.

Por padrão, um job já concluído com sucesso é pulado em execuções futuras, permitindo retomar um `batch` interrompido sem refazer o que já terminou. Cada simulação tem um timeout de segurança (30h) para evitar que um veículo preso trave o processo indefinidamente; falhas do SUMO são automaticamente reexecutadas com paralelismo reduzido.

## Grade de experimentos

Para cada uma das 5 abordagens, a grade cobre:

- **Janela de recarga**: 10, 20, 40 ou 60 minutos
- **Percentual de veículos elétricos**: 5% a 30%, em passos de 5%
- **Quantidade de estações**: 9, 16, 25, 36 ou 49
- **Repetições**: 5 por combinação

Totalizando 600 simulações por abordagem.

## Métricas coletadas

Por simulação: duração média de rota, comprimento de rota, tempo de espera, tempo perdido (`time loss`), atraso de partida, número de teleportes (colisão, engarrafamento, yield, faixa errada) e paradas de emergência.

## 📊 Análise de Dados dos Resultados

A análise estatística dos resultados é feita em um notebook no Google Colab: normaliza os dados brutos, agrega por (abordagem, quantidade de estações, percentual), calcula média e intervalo de confiança de 95% (distribuição t de Student) por métrica, e compara cada abordagem contra uma baseline sem estações. Os hiperparâmetros do algoritmo genético (taxa de crossover, mutação, tamanho de população, elitismo, torneio, número de gerações) foram validados por um grid search de 729 combinações, analisando o efeito de cada parâmetro sobre o fitness e o tempo de execução.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/drive/1_nZP1TkM0w6r_qnXkJOje96UVX-2MK5J?usp=sharing)
