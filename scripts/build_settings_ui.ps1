[CmdletBinding()]
param(
    [ValidateSet("pet-only", "pet-assistant")][string]$Edition = "pet-assistant",
    [Parameter(Mandatory)][string]$Destination
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$uiRoot = Join-Path $projectRoot "settings-ui"
$target = [IO.Path]::GetFullPath($Destination)
$pnpm = (Get-Command pnpm.cmd -ErrorAction Stop).Source
$node = (Get-Command node.exe -ErrorAction Stop).Source
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$previousEdition = $env:WATCHED_KETTLE_EDITION
Push-Location $uiRoot
try {
    & $pnpm install --frozen-lockfile --ignore-scripts
    if ($LASTEXITCODE -ne 0) { throw "Settings UI dependency installation failed." }
    & $node "node_modules/electron/install.js"
    if ($LASTEXITCODE -ne 0) { throw "Pinned Electron runtime installation failed." }
    if (Test-Path -LiteralPath $target) { throw "Settings UI destination must be new to prevent leftover edition files: $target" }
    New-Item -ItemType Directory -Path $target -Force | Out-Null
    Get-ChildItem -LiteralPath "node_modules/electron/dist" | Copy-Item -Destination $target -Recurse -Force
    Rename-Item -LiteralPath (Join-Path $target "electron.exe") -NewName "WatchedKettleSettings.exe"
    # Renaming keeps Electron's embedded icon, which the taskbar and window show.
    & $python (Join-Path $PSScriptRoot "set_exe_icon.py") (Join-Path $target "WatchedKettleSettings.exe") (Join-Path $projectRoot "assets\app_icon.ico")
    if ($LASTEXITCODE -ne 0) { throw "Settings executable icon replacement failed." }
    # The UI is Korean-only; Chromium falls back to en-US for other system
    # languages. The other 53 packs added ~48 MiB (stage 12 size target).
    $keptLocales = @("ko.pak", "en-US.pak")
    $localeRoot = Join-Path $target "locales"
    Get-ChildItem -LiteralPath $localeRoot -Filter "*.pak" |
        Where-Object { $keptLocales -notcontains $_.Name } |
        Remove-Item -Force
    foreach ($locale in $keptLocales) {
        if (-not (Test-Path -LiteralPath (Join-Path $localeRoot $locale))) {
            throw "Electron locale is missing: $locale"
        }
    }
    $appRoot = Join-Path $target "resources/app"
    New-Item -ItemType Directory -Path $appRoot -Force | Out-Null
    # Build straight into the bundle so settings-ui/dist keeps serving source runs.
    $rendererRoot = Join-Path $appRoot "dist"
    $env:WATCHED_KETTLE_EDITION = $Edition
    & $pnpm exec tsc --noEmit
    if ($LASTEXITCODE -ne 0) { throw "Settings UI type check failed." }
    & $pnpm exec vite build --outDir $rendererRoot --emptyOutDir
    if ($LASTEXITCODE -ne 0) { throw "Settings UI build failed." }
    $js = (Get-ChildItem -LiteralPath (Join-Path $rendererRoot "assets") -Filter "*.js" | Get-Content -Raw) -join ""
    if ($Edition -eq "pet-only" -and ($js.Contains('usage.snapshot') -or $js.Contains('integration.preview'))) {
        throw "Assistant renderer code leaked into the pet-only bundle."
    }
    Copy-Item -LiteralPath "electron" -Destination $appRoot -Recurse
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText((Join-Path $appRoot "package.json"), '{"name":"watched-kettle-settings","version":"1.0.0","main":"electron/main.cjs"}', $utf8)
    [IO.File]::WriteAllText((Join-Path $appRoot "edition.json"), (@{edition=$Edition} | ConvertTo-Json -Compress), $utf8)
    $licenses = Join-Path $target "licenses"
    New-Item -ItemType Directory -Path $licenses -Force | Out-Null
    foreach ($package in @("react", "react-dom", "lucide-react")) {
        $license = Join-Path "node_modules/$package" "LICENSE"
        Copy-Item -LiteralPath $license -Destination (Join-Path $licenses "$package-LICENSE.txt")
    }
    Copy-Item -LiteralPath "pnpm-lock.yaml" -Destination (Join-Path $licenses "build-lock.yaml")
    Write-Host "Settings UI packaged ($Edition): $target"
} finally {
    $env:WATCHED_KETTLE_EDITION = $previousEdition
    Pop-Location
}
