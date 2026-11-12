"""Compara uma tarefa de calibração com o resultado original.
USO (em validating_genetic/):
    python comparar_tarefa.py 9339 213094634 1314.105008
(id da calibração, fitness original, tempo original em segundos)"""
import json, sys
if len(sys.argv) != 4:
    sys.exit(__doc__)
i, f0, t0 = int(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
try:
    r = json.load(open(f"resultados/tarefa_{i}.json"))
except FileNotFoundError:
    sys.exit(f"resultados/tarefa_{i}.json ainda não existe.")
if r.get("status") != "concluida":
    sys.exit(f"status = {r.get('status')}: {r.get('resultado')}")
fit, t = r["resultado"]["fitness"], r["tempo_real_segundos"]
print(f"fitness novo: {fit:.0f} | original: {f0:.0f} | {'IGUAL' if round(fit)==round(f0) else 'DIFERENTE'}")
print(f"tempo   novo: {t:.1f} s | original: {t0:.1f} s | razão = {t/t0:.3f} ({(t/t0-1)*100:+.1f}%)")
