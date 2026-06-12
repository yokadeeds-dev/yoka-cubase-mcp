<#
.SYNOPSIS
    Universeller Bootstrap-Installer fuer yoka-cubase-mcp (Windows).

.DESCRIPTION
    Tarifunabhaengig — braucht KEIN Claude-Abo. Macht deterministisch, was sonst
    der agentische Claude-Code-Weg taete:
      1. Umgebung pruefen (Python >= 3.11, git)
      2. Repo holen (falls noch nicht drin)
      3. venv + pip install -r requirements.txt  (mit rtmidi-Build-Hinweis)
      4. Diagnose (runtime.setup.doctor)
      5. Offline-Selftest (tests.selftests.listener_selftest)
      6. Claude-Config-Block mit absoluten Pfaden erzeugen
         (optional automatisch in Claude Desktop / Claude Code eintragen)
      7. Restliche GUI-Schritte (loopMIDI, Cubase) ausgeben

    Stoppt bei jedem echten Fehler, statt drueberzugehen.

.PARAMETER RepoUrl
    Git-URL, falls geklont werden muss. Default: offizielles Repo.

.PARAMETER Daw
    Wert fuer MACKIE_DAW_DEFAULT. Default: cubase.

.PARAMETER RegisterDesktop
    Traegt den Server automatisch (mit Backup) in claude_desktop_config.json ein.
    Ohne diesen Schalter wird der Block nur angezeigt + als Snippet-Datei abgelegt.

.PARAMETER RegisterClaudeCode
    Registriert den Server zusaetzlich via 'claude mcp add-json' (User-Scope),
    falls die Claude-Code-CLI vorhanden ist (Pro/Max/API).

.PARAMETER InstallSkill
    Verlinkt die Nicker-Skill nach ~/.claude/skills/ (Junction), damit Claude Code
    die volle Persona-/Workflow-Erfahrung laedt. Das Repo bleibt Source-of-Truth.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -RegisterDesktop
    .\install.ps1 -RegisterDesktop -RegisterClaudeCode -InstallSkill
#>
[CmdletBinding()]
param(
    [string]$RepoUrl = "https://github.com/yokadeeds-dev/yoka-cubase-mcp.git",
    [string]$Daw     = "cubase",
    [switch]$RegisterDesktop,
    [switch]$RegisterClaudeCode,
    [switch]$InstallSkill
)

$ErrorActionPreference = "Stop"

function Write-Step($n, $msg) { Write-Host "`n=== Schritt $n - $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)       { Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn2($msg)    { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Fail($msg) {
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    Write-Host "Abbruch. Behebe das oben Genannte und starte install.ps1 erneut." -ForegroundColor Red
    exit 1
}

Write-Host "yoka-cubase-mcp - Bootstrap-Installer (Windows)" -ForegroundColor Magenta
Write-Host "================================================"

# -------------------------------------------------------------------------
# Schritt 1: Umgebung pruefen
# -------------------------------------------------------------------------
Write-Step 1 "Umgebung pruefen"

