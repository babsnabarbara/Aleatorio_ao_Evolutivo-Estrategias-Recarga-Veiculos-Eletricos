"""Compara a tarefa de calibração (id 9012 = cópia da tarefa 12 do grid original)
com o resultado original. Rode em validating_genetic/ depois que o worker terminar."""
import json, sys
ORIG_FITNESS = 211894324
ORIG_TEMPO = 969.375692   # LCAD1 (servidor 3), ambiente antigo
try:
    r = json.load(open("resultados/tarefa_9012.json"))
except FileNotFoundError:
    sys.exit("resultados/tarefa_9012.json ainda não existe (o worker não terminou).")
if r.get("status") != "concluida":
    sys.exit(f"status = {r.get('status')}: {r.get('resultado')}")
fit = r["resultado"]["fitness"]; t = r["tempo_real_segundos"]
print(f"fitness  novo: {fit:.0f} | original: {ORIG_FITNESS} | {'IGUAL' if round(fit)==ORIG_FITNESS else 'DIFERENTE'}")
print(f"tempo    novo: {t:.1f} s | original: {ORIG_TEMPO:.1f} s | razão novo/original = {t/ORIG_TEMPO:.3f} ({(t/ORIG_TEMPO-1)*100:+.1f}%)")
