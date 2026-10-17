[CmdletBinding()]
param(
    [switch]$Full,
    [switch]$DocsOnly,
    [switch]$Quality,
    [ValidateSet("", "PrivateBeta", "Public")]
    [string]$BuildProfile = ""
)

$ErrorActionPreference = "Stop"
if ($DocsOnly -and ($Full -or $Quality)) { throw "-DocsOnly cannot be combined with -Full or -Quality." }
$projectRoot = Split-Path -Parent $PSScriptRoot
# The public snapshot has no private pets, so it builds the Public profile by default.
if (-not $BuildProfile) {
    $BuildProfile = if (Test-Path -LiteralPath (Join-Path $projectRoot "private-pets")) { "PrivateBeta" } else { "Public" }
}
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $venvPython
} else {
    "python"
}

$env:PYTHONUTF8 = "1"
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONUNBUFFERED = "1"

& $python (Join-Path $PSScriptRoot "python_version.py")
if ($LASTEXITCODE -ne 0) { throw "Select the supported Python environment before checking." }

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

Push-Location $projectRoot
try {
    if ($DocsOnly) {
        Invoke-Checked "Project structure and documentation" { & $python -m scripts.validate_project }
        Invoke-Checked "Static architecture boundaries" { & $python -m unittest tests.test_bubble_architecture -v }
        Write-Host "Documentation and structure checks passed."
        return
    }
    Invoke-Checked "Ruff format" { & $python -m ruff format --check . }
    Invoke-Checked "Ruff lint" { & $python -m ruff check . }
    Invoke-Checked "Python compile" { & $python -m compileall -q watched_kettle scripts tests }
    Invoke-Checked "Project structure" { & $python -m scripts.validate_project }
    Invoke-Checked "Settings appearance and protocol policies" {
        & node.exe --test settings-ui/scripts/appearance.test.cjs settings-ui/scripts/protocol.test.cjs
    }
    Invoke-Checked "Settings UI TypeScript" { & pnpm.cmd --dir settings-ui run check }
    $oldEdition = $env:WATCHED_KETTLE_EDITION
    try {
        foreach ($settingsEdition in @("pet-only", "pet-assistant")) {
            $env:WATCHED_KETTLE_EDITION = $settingsEdition
            Invoke-Checked "Settings UI $settingsEdition" { & pnpm.cmd --dir settings-ui exec vite build }
        }
    } finally { $env:WATCHED_KETTLE_EDITION = $oldEdition }
    $boundaryTargets = @(
        "watched_kettle/storage", "watched_kettle/usage",
        "watched_kettle/integrations/codex_log_worker.py", "watched_kettle/process_metrics.py",
        "watched_kettle/preferences", "watched_kettle/features/pet/contracts.py",
        "watched_kettle/ui/assistant_tray.py", "scripts/runtime_check.py",
        "watched_kettle/features/tasks", "watched_kettle/integrations/codex_task_client.py",
        "watched_kettle/features/project_activity", "watched_kettle/features/notifications",
        "watched_kettle/bubble_timing.py",
        "watched_kettle/settings_protocol.py", "scripts/generate_settings_protocol.py",
        "watched_kettle/application/settings_ui"
    )
    Invoke-Checked "Required boundary types" {
        & $python -m mypy @boundaryTargets --follow-imports=silent
    }
    if ($Quality) {
        Invoke-Checked "Regression tests, coverage gates and dependency audit" {
            & (Join-Path $PSScriptRoot "report_quality.ps1")
        }
    } else {
        Invoke-Checked "Regression tests" {
            & $python -m unittest discover -s tests -t . -v
        }
    }
    if ($Full) {
        Invoke-Checked "Windows $BuildProfile package" {
            & (Join-Path $PSScriptRoot "build_windows.ps1") `
                -Profile $BuildProfile `
                -SkipTests
        }
    }
} finally {
    Pop-Location
}

Write-Host "All required checks passed."
