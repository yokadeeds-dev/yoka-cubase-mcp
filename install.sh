#!/usr/bin/env bash
#
# Universeller Bootstrap-Installer fuer yoka-cubase-mcp (macOS/Linux).
# Analog zu install.ps1 (Windows). Tarifunabhaengig — braucht KEIN Claude-Abo.
# Macht deterministisch, was sonst der agentische Claude-Code-Weg taete:
#   1. Umgebung pruefen (Python >= 3.11, git)
#   2. Repo holen (falls noch nicht drin)
#   3. venv + pip install -r requirements.txt  (mit rtmidi-Build-Hinweis)
#   4. Diagnose (runtime.setup.doctor)
#   5. Offline-Selftest (tests.selftests.listener_selftest)
#   6. Claude-Config-Block mit absoluten Pfaden erzeugen
#      (optional automatisch in Claude Desktop / Claude Code eintragen)
#   7. Restliche Setup-Schritte (IAC-Ports, DAW) ausgeben
# Stoppt bei jedem echten Fehler, statt drueberzugehen.
#
# Aufruf:
#   ./install.sh
#   ./install.sh --register-desktop
#   ./install.sh --register-desktop --register-claude-code --install-skill
#   Optionen: --daw <name> (Default cubase) · --repo-url <url>

set -euo pipefail

REPO_URL="https://github.com/yokadeeds-dev/yoka-cubase-mcp.git"
DAW="cubase"
REGISTER_DESKTOP=0
REGISTER_CLAUDE_CODE=0
INSTALL_SKILL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url)            REPO_URL="$2"; shift 2 ;;
    --daw)                 DAW="$2"; shift 2 ;;
    --register-desktop)    REGISTER_DESKTOP=1; shift ;;
    --register-claude-code) REGISTER_CLAUDE_CODE=1; shift ;;
    --install-skill)       INSTALL_SKILL=1; shift ;;
    -h|--help)
      echo "Usage: ./install.sh [--register-desktop] [--register-claude-code] [--install-skill] [--daw cubase] [--repo-url URL]"
      exit 0 ;;
    *) echo "Unbekannte Option: $1"; exit 1 ;;
  esac
done

if [[ -t 1 ]]; then C=$'\033[36m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; M=$'\033[35m'; N=$'\033[0m'
else C=""; G=""; Y=""; R=""; M=""; N=""; fi
step() { printf "\n%s=== Schritt %s - %s ===%s\n" "$C" "$1" "$2" "$N"; }
ok()   { printf "%s[OK]   %s%s\n" "$G" "$1" "$N"; }
warn() { printf "%s[WARN] %s%s\n" "$Y" "$1" "$N"; }
fail() { printf "%s[FAIL] %s%s\n" "$R" "$1" "$N"; printf "%sAbbruch. Behebe das oben Genannte und starte install.sh erneut.%s\n" "$R" "$N"; exit 1; }

OS="$(uname -s)"
printf "%syoka-cubase-mcp - Bootstrap-Installer (%s)%s\n" "$M" "$OS" "$N"
echo "===================================================="

# ---------------------------------------------------------------- Schritt 1
step 1 "Umgebung pruefen"
PY=""
if command -v python3.11 >/dev/null 2>&1; then
  PY="python3.11"
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,11) else 1)'; then
  PY="python3"
fi
if [[ -z "$PY" ]]; then
  fail "Python >= 3.11 nicht gefunden.
Installiere es:
  macOS:  brew install python@3.11
  Linux:  sudo apt install python3.11 python3.11-venv   (oder dnf/pacman)
Danach neue Shell oeffnen und install.sh erneut starten."
fi
ok "Python gefunden: $($PY --version 2>&1)  (Befehl: $PY)"

if ! command -v git >/dev/null 2>&1; then
  fail "git nicht gefunden.  macOS: xcode-select --install   Linux: sudo apt install git"
fi
ok "git gefunden: $(git --version)"

# ---------------------------------------------------------------- Schritt 2
step 2 "Repo holen"
is_repo() { [[ -f "$1/requirements.txt" && -f "$1/runtime/mcp/server.py" ]]; }
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT=""
if is_repo "$PWD"; then
  REPO_ROOT="$PWD"; ok "Bereits im Repo: $REPO_ROOT"
elif is_repo "$SCRIPT_DIR"; then
  REPO_ROOT="$SCRIPT_DIR"; ok "Repo am Skript-Ort: $REPO_ROOT"
elif is_repo "$PWD/yoka-cubase-mcp"; then
  REPO_ROOT="$PWD/yoka-cubase-mcp"; ok "Repo bereits geklont: $REPO_ROOT"
