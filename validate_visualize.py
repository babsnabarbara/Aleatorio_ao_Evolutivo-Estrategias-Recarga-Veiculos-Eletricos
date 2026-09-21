"""
validate_and_visualize_dispositions.py -- vive na RAIZ de TCC/ (não em
MD/), diferente dos outros scripts de análise.

Faz duas coisas, em sequência:

1. VALIDAÇÃO: para cada (approach, cs_amount), confere -- lendo direto os
   .add.xml já gerados em disco, não confiando só no cache -- se a
   disposição de estações é IDÊNTICA em todas as combinações de
   minutes/percentage já geradas, PARA CADA repetição (a posição de uma
   estação não deveria variar com minutes/percentage, só entre repetições
   diferentes -- ver config.station_evolution_dir). Grava
   disposition/disposition_validation_report.txt com "sim"/"nao" por
   (approach,
   cs_amount).

2. VISUALIZAÇÃO: para os pares (approach, cs_amount) que passarem 100% na
   validação (todas as repetições com dado gerado sendo consistentes),
   gera um .png por (approach, cs_amount, repetition) -- um ponto vermelho
   em cada localização de estação, no mesmo estilo do diagnóstico que
   station_strategies/greedy_voronoi_strategy.py já gera para o Voronoi.

Combinações sem NENHUM dado gerado ainda são puladas (não contam como
"nao" -- aparecem como "sem dado gerado ainda" no relatório).

Uso (de dentro de TCC/, não de MD/):

    python3 validate_and_visualize_dispositions.py
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

TCC_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(TCC_ROOT / "MD"))  # para importar config.py/io_utils.py de lá

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

import config  # noqa: E402

FOLDER_RE = re.compile(r"^(\d+)percentage(\d+)cs$")
MINUTES_DIR_RE = re.compile(r"^(\d+)min$")

# approaches cuja seleção de estação de fato respeita a malha de quadrantes
# (greedy_voronoi usa regiões de Voronoi, não quadrante; random/genetic não
# usam nenhuma partição espacial) -- só esses dois se beneficiam de buscar
# um ponto DENTRO do quadrante correto pra plotar; nos outros 3, a grade
# desenhada é só referência visual, então usar o primeiro ponto já basta.
USES_QUADRANTS = {"pseudorandom", "greedy"}


def _lanes_and_coordinates() -> dict[str, list[tuple[float, float]]]:
    """{lane_id: [(x, y), ...]} -- mesmo parsing usado em
    greedy_voronoi_strategy.py, duplicado aqui de propósito (este script
    fica fora de MD/, então não importa station_strategies diretamente)."""
    root = ET.parse(config.NET_FILE).getroot()
    lanes: dict[str, list[tuple[float, float]]] = {}
    for edge in root.findall(".//edge[@type]"):
        for lane in edge.findall("./lane"):
            coords_raw = lane.attrib["shape"].split(" ")
            points = []
            for pair in coords_raw:
                if not pair.strip():
                    continue
                x_str, y_str = pair.split(",")
                points.append((float(x_str), float(y_str)))
            lanes[lane.attrib["id"]] = points
    return lanes


def _lane_start_point(lane_id: str, lanes_and_coords: dict) -> tuple[float, float] | None:
    """Devolve o PRIMEIRO ponto da forma da lane -- usado só pros
    approaches que NÃO têm um quadrante "correto" conhecido pra procurar
    um ponto dentro dele (random/genetic/greedyvoronoi; a grade nesses
    casos é só referência visual, não algo que o approach respeita de
    verdade -- ver plot_disposition)."""
    points = lanes_and_coords.get(lane_id)
    if not points:
        return None
    return points[0]


def _load_lane_quadrant_membership(cs_amount: int) -> dict[str, list[tuple[int, int]]]:
    """
    {lane_id: [(quadrant_x, quadrant_y), ...]} -- a que quadrante(s) cada
    lane pertence, segundo o PRÓPRIO arquivo <cs_amount>quadrants.xml
    (cada <quadrant x=".." y="..."> já guarda seu índice de célula na
    grade -- ver quadrants.py::criar_elemento_quadrant). Uma lane pode
    pertencer a mais de um quadrante (rua comprida que cruza a linha de
    divisão -- ver quadrants.py::dividir_em_quadrants, que atribui por
    PONTO, não por rua inteira).
    """
    quadrants_file = config.LANES_IN_EACH_QUADRANT_DIR / f"{cs_amount}quadrants.xml"
    if not quadrants_file.exists():
        return {}

    membership: dict[str, list[tuple[int, int]]] = {}
    root = ET.parse(quadrants_file).getroot()
    for quadrant in root.findall(".//quadrant"):
        qx, qy = int(quadrant.get("x")), int(quadrant.get("y"))
        for lane_elem in quadrant.findall("lane"):
            if lane_elem.text:
                membership.setdefault(lane_elem.text, []).append((qx, qy))
    return membership


def _point_in_correct_quadrant(lane_id: str, lanes_and_coords: dict,
                                membership: dict, conv_boundary: tuple,
                                cs_amount: int) -> tuple[float, float] | None:
    """
    Devolve um ponto da forma da lane que realmente cai DENTRO de um dos
    quadrantes aos quais ela pertence (segundo o arquivo de quadrantes) --
    em vez de só pegar o primeiro ponto (que pode, por acaso, cair num
    quadrante diferente do que essa lane efetivamente representa, se a rua
    for longa o suficiente pra cruzar mais de uma linha de divisão).

    Se a lane não pertencer a nenhum quadrante conhecido (não deveria
    acontecer, mas por segurança) ou nenhum ponto bater com os quadrantes
    listados, cai de volta pro primeiro ponto.
    """
    points = lanes_and_coords.get(lane_id)
    if not points:
        return None

    quadrant_cells = membership.get(lane_id)
    if not quadrant_cells:
        return points[0]

    x_min, y_min, x_max, y_max = conv_boundary
    quadrant_raiz = int(round(cs_amount ** 0.5))
    tam_x = (x_max - x_min) / quadrant_raiz
    tam_y = (y_max - y_min) / quadrant_raiz

    quadrant_cells_set = set(quadrant_cells)
    for x, y in points:
        qx = min(int((x - x_min) / tam_x), quadrant_raiz - 1)
        qy = min(int((y - y_min) / tam_y), quadrant_raiz - 1)
        if (qx, qy) in quadrant_cells_set:
            return x, y

    return points[0]  # nenhum ponto bateu -- fallback, não deveria acontecer


def _conv_boundary() -> tuple[float, float, float, float]:
    """(x_min, y_min, x_max, y_max) do mapa -- mesmo campo que
    quadrants.py usa pra dividir em quadrantes, e que
    greedy_voronoi_strategy.py usa pra sortear os pontos do diagrama."""
    root = ET.parse(config.NET_FILE).getroot()
    conv_boundary = root.find(".//location").attrib["convBoundary"]
    x_min, y_min, x_max, y_max = map(float, conv_boundary.split(","))
    return x_min, y_min, x_max, y_max


def find_station_sets(approach: str, cs_amount: int,
                       repetition: int) -> dict[tuple[int, int], set[str]]:
    """
    {(minutes, percentage): {lane_ids...}} -- uma entrada por combinação
    de minutes/percentage já gerada em disco para essa (approach,
    cs_amount, repetition). Lê direto dos .add.xml (fonte de verdade real,
    não o cache) -- é isso que permite detectar qualquer inconsistência
    real que tenha acontecido, em vez de só reafirmar o que o cache diz.
    """
    approach_dir = config.OUTPUT_DIR / approach
    result: dict[tuple[int, int], set[str]] = {}
    if not approach_dir.exists():
        return result

    for minutes_dir in sorted(approach_dir.glob("*min")):
        m = MINUTES_DIR_RE.match(minutes_dir.name)
        if not m:
            continue
        minutes = int(m.group(1))

        for combo_dir in sorted(minutes_dir.glob("*percentage*cs")):
            fm = FOLDER_RE.match(combo_dir.name)
            if not fm:
                continue
            percentage, folder_cs = int(fm.group(1)), int(fm.group(2))
            if folder_cs != cs_amount:
                continue

            add_path = combo_dir / f"cologne{repetition}.add.xml"
            if not add_path.exists():
                continue

            root = ET.parse(add_path).getroot()
            lanes = {pa.get("lane") for pa in root.findall(".//parkingArea")}
            result[(minutes, percentage)] = lanes

    return result


def validate_disposition(approach: str, cs_amount: int) -> tuple[bool, bool, list[str]]:
    """
    Devolve (algo_foi_gerado, passou_em_tudo, detalhes_dos_problemas).

    Confere, PARA CADA repetição com dado gerado, se todas as combinações
    de minutes/percentage já geradas compartilham a MESMA disposição.
    Repetições sem nenhum dado gerado são ignoradas (não contam nem a
    favor nem contra).
    """
    algo_gerado = False
    problemas: list[str] = []

    for repetition in config.REPETITIONS:
        sets_by_combo = find_station_sets(approach, cs_amount, repetition)
        if not sets_by_combo:
            continue
        algo_gerado = True

        unique_sets = {frozenset(s) for s in sets_by_combo.values()}
        if len(unique_sets) > 1:
            exemplos = list(sets_by_combo.items())[:2]
            problemas.append(
                f"repetition={repetition}: {len(unique_sets)} disposições "
                f"DIFERENTES entre as {len(sets_by_combo)} combinações de "
                f"minutes/percentage já geradas (ex: "
                f"{exemplos[0][0]}={len(exemplos[0][1])} estações vs "
                f"{exemplos[1][0]}={len(exemplos[1][1])} estações)"
            )

    return algo_gerado, (len(problemas) == 0), problemas


def plot_disposition(approach: str, cs_amount: int, repetition: int, lanes: set[str],
                      lanes_and_coords: dict, road_segments: list, conv_boundary: tuple,
                      out_dir: Path) -> None:
    xs, ys, sem_coordenada = [], [], 0

    if approach in USES_QUADRANTS:
        membership = _load_lane_quadrant_membership(cs_amount)
    else:
        membership = {}

    for lane_id in lanes:
        if approach in USES_QUADRANTS:
            point = _point_in_correct_quadrant(
                lane_id, lanes_and_coords, membership, conv_boundary, cs_amount
            )
        else:
            point = _lane_start_point(lane_id, lanes_and_coords)

        if point is None:
            sem_coordenada += 1
            continue
        xs.append(point[0])
        ys.append(point[1])

    x_min, y_min, x_max, y_max = conv_boundary

    fig, ax = plt.subplots(figsize=(8, 8))

    # mapa de fundo -- todas as ruas do net.xml, cinza claro, atrás de tudo.
    # LineCollection desenha os milhares de segmentos numa chamada só (bem
    # mais rápido que um ax.plot() por rua, que ficaria lento demais pra
    # gerar 125 imagens).
    road_lines = LineCollection(road_segments, colors="lightgray", linewidths=0.5, zorder=1)
    ax.add_collection(road_lines)

    # divisão em quadrantes -- mesma malha que quadrants.py usa
    # (quadrant_raiz = sqrt(cs_amount), grade uniforme sobre o convBoundary).
    # Desenhada pra TODOS os approaches, não só random/greedy/pseudorandom
    # que usam quadrante de verdade na escolha -- serve de referência
    # espacial em qualquer caso, pra comparar visualmente o quão distribuída
    # (ou concentrada) cada disposição ficou em relação a essa grade padrão.
    quadrant_raiz = int(round(cs_amount ** 0.5))
    for i in range(1, quadrant_raiz):
        x = x_min + i * (x_max - x_min) / quadrant_raiz
        ax.axvline(x, color="gray", linewidth=0.6, linestyle="--", zorder=2)
        y = y_min + i * (y_max - y_min) / quadrant_raiz
        ax.axhline(y, color="gray", linewidth=0.6, linestyle="--", zorder=2)

    # estações -- por cima de tudo
    ax.scatter(xs, ys, c="red", s=40, zorder=3)

    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    ax.set_title(f"{approach} -- {cs_amount} estações -- repetition {repetition}")
    ax.set_xlabel("x (net.xml)")
    ax.set_ylabel("y (net.xml)")
    ax.set_aspect("equal")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{approach}_{cs_amount}cs_rep{repetition}.png"
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    if sem_coordenada:
        print(f"  aviso: {sem_coordenada} lane(s) sem coordenada encontrada "
              f"em {approach}/{cs_amount}cs/rep{repetition} -- omitidas do PNG")


def main() -> None:
    report_lines = ["Validação de disposição de estações (mesma repetition, "
                     "minutes/percentage diferentes)", "=" * 70, ""]
    to_visualize: list[tuple[str, int, int, set[str]]] = []

    for approach in config.APPROACHES:
        report_lines.append(f"=== {approach} ===")
        for cs_amount in config.STATIONS_AMOUNTS:
            algo_gerado, passou, problemas = validate_disposition(approach, cs_amount)

            if not algo_gerado:
                report_lines.append(f"  {cs_amount}cs: sem dado gerado ainda (pulado)")
                continue

            resultado = "sim" if passou else "nao"
            report_lines.append(f"  {cs_amount}cs: {resultado}")
            for p in problemas:
                report_lines.append(f"      -> {p}")

            if passou:
                for repetition in config.REPETITIONS:
                    sets_by_combo = find_station_sets(approach, cs_amount, repetition)
                    if not sets_by_combo:
                        continue
                    # já validado que todas as combinações são iguais -- pega qualquer uma
                    lanes = next(iter(sets_by_combo.values()))
                    to_visualize.append((approach, cs_amount, repetition, lanes))

        report_lines.append("")

    report_path = TCC_ROOT / "disposition" / "disposition_validation_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print("\n".join(report_lines))
    print(f"[relatório salvo em: {report_path}]")

    if not to_visualize:
        print("\nNenhuma disposição com dado gerado passou na validação -- "
              "nenhuma imagem gerada.")
        return

    print(f"\nGerando {len(to_visualize)} imagem(ns)...")
    lanes_and_coords = _lanes_and_coordinates()
    # segmentos de todas as ruas do mapa, calculados uma vez só e
    # reaproveitados nas 125 imagens (recalcular isso a cada imagem seria
    # desperdício -- o mapa não muda entre disposições)
    road_segments = [points for points in lanes_and_coords.values() if len(points) >= 2]
    conv_boundary = _conv_boundary()

    out_dir = TCC_ROOT / "disposition" / "images"
    for approach, cs_amount, repetition, lanes in to_visualize:
        plot_disposition(approach, cs_amount, repetition, lanes,
                          lanes_and_coords, road_segments, conv_boundary, out_dir)

    print(f"[{len(to_visualize)} imagem(ns) salva(s) em: {out_dir}]")


if __name__ == "__main__":
    main()
