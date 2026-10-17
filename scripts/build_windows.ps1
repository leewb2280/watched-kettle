[CmdletBinding()]
param(
    [ValidateSet("PrivateBeta", "Public")]
    [string]$Profile = "PrivateBeta",
    [ValidateSet("PetOnly", "PetAssistant")]
    [string]$Edition = "PetAssistant",
    [string]$OutputRoot = "",
    # Points the update check at scripts/serve_update_test.py on 127.0.0.1
    # instead of the official Releases. Never publish such a bundle.
    [ValidateRange(1024, 65535)]
    [int]$UpdateTestPort = 0,
    # With -UpdateTestPort: the test server PC's private network IPv4 address,
    # so other PCs on the same network can try updates (serve_update_test --host).
    [string]$UpdateTestHost = "127.0.0.1",
    [switch]$SkipTests,
    [switch]$SkipPackageSmoke
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$spec = Join-Path $projectRoot "packaging\WatchedKettle.spec"
$buildProfile = if ($Profile -eq "Public") { "public" } else { "private-beta" }
$buildEdition = if ($Edition -eq "PetOnly") { "pet-only" } else { "pet-assistant" }
$distRoot = if ($OutputRoot) {
    [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputRoot))
} else {
    Join-Path $projectRoot "dist"
}
$profileDistRoot = Join-Path $distRoot "$buildProfile\$buildEdition"
$workRoot = Join-Path $projectRoot "build\pyinstaller\$buildProfile\$buildEdition"
$versionInfo = Join-Path $workRoot "windows_version_info.txt"
$bundle = Join-Path $profileDistRoot "WatchedKettle"
$executable = Join-Path $bundle "WatchedKettle.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project virtual-environment Python was not found: $python"
}

& $python (Join-Path $PSScriptRoot "python_version.py")
if ($LASTEXITCODE -ne 0) { throw "Select the supported Python environment before building." }

$applicationVersion = (
    & $python -c (
        "from watched_kettle.branding import APPLICATION_VERSION; " +
        "print(APPLICATION_VERSION)"
    )
).Trim()
if (-not $applicationVersion) {
    throw "The application version could not be read."
}
$updateApiUrl = ""
$updatePageUrl = ""
$updateNotesUrl = ""
if ($UpdateTestPort) {
    & $python -c (
        "import sys; from watched_kettle.application.update_check import local_test_host; " +
        "sys.exit(0 if local_test_host(sys.argv[1]) else 1)"
    ) $UpdateTestHost
    if ($LASTEXITCODE -ne 0) {
        throw "-UpdateTestHost must be 127.0.0.1 or a private network IPv4 address: $UpdateTestHost"
    }
    $updateChannel = "local-test"
    $updateApiUrl = "http://${UpdateTestHost}:$UpdateTestPort/api/releases/latest"
    $updatePageUrl = "http://${UpdateTestHost}:$UpdateTestPort/releases"
} elseif ($buildProfile -eq "public") {
    $updateChannel = "official"
    # Update files and the installer people download live in two repositories (ADR 0008).
    $repositories = @(
        & $python -c "from watched_kettle.branding import UPDATE_REPOSITORY as u, RELEASE_REPOSITORY as r; print(u); print(r)"
    )
    $updateRepository = "$($repositories[0])".Trim()
    $releaseRepository = "$($repositories[1])".Trim()
    foreach ($repository in @($updateRepository, $releaseRepository)) {
        if ($repository -notmatch '^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$') {
            throw "The update repositories could not be read."
        }
    }
    $updateApiUrl = "https://api.github.com/repos/$updateRepository/releases/latest"
    $updatePageUrl = "https://github.com/$updateRepository/releases"
    $updateNotesUrl = "https://github.com/$releaseRepository/releases"
} else {
    $updateChannel = "none"
}
& $python -m scripts.generate_windows_version_info $versionInfo
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $versionInfo)) {
    throw "The Windows version metadata could not be generated."
}
$artifactBaseName = "WatchedKettle-$applicationVersion-$buildProfile-$buildEdition"
$archive = Join-Path $profileDistRoot "$artifactBaseName.zip"
$checksum = "$archive.sha256"

if (-not $SkipTests) {
    & $python -m unittest discover -s (Join-Path $projectRoot "tests") -t $projectRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Regression tests failed; packaging was stopped."
    }
}

& $python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is missing. Install requirements-build.txt first."
}

$env:WATCHED_KETTLE_BUILD_PROFILE = $buildProfile
$env:WATCHED_KETTLE_EDITION = $buildEdition
$env:WATCHED_KETTLE_VERSION_FILE = $versionInfo
& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $profileDistRoot `
    --workpath $workRoot `
    $spec
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $executable)) {
    throw "The Windows executable build failed."
}
& $python -m scripts.check_edition_modules `
    (Join-Path $workRoot "WatchedKettle\PYZ-00.toc") --edition $buildEdition `
    --bundle (Join-Path $bundle "_internal")