else
  echo "Klone $REPO_URL ..."
  git clone "$REPO_URL" "$PWD/yoka-cubase-mcp"
  REPO_ROOT="$PWD/yoka-cubase-mcp"
  is_repo "$REPO_ROOT" || fail "git clone fehlgeschlagen."
  ok "Geklont nach: $REPO_ROOT"
fi
cd "$REPO_ROOT"

# ---------------------------------------------------------------- Schritt 3
step 3 "venv + Abhaengigkeiten"
VENV_PY="$REPO_ROOT/.venv/bin/python"
if [[ ! -x "$VENV_PY" ]]; then
  echo "Erstelle venv (.venv) ..."
  "$PY" -m venv .venv
  [[ -x "$VENV_PY" ]] || fail "venv-Erstellung fehlgeschlagen."
  ok "venv erstellt."
else
  ok "venv existiert bereits - wird wiederverwendet."
fi

"$VENV_PY" -m pip install --upgrade pip --quiet || fail "pip-Upgrade fehlgeschlagen."
echo "Installiere requirements.txt (kann 1-3 Min dauern: numpy/scipy/rtmidi) ..."
if ! "$VENV_PY" -m pip install -r requirements.txt; then
  warn "pip install fehlgeschlagen. Haeufigste Ursache: python-rtmidi braucht Build-Tools.
  macOS:  xcode-select --install
  Linux:  sudo apt install build-essential libasound2-dev   (Debian/Ubuntu)
Dann erneut starten."
  fail "Abhaengigkeiten nicht vollstaendig installiert."
fi
"$VENV_PY" -c "import rtmidi" 2>/dev/null || fail "python-rtmidi liess sich nicht importieren (Build-Tools fehlen?)."
ok "Alle Abhaengigkeiten installiert (inkl. python-rtmidi)."

# ---------------------------------------------------------------- Schritt 4
step 4 "Diagnose (runtime.setup.doctor)"
"$VENV_PY" -m runtime.setup.doctor || fail "doctor meldet einen harten Fehler (Python/Deps/Server-Import)."
ok "Diagnose ohne harte Fehler. WARN zu MIDI-Ports/DAW/Plugins/YMP ist NORMAL bis IAC + DAW eingerichtet sind."

# ---------------------------------------------------------------- Schritt 5
step 5 "Offline-Selftest"
"$VENV_PY" -m tests.selftests.listener_selftest || fail "Selftest fehlgeschlagen."
ok "Selftests bestanden."

# ---------------------------------------------------------------- Schritt 6
step 6 "Claude-Config erzeugen"
SNIPPET_PATH="$REPO_ROOT/claude_desktop_config.snippet.json"
# JSON robust via Python erzeugen (auf Unix sind Pfade ohnehin Forward-Slash).
"$VENV_PY" - "$VENV_PY" "$REPO_ROOT" "$DAW" "$SNIPPET_PATH" <<'PYEOF'
import json, sys
venv_py, repo, daw, out = sys.argv[1:5]
block = {"mcpServers": {"yoka-cubase-mcp": {
    "command": venv_py,
    "args": ["-m", "runtime.mcp.server"],
    "cwd": repo,
    "env": {"MACKIE_DAW_DEFAULT": daw},
}}}
js = json.dumps(block, indent=2)
with open(out, "w") as f:
    f.write(js)
print(js)
PYEOF
ok "Config-Block geschrieben: $SNIPPET_PATH"

# 6a) optional: in Claude Desktop config einmergen (macOS; Claude Desktop gibt es nicht auf Linux)
if [[ "$REGISTER_DESKTOP" == "1" ]]; then
  if [[ "$OS" == "Darwin" ]]; then
    CFG_PATH="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
  else
    CFG_PATH=""
    warn "Claude Desktop gibt es nicht auf Linux — uebersprungen (nutze --register-claude-code)."
  fi
  if [[ -n "$CFG_PATH" ]]; then
    mkdir -p "$(dirname "$CFG_PATH")"
    "$VENV_PY" - "$CFG_PATH" "$VENV_PY" "$REPO_ROOT" "$DAW" <<'PYEOF'
import json, os, sys, shutil, time
cfg_path, venv_py, repo, daw = sys.argv[1:5]
server = {"command": venv_py, "args": ["-m", "runtime.mcp.server"], "cwd": repo, "env": {"MACKIE_DAW_DEFAULT": daw}}
cfg = {}
if os.path.exists(cfg_path):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    shutil.copy2(cfg_path, cfg_path + ".bak-" + stamp)
    print("[OK]   Backup: %s.bak-%s" % (cfg_path, stamp))
    try:
        with open(cfg_path) as f: cfg = json.load(f)
    except Exception: cfg = {}
