[CmdletBinding()]
param(
    [switch]$Full,
    [ValidateSet("", "PrivateBeta", "Public")]
    [string]$BuildProfile = ""
)

$ErrorActionPreference = "Stop"
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
    Invoke-Checked "Ruff format" { & $python -m ruff format --check . }
    Invoke-Checked "Ruff lint" { & $python -m ruff check . }
    Invoke-Checked "Python compile" { & $python -m compileall -q watched_kettle scripts tests }
    Invoke-Checked "Project structure" { & $python -m scripts.validate_project }
    $oldEdition = $env:WATCHED_KETTLE_EDITION
    Invoke-Checked "Settings appearance policies" { & node.exe --test settings-ui/scripts/appearance.test.cjs }
    try {
        foreach ($settingsEdition in @("pet-only", "pet-assistant")) {
            $env:WATCHED_KETTLE_EDITION = $settingsEdition
            Invoke-Checked "Settings UI $settingsEdition" { & pnpm.cmd --dir settings-ui run build }
        }
    } finally { $env:WATCHED_KETTLE_EDITION = $oldEdition }
    Invoke-Checked "Usage and storage boundary types" {
        & $python -m mypy watched_kettle/storage watched_kettle/usage `
            watched_kettle/integrations/codex_log_worker.py watched_kettle/process_metrics.py `
            watched_kettle/preferences watched_kettle/features/pet/contracts.py --follow-imports=silent
    }
    Invoke-Checked "Tray and runtime supervisor boundary types" {
        & $python -m mypy watched_kettle/ui/assistant_tray.py scripts/runtime_check.py --follow-imports=silent
    }
    Invoke-Checked "Task review and execution boundary types" {
        & $python -m mypy watched_kettle/features/tasks watched_kettle/integrations/codex_task_client.py --follow-imports=silent
    }
    Invoke-Checked "Regression tests" {
        & $python -m unittest discover -s tests -t . -v
    }

    Invoke-Checked "Project activity and notification boundary types" {
        & $python -m mypy watched_kettle/features/project_activity `
            watched_kettle/features/notifications watched_kettle/bubble_timing.py --follow-imports=silent
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
