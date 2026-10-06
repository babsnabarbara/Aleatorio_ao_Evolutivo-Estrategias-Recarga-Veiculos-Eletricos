#!/usr/bin/env bash
# backup_environment.sh
#
# Roda UMA VEZ, num servidor que já está funcionando (ex: LCAD1), antes da
# formatação. Empacota tudo que é preciso pra recriar o ambiente depois:
#
#   - sumo.tar.gz              -> o SUMO inteiro (binário + tools, inclui
#                                  traci/sumolib já na versão certa -- não
#                                  precisa (e não deve) reinstalar via pip)
#   - requirements_project.txt -> só as bibliotecas Python que o PROJETO
#                                  de verdade importa (via pipreqs, lendo
#                                  os .py de ~/TCC), com traci/sumolib
#                                  removidos de propósito
#   - VERSIONS.txt             -> manifesto legível (versão do Python, do
#                                  SUMO, do SO) pra conferência manual
#
# Uso:
#   bash backup_environment.sh
#
# Depois, baixa a pasta gerada (env_backup_<host>_<data>/) pro seu
# computador ou outro storage, fora do servidor que vai ser formatado.

set -euo pipefail

OUT_DIR=~/env_backup_$(hostname)_$(date +%Y%m%d)
mkdir -p "$OUT_DIR"

echo "== 1/3: empacotando SUMO (\$SUMO_HOME=$SUMO_HOME) =="
if [ -z "${SUMO_HOME:-}" ] || [ ! -d "$SUMO_HOME" ]; then
    echo "ERRO: \$SUMO_HOME não está definido ou a pasta não existe. Aborting."
    exit 1
fi
tar czf "$OUT_DIR/sumo.tar.gz" -C "$(dirname "$SUMO_HOME")" "$(basename "$SUMO_HOME")"
echo "   -> $OUT_DIR/sumo.tar.gz ($(du -h "$OUT_DIR/sumo.tar.gz" | cut -f1))"

echo
echo "== 1b/3: dependências de SISTEMA do binário SUMO (apt, não pip/venv) =="
# O binário sumo é compilado e linkado contra libs do SO (libproj, libgdal,
# libxerces-c, libfox pro GUI, etc). Isso NAO vem no sumo.tar.gz nem no
# requirements.txt -- se faltar no servidor novo, o binário restaurado
# simplesmente não roda (erro de .so não encontrada), mesmo com o tar.gz
# certo. Aqui a gente descobre quais pacotes apt fornecem essas libs, pra
# você conseguir reinstalar ANTES de extrair o sumo.tar.gz no servidor novo.
LDD_OUT="$OUT_DIR/sumo_ldd.txt"
ldd "$SUMO_HOME/bin/sumo" > "$LDD_OUT" 2>&1 || true
echo "   -> $LDD_OUT (saída crua do ldd, pra conferência manual)"

APT_DEPS_OUT="$OUT_DIR/sumo_apt_packages.txt"
{
    awk '{print $3}' "$LDD_OUT" | grep '^/' | sort -u | while read -r lib; do
        dpkg -S "$lib" 2>/dev/null | cut -d: -f1
    done | sort -u
} > "$APT_DEPS_OUT" || true
N_PKGS=$(wc -l < "$APT_DEPS_OUT" 2>/dev/null || echo 0)
echo "   -> $APT_DEPS_OUT ($N_PKGS pacote(s) apt que o SUMO precisa pra rodar)"

echo
echo "== 2/3: gerando requirements do projeto (via pipreqs) =="
PROJECT_DIR=~/TCC
if [ ! -d "$PROJECT_DIR" ]; then
    echo "AVISO: $PROJECT_DIR não existe -- ajuste PROJECT_DIR no script e rode de novo."
else
    pip install --user --quiet pipreqs 2>/dev/null || pip3 install --user --quiet pipreqs
    "$HOME/.local/bin/pipreqs" "$PROJECT_DIR" --savepath "$OUT_DIR/requirements_project.txt" --force \
        || python3 -m pipreqs.pipreqs "$PROJECT_DIR" --savepath "$OUT_DIR/requirements_project.txt" --force

    # traci/sumolib NUNCA devem vir de pip -- vêm de dentro do sumo.tar.gz
    # (ver nota no topo). Remove se o pipreqs tiver detectado o import.
    grep -viE '^(traci|sumolib)==' "$OUT_DIR/requirements_project.txt" > "$OUT_DIR/requirements_project.tmp" \
        && mv "$OUT_DIR/requirements_project.tmp" "$OUT_DIR/requirements_project.txt"
    echo "   -> $OUT_DIR/requirements_project.txt"
fi

echo
echo "== 3/3: manifesto de versões (sumo, traci, sumolib, libsumo) =="
{
    echo "host: $(hostname)"
    echo "gerado em: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "python: $(python3 --version 2>&1)"
    echo "SUMO_HOME original neste servidor: $SUMO_HOME"
    echo "SO: $(lsb_release -ds 2>/dev/null || uname -a)"
    echo
    echo "--- sumo (binário) ---"
    "$SUMO_HOME/bin/sumo" --version 2>/dev/null | head -1
    echo
    python3 - <<'PYEOF'
import sys
print("--- traci (Python) ---")
try:
    import traci
    print("arquivo:", traci.__file__)
    print("traci.__version__:", getattr(traci, "__version__", "n/a -- essa versão não expõe isso"))
    try:
        import traci.constants as tc
        print("traci API version (TRACI_VERSION):", getattr(tc, "TRACI_VERSION", "n/a"))
    except Exception as e:
        print("traci.constants: erro ->", e)
except Exception as e:
    print("traci: NAO DISPONIVEL ->", e)

print()
print("--- sumolib (Python) ---")
try:
    import sumolib
    print("arquivo:", sumolib.__file__)
    print("sumolib.__version__:", getattr(sumolib, "__version__", "n/a -- essa versão não expõe isso"))
except Exception as e:
    print("sumolib: NAO DISPONIVEL ->", e)

print()
print("--- libsumo (Python, bindings compilados -- opcional) ---")
try:
    import libsumo
    print("arquivo:", libsumo.__file__)
    try:
        print("libsumo.getVersion():", libsumo.getVersion())
    except Exception as e:
        print("libsumo.getVersion(): erro ->", e)
except Exception as e:
    print("libsumo: NAO DISPONIVEL/NAO COMPILADO nesse build ->", type(e).__name__, str(e))
PYEOF
} > "$OUT_DIR/VERSIONS.txt"
cat "$OUT_DIR/VERSIONS.txt"

echo
echo "Pronto -- tudo em: $OUT_DIR"
ls -la "$OUT_DIR"
echo
echo "Baixa essa pasta inteira pro seu computador (ou outro storage) antes"
echo "de formatar. Pra recriar o ambiente depois, usa setup_env.sh com essa"
echo "mesma pasta como argumento -- ele já instala sumo_apt_packages.txt"
echo "ANTES de extrair o SUMO."
echo
echo "IMPORTANTE -- o que esse script NÃO cobre (fora do escopo de 'ambiente'):"
echo "  - o código do projeto (~/TCC) -- esse já está no git/main, recupera com"
echo "    'git clone' no servidor novo, não precisa de backup separado aqui."
echo "  - input/ e output/ -- dados e resultados, não fazem parte do 'ambiente'"
echo "    de execução; se forem grandes, cuide do backup deles à parte."