cfg.setdefault("mcpServers", {})["yoka-cubase-mcp"] = server
with open(cfg_path, "w") as f: json.dump(cfg, f, indent=2)
print("[OK]   In Claude Desktop eingetragen: %s  (Desktop neu starten)" % cfg_path)
PYEOF
  fi
else
  printf "%sTipp: --register-desktop traegt den Block automatisch (mit Backup) in claude_desktop_config.json ein.%s\n" "$Y" "$N"
fi

# 6b) optional: Claude Code (CLI), falls vorhanden
if [[ "$REGISTER_CLAUDE_CODE" == "1" ]]; then
  if command -v claude >/dev/null 2>&1; then
    SERVER_JSON="$("$VENV_PY" -c "import json,sys; print(json.dumps({'command':sys.argv[1],'args':['-m','runtime.mcp.server'],'cwd':sys.argv[2],'env':{'MACKIE_DAW_DEFAULT':sys.argv[3]}}))" "$VENV_PY" "$REPO_ROOT" "$DAW")"
    claude mcp remove yoka-cubase-mcp --scope user >/dev/null 2>&1 || true
    if claude mcp add-json yoka-cubase-mcp "$SERVER_JSON" --scope user; then
      ok "In Claude Code (User-Scope) registriert."
    else
      warn "claude mcp add-json fehlgeschlagen - bitte Config manuell pruefen."
    fi
  else
    warn "Claude-Code-CLI ('claude') nicht gefunden - uebersprungen."
  fi
fi

# 6c) optional: Nicker-Skill nach ~/.claude/skills/ verlinken
if [[ "$INSTALL_SKILL" == "1" ]]; then
  SKILL_SRC="$REPO_ROOT/skills/ki-studio-nicker"
  SKILLS_DIR="$HOME/.claude/skills"
  SKILL_DEST="$SKILLS_DIR/ki-studio-nicker"
  if [[ ! -d "$SKILL_SRC" ]]; then
    warn "Skill-Quelle nicht gefunden ($SKILL_SRC) - uebersprungen."
  else
    mkdir -p "$SKILLS_DIR"
    # ln -sfn ersetzt einen vorhandenen Symlink sicher, ohne in ein verlinktes Verzeichnis zu schreiben.
    if [[ -e "$SKILL_DEST" && ! -L "$SKILL_DEST" ]]; then
      warn "Vorhandener echter Ordner wird ersetzt: $SKILL_DEST"
      rm -rf "$SKILL_DEST"
    fi
    ln -sfn "$SKILL_SRC" "$SKILL_DEST"
    ok "Nicker-Skill verlinkt: $SKILL_DEST -> $SKILL_SRC  (Claude Code neu starten)"
  fi
fi

# ---------------------------------------------------------------- Schritt 7
step 7 "DAW-Setup (manuell - kann kein Skript automatisieren)"
cat <<EOF
Diese Schritte bleiben manuell:

  1) Virtuelle MIDI-Ports:
     macOS:  IAC-Treiber aktivieren — Audio-MIDI-Setup.app -> Fenster -> MIDI-Studio
             -> IAC-Treiber -> "Gerat ist online". Helfer:
               $VENV_PY -m runtime.setup.add_iac_ports
     Linux:  z. B. ALSA/JACK virtuelle Ports.
     Drei Ports mit exakt diesen Namen:
       - MACKIE_FROM_CUBASE
       - MACKIE_TO_CUBASE
       - AI_INPUT

  2) In deiner DAW ein Mackie-Control-Device auf diese Ports:
       - Eingang:  MACKIE_TO_CUBASE
       - Ausgang:  MACKIE_FROM_CUBASE
     Cubase:  Studio -> Studio-Konfiguration -> '+' -> Mackie Control (docs/01_setup_cubase_mcu.md).
     Ableton (auf dem Mac oft naeher): Einstellungen -> Link/Tempo/MIDI ->
       Bedienoberflaeche "MackieControl", Ein-/Ausgang auf die IAC-Ports. Dann --daw ableton nutzen.

Danach erneut pruefen:
  $VENV_PY -m runtime.setup.doctor
EOF

printf "\n%sFertig. Headless-Setup steht; nur IAC-Ports + DAW fehlen noch (Schritt 7).%s\n" "$G" "$N"
