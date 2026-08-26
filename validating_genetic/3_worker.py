"""
3_worker.py

Roda em CADA servidor (--servidor 0, 1, 2 ou 3, conforme o arquivo
tarefas_servidor_N.json que ele recebeu).

Diferente da versão anterior (placeholder), agora chama de verdade o AG
de genetic_algorithm.py. O grafo da rede viária e o ProcessPoolExecutor
são montados UMA VEZ no início — não a cada tarefa, já que não mudam
entre combinações de hiperparâmetros nem entre valores de k.

Cada tarefa concluída salva seu resultado individualmente em
resultados/tarefa_<id>.json (se o processo cair no meio, nada se perde) e
o worker retoma de onde parou se rodar de novo.

USO:
    python 3_worker.py --servidor 0
    python 3_worker.py --servidor 0 --netfile /caminho/para/cologne.net.xml
    (rodar em background, ex.: nohup python 3_worker.py --servidor 0 &)
"""

import argparse
import json
import os
import time
import traceback
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor

from genetic_algorithm import (
    montar_grafo_base,
    rodar_combinacao,
    _init_worker,
)

os.makedirs("resultados", exist_ok=True)

# Seed usada em todas as tarefas do grid de hiperparâmetros: mantê-la fixa
# isola o efeito dos hiperparâmetros (mesma condição inicial pra todo mundo).
# Se depois você quiser rodar as combinações vencedoras com múltiplas seeds
# pra checar robustez, isso é uma etapa separada, sobre um conjunto bem
# menor de combinações (as finalistas), não o grid inteiro.
SEED_PADRAO = 42


def carregar_bloco(servidor):
    caminho = f"tarefas_servidor_{servidor}.json"
    with open(caminho) as f:
        return caminho, json.load(f)


def ja_tem_resultado(tarefa_id):
    return os.path.exists(f"resultados/tarefa_{tarefa_id}.json")


def salvar_resultado(tarefa, resultado, tempo_real):
    tarefa["status"] = "concluida"
    tarefa["tempo_real_segundos"] = tempo_real
    tarefa["resultado"] = resultado
    with open(f"resultados/tarefa_{tarefa['id']}.json", "w") as f:
        json.dump(tarefa, f, indent=2)


def salvar_falha(tarefa, erro):
    tarefa["status"] = "falhou"
    tarefa["resultado"] = {"erro": str(erro)}
    with open(f"resultados/tarefa_{tarefa['id']}.json", "w") as f:
        json.dump(tarefa, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--servidor", type=int, required=True,
                     help="Índice do servidor (0, 1, 2 ou 3)")
    ap.add_argument("--netfile", default="input/cologne.net.xml",
                     help="Caminho do arquivo .net.xml da rede viária")
    ap.add_argument("--local-search", action="store_true",
                     help="Se passado, roda o refinamento exaustivo após "
                          "o AG em cada tarefa (desligado por padrão no "
                          "grid search de hiperparâmetros)")
    args = ap.parse_args()

    caminho, bloco = carregar_bloco(args.servidor)

    pendentes = [t for t in bloco if not ja_tem_resultado(t["id"])]
    ja_feitas = len(bloco) - len(pendentes)
    print(f"[servidor {args.servidor}] {len(bloco)} tarefas no total, "
          f"{ja_feitas} já concluídas anteriormente, "
          f"{len(pendentes)} pendentes.\n")

    if not pendentes:
        print(f"[servidor {args.servidor}] Nada pendente. Encerrando.")
        return

    print(f"[servidor {args.servidor}] Montando grafo a partir de "
          f"{args.netfile} ...")
    reversed_graph, candidate_nodes, total_nodes = montar_grafo_base(args.netfile)
    print(f"[servidor {args.servidor}] Grafo pronto: {total_nodes} nós "
          f"candidatos.\n")

    num_workers = os.cpu_count()
    inicio_execucao = time.time()

    with ProcessPoolExecutor(
        max_workers=num_workers,
        initializer=_init_worker,
        initargs=(reversed_graph, total_nodes),
    ) as executor:

        for i, tarefa in enumerate(pendentes):
            run_tag = f"servidor{args.servidor}_tarefa{tarefa['id']}"
            print(f"[servidor {args.servidor}] Tarefa {tarefa['id']} "
                  f"({i + 1}/{len(pendentes)}) — k={tarefa['k']} "
                  f"params={tarefa['params']}")

            t0 = time.time()
            try:
                resultado = rodar_combinacao(
                    executor, candidate_nodes, tarefa["k"], tarefa["params"],
                    seed=tarefa.get("seed", SEED_PADRAO), run_tag=run_tag,
                    usar_local_search=args.local_search,
                )
                tempo_real = time.time() - t0
                salvar_resultado(tarefa, resultado, tempo_real)
                print(f"    -> concluída em {tempo_real:.0f}s "
                      f"(estimado: {tarefa['tempo_estimado_segundos']}s) "
                      f"| fitness: {resultado['fitness']:.0f}")
            except Exception as e:
                print(f"    -> FALHOU: {e}")
                traceback.print_exc()
                salvar_falha(tarefa, e)

            decorrido = time.time() - inicio_execucao
            feito_estimado = sum(
                t["tempo_estimado_segundos"] for t in pendentes[:i + 1]
            )
            if feito_estimado > 0:
                fator = decorrido / feito_estimado
                restante_estimado = sum(
                    t["tempo_estimado_segundos"] for t in pendentes[i + 1:]
                ) * fator
                eta = datetime.now() + timedelta(seconds=restante_estimado)
                print(f"    ETA para terminar este servidor: "
                      f"{eta.strftime('%d/%m %H:%M')}\n")

    print(f"[servidor {args.servidor}] Bloco concluído.")


if __name__ == "__main__":
    main()
