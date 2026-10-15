[CmdletBinding()]
param(
    [ValidateSet('Capture', 'Install', 'Uninstall', 'BackupReset', 'Export', 'RepairManual')]
    [string]$Action = 'Capture',
    [ValidateSet('baseline', 'fresh-pet', 'assistant-disconnected', 'assistant-connected', 'pet-after-removal', 'assistant-readded', 'assistant-reinstalled', 'legacy-before', 'legacy-upgraded', 'uninstall-records', 'uninstall-all', 'uninstall-keep')]
    [string]$Phase = 'baseline',
    [ValidateSet('Running', 'Stopped')]
    [string]$When = 'Running',
    [string]$Installer = '',
    [switch]$SilentUninstall,
    [string]$ExpectedTestUser = '',
    [string]$OutputRoot = ''
)

$ErrorActionPreference = 'Stop'
$profileRoot = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
$localRoot = [IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\')
$appRoot = [IO.Path]::GetFullPath((Join-Path $localRoot 'Programs\CodexDesktopPets'))
$dataRoot = [IO.Path]::GetFullPath((Join-Path $localRoot 'CodexDesktopPets'))
$qaRoot = [IO.Path]::GetFullPath($(if ($OutputRoot) { $OutputRoot } else { Join-Path $profileRoot 'Documents\CodexDesktopPets-stage10-qa' }))
$comparison = [StringComparison]::OrdinalIgnoreCase

function Assert-WithinProfile([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($profileRoot + '\', $comparison)) {
        throw "Path is outside the current Windows profile: $resolved"
    }
}

foreach ($path in @($localRoot, $appRoot, $dataRoot, $qaRoot)) {
    Assert-WithinProfile $path
}

function File-Record([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try {
        $item = Get-Item -LiteralPath $Path
        $record = [ordered]@{ bytes = $item.Length }
        try { $record.sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash }
        catch { $record.hash_error = $_.Exception.GetType().Name }
        return $record
    } catch {
        return [ordered]@{ error = $_.Exception.GetType().Name }
    }
}

function Managed-Hook-Count {
    $codexRoot = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $profileRoot '.codex' }
    $hookPath = Join-Path $codexRoot 'hooks.json'
    if (-not (Test-Path -LiteralPath $hookPath -PathType Leaf)) { return 0 }
    $contents = Get-Content -LiteralPath $hookPath -Raw -Encoding UTF8
    return [regex]::Matches($contents, 'codex-desktop-pets-managed-v1').Count
}

function Add-Check([System.Collections.ArrayList]$Checks, [string]$Name, [bool]$Passed) {
    [void]$Checks.Add([ordered]@{ name = $Name; passed = $Passed })
}

New-Item -ItemType Directory -Path $qaRoot -Force | Out-Null

trap {
    $message = $_.Exception.Message
    try {
        $errorRoot = Join-Path $qaRoot 'command-errors'
        New-Item -ItemType Directory -Path $errorRoot -Force | Out-Null
        $errorPath = Join-Path $errorRoot ("$Action-$Phase-$(Get-Date -Format yyyyMMdd-HHmmss).json")
        [ordered]@{
            action = $Action
            phase = $Phase
            captured_at_utc = [DateTime]::UtcNow.ToString('o')
            windows_user = $env:USERNAME
            error = $message
        } | ConvertTo-Json | Set-Content -LiteralPath $errorPath -Encoding UTF8
        [Console]::Error.WriteLine("QA error report: $errorPath")
    } catch {
        [Console]::Error.WriteLine('Could not save a QA error report.')
    }
    [Console]::Error.WriteLine($message)
    exit 1
}

$manualPath = Join-Path $qaRoot 'manual-results.txt'
$manualTemplate = @'
Stage 10 manual UI results (fill in pass/fail and what you saw)
Windows test user:
Fresh install defaults to pet-only:
Pet display, drag, position restore, settings, tray, quit:
Bubble preview and manual update notice:
Assistant added while Codex is unavailable; pet keeps working:
After Codex login: connection, bubbles, usage, history, diagnostics:
Assistant removed: UI, hook, pet settings, custom pet:
Assistant readded: history restored; old queue and candidate UI absent:
Reinstall selection and Windows restart recovery:
Assistant center sidebar Quit exits the app process within 10 seconds:
Legacy single-bundle upgrade: waived because the app has not been distributed.
Full uninstall, keep data: DB, pet settings, custom pet, hook and startup:
Full uninstall, records only: DB and logs gone; pet settings and custom pet remain:
Full uninstall, all data: app data and old settings gone; unrelated Codex data remains:
Silent uninstall: app data remains; managed hook and startup gone:
'@
$writeManualTemplate = -not (Test-Path -LiteralPath $manualPath)
if (-not $writeManualTemplate) {
    try {
        # Replace only the known blank template corrupted by Windows PowerShell's ANSI source decoding.
        $writeManualTemplate = (Get-FileHash -LiteralPath $manualPath -Algorithm SHA256).Hash -eq
            '79E45500945BDB0D83795692BA68C40C14FD4B4B86C5148541C67EC5DA1BE653'
    } catch { $writeManualTemplate = $false }
}
if ($writeManualTemplate) {
    $manualTemplate | Set-Content -LiteralPath $manualPath -Encoding UTF8
}

if ($Action -eq 'RepairManual') {
    $backupPath = Join-Path $qaRoot ("manual-results-before-repair-$(Get-Date -Format yyyyMMdd-HHmmss).txt")
    if (Test-Path -LiteralPath $manualPath -PathType Leaf) {
        Copy-Item -LiteralPath $manualPath -Destination $backupPath
    }
    $manualTemplate | Set-Content -LiteralPath $manualPath -Encoding UTF8
    Write-Output "Readable manual results template: $manualPath"
    if (Test-Path -LiteralPath $backupPath) { Write-Output "Previous file saved: $backupPath" }
    exit 0
}

if ($Action -eq 'Export') {
    $publicRoot = [IO.Path]::GetFullPath('C:\Users\Public\Documents')
    $exportRoot = Join-Path $publicRoot ("CodexDesktopPets-stage10-results-$($env:USERNAME)-$(Get-Date -Format yyyyMMdd-HHmmss)")
    if (Test-Path -LiteralPath $exportRoot) { throw 'QA export directory already exists.' }
    New-Item -ItemType Directory -Path $exportRoot | Out-Null
    $copied = 0
    foreach ($file in @(Get-ChildItem -LiteralPath $qaRoot -File | Where-Object {
        $_.Name -eq 'manual-results.txt' -or $_.Name -match '^[a-z-]+-(running|stopped)-\d{8}-\d{6}\.json$'
    })) {
        Copy-Item -LiteralPath $file.FullName -Destination $exportRoot
        $copied++
    }
    foreach ($folder in @('installer-logs', 'command-errors')) {
        $sourceFolder = Join-Path $qaRoot $folder
        if (-not (Test-Path -LiteralPath $sourceFolder -PathType Container)) { continue }
        $destinationFolder = Join-Path $exportRoot $folder
        New-Item -ItemType Directory -Path $destinationFolder | Out-Null
        foreach ($file in @(Get-ChildItem -LiteralPath $sourceFolder -File | Where-Object {
            ($folder -eq 'installer-logs' -and $_.Extension -eq '.log') -or
            ($folder -eq 'command-errors' -and $_.Extension -eq '.json')
        })) {
            Copy-Item -LiteralPath $file.FullName -Destination $destinationFolder
            $copied++
        }
    }
    [ordered]@{
        windows_user = $env:USERNAME
        windows_machine = $env:COMPUTERNAME
        windows_sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        captured_at_utc = [DateTime]::UtcNow.ToString('o')
        copied_file_count = $copied
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $exportRoot 'export-summary.json') -Encoding UTF8
    Write-Output "QA reports exported: $exportRoot"
    exit 0
}

if ($Action -eq 'Install') {
    if (-not $Installer) { throw 'Install requires -Installer.' }
    $installerPath = (Resolve-Path -LiteralPath $Installer).Path
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) { throw 'Installer not found.' }
    $logRoot = Join-Path $qaRoot 'installer-logs'
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $logPath = Join-Path $logRoot ("$Phase-$(Get-Date -Format yyyyMMdd-HHmmss).log")
    $process = Start-Process -FilePath $installerPath -ArgumentList "/LOG=`"$logPath`"" -PassThru
    try {
        # Start-Process -Wait also waits for descendants, including the optional pet launch.
        $process.WaitForExit()
        $installerExitCode = $process.ExitCode
    } finally {
        $process.Dispose()
    }
    if ($installerExitCode -ne 0) { throw "Installer exited with $installerExitCode. Log: $logPath" }
    Write-Output "Installer finished. Log: $logPath"
    exit 0
}

if ($Action -eq 'Uninstall') {
    $uninstallerPath = Join-Path $appRoot 'unins000.exe'
    if (-not (Test-Path -LiteralPath $uninstallerPath -PathType Leaf)) {
        throw "Uninstaller not found: $uninstallerPath"
    }
    $logRoot = Join-Path $qaRoot 'installer-logs'
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $logPath = Join-Path $logRoot ("$Phase-uninstall-$(Get-Date -Format yyyyMMdd-HHmmss).log")
    $arguments = "/LOG=`"$logPath`""
    if ($SilentUninstall) { $arguments += ' /VERYSILENT' }
    $process = Start-Process -FilePath $uninstallerPath -ArgumentList $arguments -PassThru
    try {
        $process.WaitForExit()
        $uninstallerExitCode = $process.ExitCode
    } finally {
        $process.Dispose()
    }
    if ($uninstallerExitCode -ne 0) { throw "Uninstaller exited with $uninstallerExitCode. Log: $logPath" }
    Write-Output "Uninstaller finished. Log: $logPath"
    exit 0
}

if ($Action -eq 'BackupReset') {
    if (-not $ExpectedTestUser -or $env:USERNAME -ine $ExpectedTestUser) {
        throw 'BackupReset is allowed only in the explicitly named disposable test account.'
    }
    if (Test-Path -LiteralPath (Join-Path $appRoot 'runtime\pet-only\CodexDesktopPets.exe')) {
        throw 'Uninstall the application before BackupReset.'
    }
    if (Test-Path -LiteralPath (Join-Path $appRoot 'runtime\pet-assistant\CodexDesktopPets.exe')) {
        throw 'Uninstall the application before BackupReset.'
    }
    if (Test-Path -LiteralPath (Join-Path $appRoot 'CodexDesktopPets.exe')) {
        throw 'Uninstall the legacy application before BackupReset.'
    }
    if ((Test-Path -LiteralPath $appRoot -PathType Container) -and
        @(Get-ChildItem -LiteralPath $appRoot -File -Recurse).Count -gt 0) {
        throw 'Application files remain after uninstall; inspect them before BackupReset.'
    }
    if ((Managed-Hook-Count) -ne 0) {
        throw 'A managed Codex hook remains. Remove it through the application before BackupReset.'
    }
    if ($qaRoot.StartsWith($dataRoot + '\', $comparison) -or
        $qaRoot.StartsWith($appRoot + '\', $comparison)) {
        throw 'The QA output directory must be outside the app installation and data directories.'
    }
    $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $cleanBaselines = @(Get-ChildItem -LiteralPath $qaRoot -Filter 'baseline-stopped-*.json' -File |
        ForEach-Object {
            try { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json }
            catch { $null }
        } | Where-Object {
            $_ -and $_.windows_sid -eq $currentSid -and $_.windows_machine -eq $env:COMPUTERNAME -and
            $_.expected_edition -eq 'none' -and
            @($_.checks | Where-Object { -not $_.passed }).Count -eq 0
        })
    $cleanPetRuns = @(Get-ChildItem -LiteralPath $qaRoot -Filter 'fresh-pet-*.json' -File |
        ForEach-Object {
            try { Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json }
            catch { $null }
        } | Where-Object {
            $_ -and $_.windows_sid -eq $currentSid -and $_.windows_machine -eq $env:COMPUTERNAME -and
            $_.expected_edition -eq 'pet-only' -and
            @($_.checks | Where-Object { -not $_.passed }).Count -eq 0 -and
            $null -eq $_.observed.assistant_database.main -and
            $_.observed.managed_hook_marker_count -eq 0 -and
            -not $_.observed.assistant_pipe_present
        })
    if ($cleanBaselines.Count -eq 0 -and $cleanPetRuns.Count -eq 0) {
        throw 'BackupReset requires a passing clean baseline or fresh pet-only report from this same test account.'
    }
    $backupRoot = [IO.Path]::GetFullPath((Join-Path $qaRoot ("backup-before-legacy-$(Get-Date -Format yyyyMMdd-HHmmss)")))
    Assert-WithinProfile $backupRoot
    if (Test-Path -LiteralPath $backupRoot) { throw 'Backup destination already exists.' }
    New-Item -ItemType Directory -Path $backupRoot | Out-Null
    $legacyKey = 'HKCU:\Software\CodexDesktopPets\DesktopPet'
    $registryBackup = Join-Path $backupRoot 'legacy-settings.reg'
    if (Test-Path -LiteralPath $legacyKey) {
        & reg.exe export 'HKCU\Software\CodexDesktopPets\DesktopPet' $registryBackup /y | Out-Null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $registryBackup)) {
            throw 'Legacy registry backup failed; no data was moved.'
        }
    }
    $startupKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $startup = (Get-ItemProperty -LiteralPath $startupKey -Name 'CodexDesktopPets' -ErrorAction SilentlyContinue).CodexDesktopPets
    [ordered]@{
        windows_user = $env:USERNAME
        windows_machine = $env:COMPUTERNAME
        windows_sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        app_data_moved = (Test-Path -LiteralPath $dataRoot)
        startup_value = $startup
        legacy_registry_backed_up = (Test-Path -LiteralPath $registryBackup)
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backupRoot 'reset-manifest.json') -Encoding UTF8
    if (Test-Path -LiteralPath $dataRoot) {
        Move-Item -LiteralPath $dataRoot -Destination (Join-Path $backupRoot 'CodexDesktopPets')
    }
    if (Test-Path -LiteralPath $legacyKey) { Remove-Item -LiteralPath $legacyKey -Recurse }
    if ($startup -and $startup.Contains($appRoot)) {
        Remove-ItemProperty -LiteralPath $startupKey -Name 'CodexDesktopPets'
    }
    Write-Output "Test-account data was backed up and reset: $backupRoot"
    exit 0
}

$edition = switch ($Phase) {
    'fresh-pet' { 'pet-only' }
    'pet-after-removal' { 'pet-only' }
    'assistant-disconnected' { 'pet-assistant' }
    'assistant-connected' { 'pet-assistant' }
    'assistant-readded' { 'pet-assistant' }
    'assistant-reinstalled' { 'pet-assistant' }
    'legacy-before' { 'legacy' }
    'legacy-upgraded' { 'pet-assistant' }
    default { 'none' }
}
$petExe = Join-Path $appRoot 'runtime\pet-only\CodexDesktopPets.exe'
$assistantExe = Join-Path $appRoot 'runtime\pet-assistant\CodexDesktopPets.exe'
$legacyExe = Join-Path $appRoot 'CodexDesktopPets.exe'
$helperRoot = Join-Path $appRoot 'hook-cleanup-helper'
$expectedExe = switch ($edition) {
    'pet-only' { $petExe }
    'pet-assistant' { $assistantExe }
    'legacy' { $legacyExe }
    default { '' }
}
$dbPath = Join-Path $dataRoot 'assistant-v1.sqlite3'
$dbSidecars = @('assistant-v1.sqlite3-wal', 'assistant-v1.sqlite3-shm')
$petRoot = Join-Path $dataRoot 'pets'
$qaPetRoot = Join-Path $petRoot 'stage10-qa-mori'
$legacySettingsKey = 'HKCU:\Software\CodexDesktopPets\DesktopPet'
$startupKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$startupValue = (Get-ItemProperty -LiteralPath $startupKey -Name 'CodexDesktopPets' -ErrorAction SilentlyContinue).CodexDesktopPets
$managedStartup = $startupValue -and (
    $startupValue.Contains($appRoot + '\') -or
    $startupValue.Trim('"') -ieq $legacyExe
)
$recordFiles = if (Test-Path -LiteralPath $dataRoot -PathType Container) {
    @(Get-ChildItem -LiteralPath $dataRoot -File | Where-Object {
        $_.Name -like 'assistant-v1.sqlite3*' -or $_.Name -like 'usage-history-v1.json*'
    })
} else { @() }
$hookCount = Managed-Hook-Count
$processProbe = 'available'
try {
    $appProcesses = @(Get-CimInstance Win32_Process -Filter "Name='CodexDesktopPets.exe'" | ForEach-Object {
        [ordered]@{ pid = $_.ProcessId; executable = $_.ExecutablePath }
    })
} catch {
    try {
        $appProcesses = @(Get-Process -Name 'CodexDesktopPets' -ErrorAction SilentlyContinue | ForEach-Object {
            [ordered]@{ pid = $_.Id; executable = $_.Path }
        })
        $processProbe = 'Get-Process fallback'
    } catch {
        $processProbe = $_.Exception.GetType().Name
        $appProcesses = @()
    }
}
$ownedProcesses = @($appProcesses | Where-Object {
    $_.executable -and $_.executable.StartsWith($appRoot + '\', $comparison)
})
$pipeProbe = 'available'
try {
    $pipeFound = @(Get-ChildItem -LiteralPath '\\.\pipe\' -ErrorAction Stop | Where-Object {
        $_.Name -eq 'codex-desktop-pets-agent-v1'
    }).Count -gt 0
} catch {
    $pipeProbe = $_.Exception.GetType().Name
    $pipeFound = $null
}
$dbFiles = [ordered]@{ main = (File-Record $dbPath) }
foreach ($name in $dbSidecars) { $dbFiles[$name] = File-Record (Join-Path $dataRoot $name) }
$customPetCount = if (Test-Path -LiteralPath $petRoot -PathType Container) {
    @(Get-ChildItem -LiteralPath $petRoot -Directory).Count
} else { 0 }
$qaPetManifest = File-Record (Join-Path $qaPetRoot 'pet.json')
$qaPetSprite = File-Record (Join-Path $qaPetRoot 'spritesheet.webp')
$checks = [System.Collections.ArrayList]::new()
if ($edition -eq 'none') {
    Add-Check $checks 'no_installed_runtime' (-not ((Test-Path $petExe) -or (Test-Path $assistantExe) -or (Test-Path $legacyExe)))
    if ($Phase -ne 'uninstall-keep') {
        Add-Check $checks 'no_assistant_database' (-not (Test-Path $dbPath))
    }
    Add-Check $checks 'no_managed_hook' ($hookCount -eq 0)
    Add-Check $checks 'no_assistant_pipe' ($pipeProbe -eq 'available' -and -not $pipeFound)
} elseif ($edition -eq 'legacy') {
    Add-Check $checks 'legacy_executable_present' (Test-Path $legacyExe -PathType Leaf)
} else {
    Add-Check $checks 'selected_executable_present' (Test-Path $expectedExe -PathType Leaf)
    Add-Check $checks 'other_runtime_absent' (-not (Test-Path $(if ($edition -eq 'pet-only') { Split-Path -Parent $assistantExe } else { Split-Path -Parent $petExe })))
    Add-Check $checks 'legacy_executable_absent' (-not (Test-Path $legacyExe))
    Add-Check $checks 'cleanup_helper_absent' (-not (Test-Path $helperRoot))
}
if ($Phase -in @('uninstall-records', 'uninstall-all', 'uninstall-keep')) {
    Add-Check $checks 'managed_startup_absent' (-not $managedStartup)
}
if ($Phase -eq 'uninstall-records') {
    Add-Check $checks 'record_files_absent' ($recordFiles.Count -eq 0)
    Add-Check $checks 'app_logs_absent' (-not (Test-Path (Join-Path $dataRoot 'logs')))
    Add-Check $checks 'temporary_events_absent' (-not (Test-Path (Join-Path $dataRoot 'runtime')))
    Add-Check $checks 'pet_settings_preserved' (Test-Path (Join-Path $dataRoot 'settings.ini') -PathType Leaf)
    Add-Check $checks 'qa_custom_pet_preserved' ($null -ne $qaPetManifest -and $null -ne $qaPetSprite)
}
if ($Phase -eq 'uninstall-all') {
    Add-Check $checks 'app_data_absent' (-not (Test-Path -LiteralPath $dataRoot))
    Add-Check $checks 'legacy_registry_absent' (-not (Test-Path $legacySettingsKey))
}
if ($Phase -eq 'uninstall-keep') {
    Add-Check $checks 'assistant_database_preserved' (Test-Path $dbPath -PathType Leaf)
    Add-Check $checks 'pet_settings_preserved' (Test-Path (Join-Path $dataRoot 'settings.ini') -PathType Leaf)
    Add-Check $checks 'qa_custom_pet_preserved' ($null -ne $qaPetManifest -and $null -ne $qaPetSprite)
}
if ($Phase -in @('fresh-pet', 'pet-after-removal')) {
    Add-Check $checks 'managed_hook_absent' ($hookCount -eq 0)
}
if ($Phase -eq 'fresh-pet') {
    Add-Check $checks 'assistant_database_absent' (-not (Test-Path $dbPath))
    Add-Check $checks 'assistant_pipe_absent' ($pipeProbe -eq 'available' -and -not $pipeFound)
}
if ($Phase -eq 'assistant-connected') {
    Add-Check $checks 'managed_hook_installed' ($hookCount -gt 0)
}
if ($Phase -in @('assistant-disconnected', 'assistant-connected', 'pet-after-removal', 'assistant-readded', 'assistant-reinstalled', 'legacy-before', 'legacy-upgraded')) {
    Add-Check $checks 'qa_custom_pet_present' ($null -ne $qaPetManifest -and $null -ne $qaPetSprite)
}
if ($Phase -in @('assistant-connected', 'pet-after-removal', 'assistant-readded', 'assistant-reinstalled', 'legacy-before', 'legacy-upgraded')) {
    Add-Check $checks 'assistant_database_preserved' (Test-Path $dbPath -PathType Leaf)
}
if ($Phase -eq 'legacy-before') {
    Add-Check $checks 'legacy_registry_settings_present' (Test-Path $legacySettingsKey)
    Add-Check $checks 'new_settings_file_absent' (-not (Test-Path (Join-Path $dataRoot 'settings.ini')))
}
if ($Phase -eq 'legacy-upgraded') {
    Add-Check $checks 'settings_ini_present' (Test-Path (Join-Path $dataRoot 'settings.ini') -PathType Leaf)
    Add-Check $checks 'legacy_registry_settings_preserved' (Test-Path $legacySettingsKey)
}
if ($When -eq 'Running' -and $edition -ne 'none') {
    Add-Check $checks 'exactly_one_owned_process' ($processProbe -in @('available', 'Get-Process fallback') -and $ownedProcesses.Count -eq 1)
    Add-Check $checks 'process_uses_selected_executable' ($ownedProcesses.Count -eq 1 -and $ownedProcesses[0].executable -ieq $expectedExe)
    if ($edition -eq 'pet-assistant') {
        Add-Check $checks 'assistant_pipe_present' ($pipeProbe -eq 'available' -and $pipeFound)
    }
} elseif ($When -eq 'Stopped') {
    Add-Check $checks 'application_stopped' ($processProbe -in @('available', 'Get-Process fallback') -and $ownedProcesses.Count -eq 0)
}
$report = [ordered]@{
    schema_version = 1
    phase = $Phase
    when = $When
    captured_at_utc = [DateTime]::UtcNow.ToString('o')
    windows_user = $env:USERNAME
    windows_machine = $env:COMPUTERNAME
    windows_sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    expected_edition = $edition
    checks = @($checks)
    observed = [ordered]@{
        pet_executable = (Test-Path $petExe -PathType Leaf)
        assistant_executable = (Test-Path $assistantExe -PathType Leaf)
        legacy_executable = (Test-Path $legacyExe -PathType Leaf)
        cleanup_helper = (Test-Path $helperRoot)
        settings = File-Record (Join-Path $dataRoot 'settings.ini')
        legacy_settings_registry_present = (Test-Path $legacySettingsKey)
        assistant_database = $dbFiles
        custom_pet_directory_count = $customPetCount
        qa_custom_pet_manifest = $qaPetManifest
        qa_custom_pet_sprite = $qaPetSprite
        managed_hook_marker_count = $hookCount
        managed_startup_present = [bool]$managedStartup
        record_file_count = $recordFiles.Count
        process_probe = $processProbe
        app_processes = $ownedProcesses
        pipe_probe = $pipeProbe
        assistant_pipe_present = $pipeFound
    }
}
$reportPath = Join-Path $qaRoot ("$Phase-$($When.ToLower())-$(Get-Date -Format yyyyMMdd-HHmmss).json")
$report | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath $reportPath -Encoding UTF8
$failed = @($checks | Where-Object { -not $_.passed })
Write-Output "QA report: $reportPath"
Write-Output "Checks passed: $($checks.Count - $failed.Count)/$($checks.Count)"
if ($failed.Count) {
    $failed | ForEach-Object { Write-Output "FAILED: $($_.name)" }
    exit 1
}
