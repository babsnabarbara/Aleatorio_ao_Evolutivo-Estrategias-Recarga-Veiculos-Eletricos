"""
4_combinar_resultados.py

Depois que os 4 servidores terminarem (ou mesmo no meio da execução, pra
acompanhar o progresso), rode isso numa máquina que tenha uma cópia da
pasta resultados/ de TODOS os servidores (junte via scp/rsync antes) para
gerar um único CSV com tudo, pronto pra análise (ex. pandas, Excel).

USO:
    # depois de copiar resultados/ de cada servidor para uma pasta local,
    # ex.: resultados_servidor_0/, resultados_servidor_1/, etc.
    python 4_combinar_resultados.py resultados_servidor_0 resultados_servidor_1 \
        resultados_servidor_2 resultados_servidor_3
"""

import argparse
import csv
import glob
import json
import os


def carregar_pasta(pasta):
    tarefas = []
    for caminho in glob.glob(os.path.join(pasta, "tarefa_*.json")):
        with open(caminho) as f:
            tarefas.append(json.load(f))
    return tarefas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pastas", nargs="+",
                     help="Pastas resultados/ copiadas de cada servidor")
    ap.add_argument("--saida", default="grid_search_resultados.csv")
    args = ap.parse_args()

    todas = []
    for pasta in args.pastas:
        todas.extend(carregar_pasta(pasta))

    print(f"{len(todas)} resultados carregados de {len(args.pastas)} pastas.")

    concluidas = [t for t in todas if t["status"] == "concluida"]
    falharam = [t for t in todas if t["status"] == "falhou"]
    print(f"  concluídas: {len(concluidas)}  |  falharam: {len(falharam)}")

    if falharam:
        print("\nTarefas que falharam (ids):",
              [t["id"] for t in falharam])

    if not concluidas:
        print("Nenhum resultado concluído para exportar.")
        return

    # Monta CSV: id, k, hiperparâmetros, tempo real, e o conteúdo de
    # 'resultado' (achatado, assumindo que tem pelo menos 'fitness')
    campos_params = list(concluidas[0]["params"].keys())
    campos_resultado = sorted({
        k for t in concluidas for k in (t["resultado"] or {}).keys()
    })

    with open(args.saida, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["id", "k", "servidor", "tempo_real_segundos"]
            + campos_params + campos_resultado
        )
        for t in sorted(concluidas, key=lambda x: x["id"]):
            linha = [
                t["id"], t["k"], t["servidor_atribuido"],
                t["tempo_real_segundos"],
            ]
            linha += [t["params"][c] for c in campos_params]
            linha += [(t["resultado"] or {}).get(c, "") for c in campos_resultado]
            writer.writerow(linha)

    print(f"\nArquivo salvo: {args.saida}")

    # Melhor resultado por k, se 'fitness' existir
    if "fitness" in campos_resultado:
        print("\nMelhor fitness encontrado por k:")
        melhores = {}
        for t in concluidas:
            k = t["k"]
            fit = (t["resultado"] or {}).get("fitness")
            if fit is None:
                continue
            if k not in melhores or fit < melhores[k]["resultado"]["fitness"]:
                melhores[k] = t
        for k in sorted(melhores):
            t = melhores[k]
            print(f"  k={k}: fitness={t['resultado']['fitness']:.0f} "
                  f"(tarefa {t['id']}, params={t['params']})")


if __name__ == "__main__":
    main()