if ($LASTEXITCODE -ne 0) { throw "The edition module boundary failed." }
if ($buildEdition -eq "pet-assistant") {
    & $python -m scripts.check_edition_modules `
        (Join-Path $workRoot "WatchedKettle\PYZ-01.toc") --edition hook-bridge
    if ($LASTEXITCODE -ne 0) { throw "The hook bridge module boundary failed." }
}

& (Join-Path $PSScriptRoot "build_settings_ui.ps1") -Edition $buildEdition -Destination (Join-Path $bundle "settings-ui")
if ($LASTEXITCODE -ne 0) { throw "The settings UI package failed." }

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
# Partial updates are made only between bundles of one installer revision.
$installerRevision = [int](Get-Content -Raw -LiteralPath (Join-Path $projectRoot "packaging\installer-revision.json") | ConvertFrom-Json).revision
if ($installerRevision -lt 1) { throw "packaging/installer-revision.json has no valid revision." }
[IO.File]::WriteAllLines(
    (Join-Path $bundle "BUILD_PROFILE.txt"),
    [string[]]@(
        "version=$applicationVersion"
        "profile=$buildProfile"
        "edition=$buildEdition"
        "update_channel=$updateChannel"
        "installer_revision=$installerRevision"
    ),
    $utf8NoBom
)
Copy-Item `
    -LiteralPath (Join-Path $projectRoot "THIRD_PARTY_NOTICES.md") `
    -Destination (Join-Path $bundle "THIRD_PARTY_NOTICES.md") `
    -Force
Copy-Item `
    -LiteralPath (Join-Path $projectRoot "assets\fonts\Pretendard\OFL.txt") `
    -Destination (Join-Path $bundle "PRETENDARD_OFL.txt") `
    -Force
if ($updateApiUrl) {
    # Read by watched_kettle/application/update_check.py, which applies the
    # same official / 127.0.0.1 address rules.
    $updateSource = [ordered]@{ api_url = $updateApiUrl; release_url = $updatePageUrl }
    if ($updateNotesUrl) { $updateSource.notes_url = $updateNotesUrl }
    $updateSource = $updateSource | ConvertTo-Json -Compress
    [IO.File]::WriteAllText((Join-Path $bundle "UPDATE_SOURCE.json"), $updateSource, $utf8NoBom)
}
if ($buildProfile -eq "private-beta") {
    $quickStartFileName = (-join @(
        [char]0xC0AC,
        [char]0xC6A9,
        [char]0xBC29,
        [char]0xBC95
    )) + ".txt"
    Copy-Item `
        -LiteralPath (Join-Path $projectRoot "packaging\private-beta\NOTICE.txt") `
        -Destination (Join-Path $bundle "PRIVATE_BETA_NOTICE.txt") `
        -Force
    Copy-Item `
        -LiteralPath (Join-Path $projectRoot "packaging\private-beta\QUICKSTART.txt") `
        -Destination (Join-Path $bundle $quickStartFileName) `
        -Force
}

if (-not $SkipPackageSmoke) {
    $settingsReport = Join-Path $workRoot "settings-ui-smoke.json"
    $settingsSmoke = Start-Process -FilePath $executable -ArgumentList "--settings-ui-smoke-test --report `"$settingsReport`"" -PassThru -WindowStyle Hidden
    if (-not $settingsSmoke.WaitForExit(45000)) { $settingsSmoke.Kill(); throw "Electron lifecycle smoke timed out." }
    if ($settingsSmoke.ExitCode -ne 0) { throw "Electron lifecycle smoke failed: $settingsReport" }
    if ($buildEdition -eq "pet-assistant") {
        # The Qt-free bridge must queue one hook event while no pet is listening.
        $bridgeRoot = Join-Path $workRoot "hook-bridge-smoke"
        Remove-Item -LiteralPath $bridgeRoot -Recurse -Force -ErrorAction SilentlyContinue
        $env:WATCHED_KETTLE_SERVER_NAME = "watched-kettle-build-smoke-" + [guid]::NewGuid().ToString("N")
        $env:WATCHED_KETTLE_SPOOL_DIRECTORY = Join-Path $bridgeRoot "spool"
        $env:WATCHED_KETTLE_HOOK_HEALTH_PATH = Join-Path $bridgeRoot "health.json"
        try {
            '{"hook_event_name":"PreToolUse","session_id":"build-smoke"}' |
                & (Join-Path $bundle "WatchedKettleHookBridge.exe") | Out-Null
            $bridgeExit = $LASTEXITCODE
        } finally {
            Remove-Item Env:WATCHED_KETTLE_SERVER_NAME, Env:WATCHED_KETTLE_SPOOL_DIRECTORY, Env:WATCHED_KETTLE_HOOK_HEALTH_PATH -ErrorAction SilentlyContinue
        }
        $bridgeHealth = Join-Path $bridgeRoot "health.json"
        if ($bridgeExit -ne 0 -or -not (Test-Path -LiteralPath $bridgeHealth) -or
            (Get-Content -LiteralPath $bridgeHealth -Raw | ConvertFrom-Json).outcome -ne "queued") {
            throw "Hook bridge smoke failed."
        }
    }
    $smokeProcess = Start-Process `
        -FilePath $executable `
        -ArgumentList "--package-smoke-test" `
        -PassThru `
        -WindowStyle Hidden
    if (-not $smokeProcess.WaitForExit(30000)) {
        $smokeProcess.Kill()
        throw "The packaged smoke test did not exit within 30 seconds."
    }
    if ($smokeProcess.ExitCode -ne 0) {
        throw "The packaged Qt, Pillow, and pet-resource smoke test failed."
    }
    $runtimeReport = Join-Path $workRoot "runtime-smoke-$applicationVersion-$(Get-Date -Format yyyyMMddHHmmss).json"
    if ($buildEdition -eq "pet-only") {
        $petSmoke = Start-Process -FilePath $executable `
            -ArgumentList "--runtime-smoke-test --report `"$runtimeReport`"" `
            -PassThru -WindowStyle Hidden
        if (-not $petSmoke.WaitForExit(30000)) {
            $petSmoke.Kill()
            throw "The pet-only runtime smoke did not exit."
        }
        if ($petSmoke.ExitCode -ne 0) { throw "The pet-only runtime smoke failed." }
    } else {
        & $python -m scripts.runtime_check --executable $executable --report $runtimeReport
        if ($LASTEXITCODE -ne 0) {
            throw "The externally supervised runtime smoke failed."
        }
        $settingsReport = Join-Path $workRoot "settings-exit-$applicationVersion-$(Get-Date -Format yyyyMMddHHmmss).json"
        $settingsSmoke = Start-Process -FilePath $executable `
            -ArgumentList "--runtime-smoke-test --require-tray --exit-via-settings --duration-seconds 3 --report `"$settingsReport`"" `
            -PassThru -WindowStyle Hidden
        if (-not $settingsSmoke.WaitForExit(30000)) {
            $settingsSmoke.Kill()
            throw "The settings quit did not exit the packaged process."
        }
        if ($settingsSmoke.ExitCode -ne 0) { throw "The packaged settings quit smoke failed." }
        $settingsResult = Get-Content -LiteralPath $settingsReport -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($settingsResult.status -ne 'observation_complete' -or
            -not $settingsResult.settings_quit_accepted -or
            -not $settingsResult.settings_hide_preserved_runtime -or
            -not $settingsResult.pet_visible_at_quit -or
            -not $settingsResult.tray_visible_at_quit -or
            -not $settingsResult.runtime_closed_on_exit -or
            -not $settingsResult.settings_closed_on_exit -or
            -not $settingsResult.tray_closed_on_exit) {
            throw "The packaged settings quit cleanup was not observed."
        }
        Write-Host "Settings quit verdict: $settingsReport"
    }
    Write-Host "Runtime verdict: $runtimeReport"

}