# Python >= 3.11 finden. Bevorzugt der py-Launcher (-3.11), sonst python auf PATH.
$PyCmd = $null
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    & py -3.11 --version *> $null
    if ($LASTEXITCODE -eq 0) { $PyCmd = @("py", "-3.11") }
}
if (-not $PyCmd) {
    $pythonExe = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonExe) {
        $ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$ver -ge [version]"3.11") {
            $PyCmd = @("python")
        }
    }
}
if (-not $PyCmd) {
    Fail @"
Python >= 3.11 nicht gefunden.
Installiere es z. B. so:
  winget install --id Python.Python.3.11 -e
  (oder von https://www.python.org/downloads/ )
Danach neue PowerShell oeffnen und install.ps1 erneut starten.
"@
}
$PyVer = & $PyCmd[0] @($PyCmd[1..($PyCmd.Count-1)]) --version
Write-Ok "Python gefunden: $PyVer  (Befehl: $($PyCmd -join ' '))"

# git
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if (-not $gitCmd) {
    Fail @"
git nicht gefunden.
Installiere es so:
  winget install --id Git.Git -e
Danach neue PowerShell oeffnen und install.ps1 erneut starten.
"@
}
Write-Ok "git gefunden: $(git --version)"

# -------------------------------------------------------------------------
# Schritt 2: Repo holen / Repo-Root bestimmen
# -------------------------------------------------------------------------
Write-Step 2 "Repo holen"

function Test-RepoRoot($path) {
    return (Test-Path (Join-Path $path "requirements.txt")) -and `
           (Test-Path (Join-Path $path "runtime\mcp\server.py"))
}

$RepoRoot = $null
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
if (Test-RepoRoot (Get-Location).Path) {
    $RepoRoot = (Get-Location).Path
    Write-Ok "Bereits im Repo: $RepoRoot"
} elseif (Test-RepoRoot $scriptDir) {
    $RepoRoot = $scriptDir
    Write-Ok "Repo am Skript-Ort: $RepoRoot"
} else {
    $target = Join-Path (Get-Location).Path "yoka-cubase-mcp"
    if (Test-RepoRoot $target) {
        $RepoRoot = $target
        Write-Ok "Repo bereits geklont: $RepoRoot"
    } else {
        Write-Host "Klone $RepoUrl ..."
        git clone $RepoUrl $target
        if ($LASTEXITCODE -ne 0 -or -not (Test-RepoRoot $target)) { Fail "git clone fehlgeschlagen." }
        $RepoRoot = $target
        Write-Ok "Geklont nach: $RepoRoot"
    }
}

Push-Location $RepoRoot
try {
    # ---------------------------------------------------------------------
    # Schritt 3: venv + Abhaengigkeiten
    # ---------------------------------------------------------------------
    Write-Step 3 "venv + Abhaengigkeiten"

    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Host "Erstelle venv (.venv) ..."
        & $PyCmd[0] @($PyCmd[1..($PyCmd.Count-1)]) -m venv .venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPy)) { Fail "venv-Erstellung fehlgeschlagen." }
        Write-Ok "venv erstellt."
    } else {
        Write-Ok "venv existiert bereits - wird wiederverwendet."
    }

    & $venvPy -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) { Fail "pip-Upgrade fehlgeschlagen." }

    Write-Host "Installiere requirements.txt (kann 1-3 Min dauern: numpy/scipy/rtmidi) ..."
    & $venvPy -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 @"
pip install ist fehlgeschlagen. Haeufigste Ursache: python-rtmidi muss kompiliert
werden und es fehlen die C++-Build-Tools. Installiere sie und starte erneut:
  winget install --id Microsoft.VisualStudio.2022.BuildTools -e `
    --override "--quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
"@
        Fail "Abhaengigkeiten nicht vollstaendig installiert."
    }
    # rtmidi-Importtest (der eigentliche Build-Stolperstein)
    & $venvPy -c "import rtmidi" 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "python-rtmidi liess sich nicht importieren (Build-Tools fehlen?)." }
    Write-Ok "Alle Abhaengigkeiten installiert (inkl. python-rtmidi)."

    # ---------------------------------------------------------------------
    # Schritt 4: Diagnose (doctor)
    # ---------------------------------------------------------------------
    Write-Step 4 "Diagnose (runtime.setup.doctor)"
    & $venvPy -m runtime.setup.doctor
    if ($LASTEXITCODE -ne 0) { Fail "doctor meldet einen harten Fehler (Python/Deps/Server-Import)." }
    Write-Ok "Diagnose ohne harte Fehler. WARN zu MIDI-Ports/Cubase/Plugins/YMP ist NORMAL bis loopMIDI+Cubase eingerichtet sind."

    # ---------------------------------------------------------------------
    # Schritt 5: Offline-Selftest
    # ---------------------------------------------------------------------
    Write-Step 5 "Offline-Selftest"
    & $venvPy -m tests.selftests.listener_selftest
    if ($LASTEXITCODE -ne 0) { Fail "Selftest fehlgeschlagen." }
    Write-Ok "Selftests bestanden."

    # ---------------------------------------------------------------------
    # Schritt 6: Claude-Config erzeugen
    # ---------------------------------------------------------------------
    Write-Step 6 "Claude-Config erzeugen"

    # Forward-Slashes: vermeiden JSON-Escaping und werden von Python/Windows akzeptiert.
    $venvPyFwd = $venvPy -replace '\\', '/'
    $repoFwd   = $RepoRoot -replace '\\', '/'

    $server = [pscustomobject]@{
        command = $venvPyFwd
        args    = @("-m", "runtime.mcp.server")
        cwd     = $repoFwd
        env     = [pscustomobject]@{ MACKIE_DAW_DEFAULT = $Daw }
    }
    $snippet = [pscustomobject]@{ mcpServers = [pscustomobject]@{ "yoka-cubase-mcp" = $server } }
    $snippetJson = $snippet | ConvertTo-Json -Depth 10

    $snippetPath = Join-Path $RepoRoot "claude_desktop_config.snippet.json"
    $snippetJson | Set-Content -Path $snippetPath -Encoding UTF8
    Write-Ok "Config-Block geschrieben: $snippetPath"
    Write-Host "`n--- Block fuer claude_desktop_config.json ---" -ForegroundColor DarkGray
    Write-Host $snippetJson
    Write-Host "---------------------------------------------`n" -ForegroundColor DarkGray

    # 6a) optional: in Claude Desktop config einmergen
    if ($RegisterDesktop) {
        $cfgPath = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
        $cfgDir  = Split-Path -Parent $cfgPath
        if (-not (Test-Path $cfgDir)) { New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null }

        if (Test-Path $cfgPath) {
            $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
            Copy-Item $cfgPath "$cfgPath.bak-$stamp"
            Write-Ok "Backup: $cfgPath.bak-$stamp"
            $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
        } else {
            $cfg = [pscustomobject]@{}
        }
        if (-not $cfg.PSObject.Properties['mcpServers']) {
            $cfg | Add-Member -NotePropertyName mcpServers -NotePropertyValue ([pscustomobject]@{})
        }
        if ($cfg.mcpServers.PSObject.Properties['yoka-cubase-mcp']) {
            $cfg.mcpServers.'yoka-cubase-mcp' = $server
        } else {
            $cfg.mcpServers | Add-Member -NotePropertyName 'yoka-cubase-mcp' -NotePropertyValue $server
        }
        $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $cfgPath -Encoding UTF8
        Write-Ok "In Claude Desktop eingetragen: $cfgPath  (Desktop neu starten)"
    } else {
        Write-Host "Tipp: Mit -RegisterDesktop traegt das Skript den Block automatisch (mit Backup) in claude_desktop_config.json ein." -ForegroundColor DarkGray
    }

    # 6b) optional: Claude Code (CLI), falls vorhanden
    if ($RegisterClaudeCode) {
        $claudeCli = Get-Command claude -ErrorAction SilentlyContinue
        if ($claudeCli) {
            $serverJson = $server | ConvertTo-Json -Depth 10 -Compress
            claude mcp remove yoka-cubase-mcp --scope user *> $null
            claude mcp add-json yoka-cubase-mcp $serverJson --scope user
            if ($LASTEXITCODE -eq 0) { Write-Ok "In Claude Code (User-Scope) registriert." }
            else { Write-Warn2 "claude mcp add-json fehlgeschlagen - bitte Config manuell pruefen." }
        } else {
            Write-Warn2 "Claude-Code-CLI ('claude') nicht gefunden - uebersprungen."
        }
    }

    # 6c) optional: Nicker-Skill nach ~/.claude/skills/ verlinken (volle Claude-Code-Erfahrung)
    if ($InstallSkill) {
        $skillSrc  = Join-Path $RepoRoot "skills\ki-studio-nicker"
        $skillsDir = Join-Path $env:USERPROFILE ".claude\skills"
        $skillDest = Join-Path $skillsDir "ki-studio-nicker"
        if (-not (Test-Path $skillSrc)) {
            Write-Warn2 "Skill-Quelle nicht gefunden ($skillSrc) - uebersprungen."
        } else {
            if (-not (Test-Path $skillsDir)) { New-Item -ItemType Directory -Path $skillsDir -Force | Out-Null }
            if (Test-Path $skillDest) {
                # Bestehendes Ziel sicher entfernen: Junction/Symlink nur als LINK loeschen,
                # niemals -Recurse (das wuerde sonst die verlinkten Repo-Dateien mitnehmen).
                $existing = Get-Item $skillDest -Force
                if ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                    Write-Warn2 "Vorhandener Link wird ersetzt: $skillDest"
                    $existing.Delete()
                } else {
                    Write-Warn2 "Vorhandener Ordner wird ersetzt: $skillDest"
                    Remove-Item $skillDest -Recurse -Force
                }
            }
            New-Item -ItemType Junction -Path $skillDest -Target $skillSrc | Out-Null
            Write-Ok "Nicker-Skill verlinkt: $skillDest -> $skillSrc  (Claude Code neu starten)"
        }
    }
}
finally {
    Pop-Location
}

# -------------------------------------------------------------------------
# Schritt 7: Restliche GUI-Schritte (nicht automatisierbar)
# -------------------------------------------------------------------------
Write-Step 7 "DAW-Setup (manuell - fuer JEDEN Nutzer gleich)"
Write-Host @"
Diese beiden Schritte kann kein Skript automatisieren:

  1) loopMIDI installieren (Windows):  winget install --id TobiasErichsen.loopMIDI -e
     Starten und DREI virtuelle Ports anlegen (Namen exakt):
       - MACKIE_FROM_CUBASE
       - MACKIE_TO_CUBASE
       - AI_INPUT

  2) In Cubase: Studio -> Studio-Konfiguration -> '+' -> Mackie Control
       - MIDI-Eingang:  MACKIE_TO_CUBASE
       - MIDI-Ausgang:  MACKIE_FROM_CUBASE
     Anleitung: docs/01_setup_cubase_mcu.md

Danach erneut pruefen:
  $venvPy -m runtime.setup.doctor
"@ -ForegroundColor Gray

Write-Host "`nFertig. Headless-Setup steht; nur loopMIDI + Cubase fehlen noch (Schritt 7)." -ForegroundColor Green
