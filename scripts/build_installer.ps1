[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$PetOnlyBundleRoot,
    [Parameter(Mandatory)][string]$AssistantBundleRoot,
    [Parameter(Mandatory)][string]$Compiler,
    [string]$OutputRoot = "dist/installers",
    # Invitation installer: also installs the private-beta pets into the user's
    # pet folder. Never upload its output to public Releases.
    [switch]$WithPrivatePets,
    # Also build one update installer per edition, the in-app update's
    # fallback when no partial update applies (ADR 0007).
    [switch]$UpdateInstallers
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$petBundle = (Resolve-Path -LiteralPath $PetOnlyBundleRoot).Path
$assistantBundle = (Resolve-Path -LiteralPath $AssistantBundleRoot).Path
$compilerPath = (Resolve-Path -LiteralPath $Compiler).Path
$artifactDir = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputRoot))
if ($WithPrivatePets -and $UpdateInstallers) {
    throw "Update installers come from the public bundles only; build them without -WithPrivatePets."
}
$versions = @()
$channels = @()
$revisions = @()
foreach ($item in @(@{ Path = $petBundle; Edition = "pet-only" }, @{ Path = $assistantBundle; Edition = "pet-assistant" })) {
    $profile = Get-Content -LiteralPath (Join-Path $item.Path "BUILD_PROFILE.txt")
    if ($profile -notcontains "profile=public" -or $profile -notcontains "edition=$($item.Edition)") {
        throw "Expected a Public $($item.Edition) bundle: $($item.Path)"
    }
    $versionLine = @($profile | Where-Object { $_ -match '^version=\d+\.\d+\.\d+$' })
    if ($versionLine.Count -ne 1) { throw "Missing or invalid bundle version." }
    if (-not (Test-Path -LiteralPath (Join-Path $item.Path "WatchedKettle.exe"))) {
        throw "Missing executable: $($item.Path)"
    }
    $versions += $versionLine[0].Substring(8)
    # Written by build_windows.ps1; older bundles predate the line.
    $channelLine = @($profile | Where-Object { $_ -match '^update_channel=(official|local-test|none)$' })
    $channels += if ($channelLine.Count -eq 1) { $channelLine[0].Substring(15) } else { "none" }
    $revisionLine = @($profile | Where-Object { $_ -match '^installer_revision=\d+$' })
    $revisions += if ($revisionLine.Count -eq 1) { $revisionLine[0].Substring(19) } else { "" }
}
if ($versions[0] -ne $versions[1]) { throw "Bundle versions do not match." }
if ($channels[0] -ne $channels[1]) { throw "Bundle update channels do not match: $($channels -join ', ')." }
$version = $versions[0]
# Partial updates are made only between bundles of the same installer revision.
$expectedRevision = [string](Get-Content -Raw -LiteralPath (Join-Path $projectRoot "packaging\installer-revision.json") | ConvertFrom-Json).revision
foreach ($revision in $revisions) {
    if ($revision -ne $expectedRevision) {
        throw "Bundle installer revision '$revision' is not packaging/installer-revision.json's $expectedRevision; rebuild the bundles."
    }
}
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$stamp = Get-Date -Format "yyyyMMddHHmmss"
$installerStage = Join-Path $projectRoot "build\installer-stage-$stamp"

# Wizard images, one per DPI scale.
$imagesRoot = Join-Path $installerStage "images"
& $python (Join-Path $PSScriptRoot "render_installer_images.py") $imagesRoot
if ($LASTEXITCODE -ne 0) { throw "Installer image rendering failed." }

# Stable launcher for shortcuts and startup, built with the .NET Framework
# compiler that ships with Windows.
$csc = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path -LiteralPath $csc -PathType Leaf)) { throw "Missing .NET Framework compiler: $csc" }
$launcherRoot = Join-Path $installerStage "launcher"
New-Item -ItemType Directory -Path $launcherRoot | Out-Null
$assemblyInfo = Join-Path $launcherRoot "AssemblyInfo.cs"
Set-Content -LiteralPath $assemblyInfo -Encoding utf8 -Value @(
    "using System.Reflection;",
    "[assembly: AssemblyTitle(`"Watched Kettle`")]",
    "[assembly: AssemblyProduct(`"Watched Kettle`")]",
    "[assembly: AssemblyCompany(`"Watched Kettle contributors`")]",
    "[assembly: AssemblyVersion(`"$version.0`")]",
    "[assembly: AssemblyFileVersion(`"$version.0`")]",
    "[assembly: AssemblyInformationalVersion(`"$version`")]"
)
$launcher = Join-Path $launcherRoot "WatchedKettle.exe"
& $csc /nologo /target:winexe /platform:anycpu /optimize+ /codepage:65001 `
    "/win32icon:$(Join-Path $projectRoot 'assets\app_icon.ico')" "/out:$launcher" `
    (Join-Path $projectRoot "packaging\launcher\WatchedKettleLauncher.cs") $assemblyInfo
if ($LASTEXITCODE -ne 0) { throw "Launcher compilation failed." }

$runtimeBytes = ($petBundle, $assistantBundle | ForEach-Object {
    (Get-ChildItem -LiteralPath $_ -Recurse -File | Measure-Object -Property Length -Sum).Sum
} | Measure-Object -Maximum).Maximum

$compilerArguments = @("/DAppVersion=$version", "/DPetOnlyBundleRoot=$petBundle", "/DAssistantBundleRoot=$assistantBundle", "/DArtifactDir=$artifactDir", "/DLauncherExe=$launcher", "/DWizardImagesRoot=$imagesRoot", "/DRuntimeBytes=$([int64]$runtimeBytes)")
$installerKind = "public"
if ($channels[0] -eq "local-test") {
    # Its update check reads 127.0.0.1, so the name keeps it out of Releases.
    $compilerArguments += "/DUpdateTest"
    $installerKind = "public-update-test"
}
if ($WithPrivatePets) {
    $stage = Join-Path $projectRoot "build\private-pets-stage-$stamp"
    & $python (Join-Path $PSScriptRoot "stage_private_pets.py") $stage
    if ($LASTEXITCODE -ne 0) { throw "Private pet staging failed." }
    $compilerArguments += "/DPrivatePetsRoot=$stage"
    $installerKind = $installerKind -replace '^public', 'private-pets'
}
function Build-Installer([string[]]$Extra, [string]$Kind) {
    & $compilerPath @compilerArguments @Extra (Join-Path $projectRoot "packaging/windows-installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Installer compilation failed." }
    $installer = Join-Path $artifactDir "WatchedKettle-$version-$Kind-unsigned-setup.exe"
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'NotSigned') { throw "Expected an unsigned candidate; inspect signing state." }
    $hash = Get-FileHash -LiteralPath $installer -Algorithm SHA256
    Set-Content -LiteralPath "$installer.sha256" -Value "$($hash.Hash)  $([IO.Path]::GetFileName($installer))" -Encoding ascii
    Write-Host "Unsigned installer candidate: $installer"
}
Build-Installer @() $installerKind
if ($UpdateInstallers) {
    foreach ($edition in @("pet-only", "pet-assistant")) {
        Build-Installer @("/DUpdateEdition=$edition") "$installerKind-$edition-update"
    }
}
