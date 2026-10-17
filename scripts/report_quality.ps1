[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
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
if ($LASTEXITCODE -ne 0) { throw "Select the supported Python environment before reporting quality." }
$qualityRoot = Join-Path $projectRoot "build\quality"
$coverageFile = Join-Path $qualityRoot ".coverage"
$coverageXml = Join-Path $qualityRoot "coverage.xml"
$auditCache = Join-Path $qualityRoot "pip-audit-cache"
New-Item -ItemType Directory -Force -Path $qualityRoot | Out-Null
New-Item -ItemType Directory -Force -Path $auditCache | Out-Null
$previousCoverageFile = $env:COVERAGE_FILE

function Invoke-QualityCheck {
    param([scriptblock]$Command)
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Quality gate failed (exit $LASTEXITCODE)." }
}

Push-Location $projectRoot
try {
    $env:COVERAGE_FILE = $coverageFile
    # Existing full-project typing debt remains an explicitly advisory artifact.
    & $python -m mypy *> (Join-Path $qualityRoot "mypy-advisory.txt")
    $typeExit = $LASTEXITCODE
    "mypy_advisory_exit=$typeExit" | Set-Content (Join-Path $qualityRoot "mypy-advisory-status.txt")
    Write-Host "Full-project mypy advisory exit: $typeExit"
    Invoke-QualityCheck { & $python -m coverage erase }
    Invoke-QualityCheck { & $python -m coverage run -m unittest discover -s tests -t . -v }
    Invoke-QualityCheck { & $python -m coverage report }
    Invoke-QualityCheck { & $python -m coverage xml -o $coverageXml }
    $coverageJson = Join-Path $qualityRoot "coverage.json"
    Invoke-QualityCheck { & $python -m coverage json -o $coverageJson }
    Invoke-QualityCheck { & $python -m scripts.coverage_gate $coverageJson }
    # Resolve transitive dependencies too; no --no-deps bypass.
    Invoke-QualityCheck { & $python -m pip_audit --cache-dir $auditCache -r requirements.txt }
} finally {
    $env:COVERAGE_FILE = $previousCoverageFile
    Pop-Location
}
