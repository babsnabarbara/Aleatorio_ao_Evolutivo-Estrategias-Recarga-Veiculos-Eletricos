"""
6_apagar_servidor0.py

Percorre os arquivos tarefa_*.json de uma pasta e apaga os que foram executados
no servidor 0 (campo "servidor_atribuido" == 0, o Xeon). Ao final, imprime a lista
de tudo que foi apagado e grava um JSON (apagados_servidor0.json) com o nome e os
hiperparâmetros de cada tarefa apagada.

Por segurança, antes de apagar ele:
  1) mostra o que vai ser apagado e pede confirmação (use --yes para pular);
  2) copia os arquivos para uma pasta de backup (use --sem-backup para não copiar).

USO:
    python 6_apagar_servidor0.py resultados --dry-run     # só lista, não apaga
    python 6_apagar_servidor0.py resultados               # lista, pede confirmação, apaga
    python 6_apagar_servidor0.py resultados --yes         # apaga sem perguntar
"""

import argparse
import glob
import json
import os
import shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta", nargs="?", default="resultados",
                    help="Pasta com os tarefa_*.json (padrão: resultados)")
    ap.add_argument("--servidor", type=int, default=0,
                    help="Índice do servidor cujos arquivos serão apagados (padrão: 0)")
    ap.add_argument("--dry-run", action="store_true", help="Só lista, não apaga nada")
    ap.add_argument("--yes", action="store_true", help="Não pede confirmação")
    ap.add_argument("--sem-backup", action="store_true", help="Não copia os arquivos antes de apagar")
    ap.add_argument("--saida", default="apagados_servidor0.txt",
                    help="Arquivo de texto com os nomes dos apagados")
    ap.add_argument("--saida-json", default="apagados_servidor0.json",
                    help="JSON com nome, hiperparâmetros (e fitness/tempo originais) de cada apagado")
    args = ap.parse_args()

    arquivos = sorted(glob.glob(os.path.join(args.pasta, "tarefa_*.json")),
                      key=lambda p: int(os.path.basename(p)[7:-5]) if os.path.basename(p)[7:-5].isdigit() else -1)
    if not arquivos:
        print(f"Nenhum tarefa_*.json encontrado em '{args.pasta}'.")
        return

    alvo, erros = [], []
    for caminho in arquivos:
        try:
            with open(caminho, encoding="utf-8") as f:
                t = json.load(f)
        except Exception as e:
            erros.append((caminho, str(e)))
            continue
        if t.get("servidor_atribuido") == args.servidor:
            alvo.append((caminho, t))

    print(f"{len(arquivos)} arquivos lidos | {len(alvo)} do servidor {args.servidor} | {len(erros)} com erro de leitura")
    for caminho, e in erros:
        print(f"  [erro] {os.path.basename(caminho)}: {e}")
    if not alvo:
        print("Nada para apagar.")
        return

    print(f"\nArquivos do servidor {args.servidor}:")
    print(f"{'arquivo':<18}{'id':>5}{'k':>4}{'tempo_real(s)':>15}{'fitness':>14}")
    for caminho, t in alvo:
        res = t.get("resultado") or {}
        print(f"{os.path.basename(caminho):<18}{t.get('id', '?'):>5}{t.get('k', '?'):>4}"
              f"{t.get('tempo_real_segundos', 0):>15.1f}{res.get('fitness', '-'):>14}")

    if args.dry_run:
        print(f"\n[dry-run] {len(alvo)} arquivos seriam apagados. Nada foi alterado.")
        return

    if not args.yes:
        resp = input(f"\nApagar {len(alvo)} arquivos? Digite SIM para confirmar: ")
        if resp.strip() != "SIM":
            print("Cancelado. Nada foi apagado.")
            return

    # JSON com o nome e os hiperparâmetros de cada tarefa (gravado ANTES de apagar)
    registro = []
    for caminho, t in alvo:
        res = t.get("resultado") or {}
        registro.append({
            "arquivo": os.path.basename(caminho),
            "id": t.get("id"),
            "k": t.get("k"),
            "seed": t.get("seed"),
            "servidor_atribuido": t.get("servidor_atribuido"),
            "params": t.get("params"),
            "fitness_original": res.get("fitness"),
            "tempo_real_segundos_original": t.get("tempo_real_segundos"),
        })
    with open(args.saida_json, "w", encoding="utf-8") as f:
        json.dump(registro, f, indent=2, ensure_ascii=False)
    print(f"\nJSON com os hiperparâmetros salvo em: {args.saida_json}")

    if not args.sem_backup:
        backup = os.path.join(args.pasta + "_backup_servidor" + str(args.servidor))
        os.makedirs(backup, exist_ok=True)
        for caminho, _ in alvo:
            shutil.copy2(caminho, backup)
        print(f"\nBackup copiado para: {backup}/")

    apagados = []
    for caminho, t in alvo:
        os.remove(caminho)
        apagados.append(os.path.basename(caminho))

    with open(args.saida, "w", encoding="utf-8") as f:
        f.write("\n".join(apagados) + "\n")

    print(f"\n=== {len(apagados)} arquivos APAGADOS ===")
    print(", ".join(apagados))
    print(f"\nLista salva em: {args.saida}")
    print(f"Hiperparâmetros salvos em: {args.saida_json}")


if __name__ == "__main__":
    main()