$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $executable
& $python -m scripts.collect_runtime_licenses (Join-Path $bundle "licenses")
if ($LASTEXITCODE -ne 0) { throw "Runtime license collection failed." }
if ($buildProfile -eq "public") {
    Copy-Item -LiteralPath (Join-Path $projectRoot "LICENSE") -Destination (Join-Path $bundle "LICENSE.txt")
}
& $python -m scripts.release_artifacts manifest $bundle
if ($LASTEXITCODE -ne 0) {
    throw "The package file inventory could not be generated."
}
# Settings, records, logs and build-machine paths belong to the user, not the bundle.
& $python -m scripts.release_artifacts inspect $bundle
if ($LASTEXITCODE -ne 0) {
    throw "The bundle contains per-user state or build machine paths."
}
Compress-Archive `
    -LiteralPath $bundle `
    -DestinationPath $archive `
    -CompressionLevel Optimal `
    -Force
& $python -m scripts.release_artifacts verify $archive
if ($LASTEXITCODE -ne 0) {
    throw "The release ZIP integrity or file inventory check failed."
}
$archiveHash = Get-FileHash -Algorithm SHA256 -LiteralPath $archive
Set-Content `
    -LiteralPath $checksum `
    -Value "$($archiveHash.Hash)  $([IO.Path]::GetFileName($archive))" `
    -Encoding ascii
Write-Host "Build complete: $bundle"
Write-Host "Build profile: $buildProfile"
Write-Host "Edition: $buildEdition"
Write-Host "Executable SHA256: $($hash.Hash)"
Write-Host "Handoff archive: $archive"
Write-Host "Archive SHA256: $($archiveHash.Hash)"
Write-Host "Checksum file: $checksum"
