# Optional Authenticode signing shared by build_windows.ps1 and build_installer.ps1
# (docs/public/signing.md). Without a certificate thumbprint nothing is signed
# and the builds stay unsigned candidates.

# File types Windows checks signatures on. Already signed vendor files stay as they are.
$script:SignedExtensions = @(".exe", ".dll", ".pyd", ".node")

function Get-CodeSigningConfig([string]$Thumbprint) {
    if (-not $Thumbprint) { $Thumbprint = $env:WATCHED_KETTLE_SIGNING_THUMBPRINT }
    if (-not $Thumbprint) { return $null }
    $Thumbprint = ($Thumbprint -replace '\s', '').ToUpperInvariant()
    if ($Thumbprint -notmatch '^[0-9A-F]{40}$') {
        throw "The signing certificate thumbprint must be 40 hexadecimal characters."
    }
    # SimplySign Desktop (or a token driver) puts the certificate in this store
    # while it is connected.
    $certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$Thumbprint" -ErrorAction SilentlyContinue
    if (-not $certificate) {
        throw "Signing certificate $Thumbprint is not in the current user's certificate store. Connect the signing service first."
    }
    if ($certificate.EnhancedKeyUsageList.ObjectId -notcontains "1.3.6.1.5.5.7.3.3") {
        throw "Certificate $Thumbprint is not a code signing certificate."
    }
    if ($certificate.NotAfter -le (Get-Date)) {
        throw "Signing certificate $Thumbprint expired on $($certificate.NotAfter)."
    }
    $timestampUrl = if ($env:WATCHED_KETTLE_SIGNING_TIMESTAMP_URL) { $env:WATCHED_KETTLE_SIGNING_TIMESTAMP_URL } else { "http://time.certum.pl" }
    $signTool = $env:WATCHED_KETTLE_SIGNTOOL
    if (-not $signTool) {
        # The newest Windows SDK's x64 signtool.
        $signTool = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin\10.*\x64\signtool.exe" -ErrorAction SilentlyContinue |
            Sort-Object { [version]$_.Directory.Parent.Name } -Descending |
            Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $signTool -or -not (Test-Path -LiteralPath $signTool -PathType Leaf)) {
        throw "signtool.exe was not found. Install the Windows SDK or set WATCHED_KETTLE_SIGNTOOL."
    }
    # Unchanged binaries reuse their earlier signed bytes, so partial updates
    # (ADR 0007) do not resend them only because a new timestamp was added.
    $cacheRoot = if ($env:WATCHED_KETTLE_SIGNING_CACHE) { $env:WATCHED_KETTLE_SIGNING_CACHE } else { Join-Path $env:LOCALAPPDATA "WatchedKettleBuild\signing-cache" }
    [pscustomobject]@{
        Thumbprint = $Thumbprint
        Subject = $certificate.Subject
        TimestampUrl = $timestampUrl
        SignTool = $signTool
        CacheRoot = Join-Path $cacheRoot $Thumbprint
    }
}

# Arguments before the file names; build_installer.ps1 passes the same ones to Inno Setup.
function Get-SignToolArguments($Config) {
    @("sign", "/sha1", $Config.Thumbprint, "/fd", "SHA256", "/tr", $Config.TimestampUrl, "/td", "SHA256")
}

function Invoke-CodeSigning($Config, [string[]]$Paths) {
    if (-not $Paths) { return }
    & $Config.SignTool @(Get-SignToolArguments $Config) @Paths
    if ($LASTEXITCODE -ne 0) { throw "signtool failed to sign $($Paths.Count) file(s)." }
    Assert-CodeSigned $Config $Paths
}

function Assert-CodeSigned($Config, [string[]]$Paths) {
    foreach ($path in $Paths) {
        $signature = Get-AuthenticodeSignature -LiteralPath $path
        if ($signature.Status -ne 'Valid' -or
            $signature.SignerCertificate.Thumbprint -ne $Config.Thumbprint -or
            -not $signature.TimeStamperCertificate) {
            throw "Not validly signed and timestamped by $($Config.Thumbprint) ($($signature.Status)): $path"
        }
    }
}

# Signs every unsigned executable file in a bundle, reusing cached signed copies.
function Invoke-BundleCodeSigning($Config, [string]$Root) {
    $targets = @(Get-ChildItem -LiteralPath $Root -Recurse -File |
        Where-Object { $script:SignedExtensions -contains $_.Extension.ToLowerInvariant() } |
        Where-Object { (Get-AuthenticodeSignature -LiteralPath $_.FullName).Status -eq 'NotSigned' } |
        ForEach-Object { $_.FullName })
    New-Item -ItemType Directory -Path $Config.CacheRoot -Force | Out-Null
    $pending = @()
    foreach ($path in $targets) {
        $cached = Join-Path $Config.CacheRoot (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if (Test-Path -LiteralPath $cached -PathType Leaf) {
            Copy-Item -LiteralPath $cached -Destination $path -Force
        } else {
            $pending += [pscustomobject]@{ Path = $path; Cache = $cached }
        }
    }
    Invoke-CodeSigning $Config @($pending | ForEach-Object { $_.Path })
    Assert-CodeSigned $Config $targets
    foreach ($item in $pending) { Copy-Item -LiteralPath $item.Path -Destination $item.Cache -Force }
    Write-Host "Signed $($targets.Count) file(s), $($targets.Count - $pending.Count) from the signing cache: $Root"
}
