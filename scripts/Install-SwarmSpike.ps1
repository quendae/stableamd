[CmdletBinding()]
param(
    [ValidateSet('Baseline', 'GfxOverride')]
    [string]$Mode = 'Baseline',

    [string]$SwarmRef = '0.9.8-Beta',

    [string]$RuntimeRoot = '',

    [int]$StartupTimeoutSeconds = 300,

    [switch]$RefreshCheckout
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'The SwarmUI RX 6950 XT spike bootstrap is Windows-only.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Hardware.psm1') -Force

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $repoRoot '.runtime'
}

$git = Get-Command git -ErrorAction SilentlyContinue
if ($null -eq $git) {
    throw 'Git is required. Install Git for Windows, reopen PowerShell, then rerun this script.'
}

$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if ($null -eq $dotnet) {
    throw 'The .NET SDK is required for this manual SwarmUI spike path. Install the current .NET 8 SDK (and optionally .NET 10 as recommended upstream), reopen PowerShell, then rerun this script.'
}

$swarmPath = Join-Path $RuntimeRoot 'SwarmUI'
$diagnosticsPath = Join-Path $repoRoot 'diagnostics'
New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $diagnosticsPath -Force | Out-Null

if (-not (Test-Path (Join-Path $swarmPath '.git'))) {
    Write-Host "Cloning SwarmUI into $swarmPath ..." -ForegroundColor Cyan
    & $git.Source clone https://github.com/mcmonkeyprojects/SwarmUI.git $swarmPath
    if ($LASTEXITCODE -ne 0) {
        throw "git clone failed with exit code $LASTEXITCODE"
    }
}
elseif ($RefreshCheckout) {
    Write-Host 'Refreshing existing SwarmUI checkout...' -ForegroundColor Cyan
    & $git.Source -C $swarmPath fetch --tags --prune
    if ($LASTEXITCODE -ne 0) {
        throw "git fetch failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Checking out SwarmUI ref $SwarmRef ..." -ForegroundColor Cyan
& $git.Source -C $swarmPath checkout --force $SwarmRef
if ($LASTEXITCODE -ne 0) {
    & $git.Source -C $swarmPath fetch --tags --prune
    if ($LASTEXITCODE -ne 0) {
        throw "git fetch failed while resolving '$SwarmRef'"
    }
    & $git.Source -C $swarmPath checkout --force $SwarmRef
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to checkout SwarmUI ref '$SwarmRef'."
    }
}

$environmentForChild = Get-StableAmdSpikeEnvironment -Mode $Mode
$oldOverride = [Environment]::GetEnvironmentVariable('HSA_OVERRIDE_GFX_VERSION', 'Process')
$hadOverride = $null -ne $oldOverride

try {
    if ($Mode -eq 'GfxOverride') {
        $env:HSA_OVERRIDE_GFX_VERSION = $environmentForChild['HSA_OVERRIDE_GFX_VERSION']
        Write-Warning 'Launching compatibility test with HSA_OVERRIDE_GFX_VERSION=10.3.0.'
    }
    else {
        Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
        Write-Host 'Launching baseline test with no HSA_OVERRIDE_GFX_VERSION.' -ForegroundColor Yellow
    }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdoutPath = Join-Path $diagnosticsPath "swarm-$($Mode.ToLowerInvariant())-$stamp.stdout.log"
    $stderrPath = Join-Path $diagnosticsPath "swarm-$($Mode.ToLowerInvariant())-$stamp.stderr.log"

    $launchBat = Join-Path $swarmPath 'launch-windows.bat'
    if (-not (Test-Path $launchBat)) {
        throw "SwarmUI launch script not found at $launchBat"
    }

    Write-Host 'Starting SwarmUI...' -ForegroundColor Cyan
    $process = Start-Process `
        -FilePath 'cmd.exe' `
        -ArgumentList '/d', '/c', 'launch-windows.bat --launch_mode none' `
        -WorkingDirectory $swarmPath `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru
}
finally {
    if ($hadOverride) {
        $env:HSA_OVERRIDE_GFX_VERSION = $oldOverride
    }
    else {
        Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
    }
}

$deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
$reachable = $false
while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) {
        break
    }

    try {
        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:7801/' -UseBasicParsing -TimeoutSec 3
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            $reachable = $true
            break
        }
    }
    catch {
        Start-Sleep -Seconds 2
    }
}

$exitCode = $null
if ($process.HasExited) {
    $exitCode = $process.ExitCode
}

$result = [pscustomobject]@{
    CreatedAtUtc = [DateTime]::UtcNow.ToString('o')
    Mode = $Mode
    SwarmRef = $SwarmRef
    SwarmPath = $swarmPath
    ProcessId = $process.Id
    ProcessExited = $process.HasExited
    ExitCode = $exitCode
    HttpReachable = $reachable
    Url = 'http://127.0.0.1:7801/'
    StdoutLog = $stdoutPath
    StderrLog = $stderrPath
}

$resultPath = Join-Path $diagnosticsPath "swarm-launch-$($Mode.ToLowerInvariant())-$stamp.json"
$result | ConvertTo-Json -Depth 5 | Set-Content -Path $resultPath -Encoding UTF8

if ($reachable) {
    Write-Host ''
    Write-Host 'SwarmUI is reachable.' -ForegroundColor Green
    Write-Host 'Open http://127.0.0.1:7801/ and complete the upstream installer.'
    Write-Host 'Choose the AMD-compatible ComfyUI backend when prompted.' -ForegroundColor Yellow
    Write-Host "Launch report: $resultPath"
    Write-Host 'After the backend installation completes, run scripts/Test-SwarmBackend.ps1.' -ForegroundColor Cyan
}
else {
    Write-Warning 'SwarmUI did not become reachable within the startup window.'
    Write-Host "stdout: $stdoutPath"
    Write-Host "stderr: $stderrPath"
    Write-Host "report: $resultPath"
    if ($process.HasExited) {
        throw "SwarmUI exited with code $($process.ExitCode). Review the diagnostic logs."
    }
    throw 'SwarmUI is still running but did not answer on port 7801. Review the diagnostic logs.'
}

return $result
