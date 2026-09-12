[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$Port = 0,
    [int]$StartupTimeoutSeconds = 0,
    [switch]$ForceRestart
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'StableAMD v0.1 managed backend is Windows-only.'
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

$runtimeModule = Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1'
Import-Module $runtimeModule -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths
$config = Read-StableAmdConfig -RepoRoot $RepoRoot

$hostAddress = [string]$config.backend.host
if ($hostAddress -ne '127.0.0.1') {
    throw "StableAMD v0.1 only supports loopback binding. Configured backend host '$hostAddress' is not allowed."
}

$resolvedPort = if ($Port -gt 0) { $Port } else { [int]$config.backend.port }
if ($resolvedPort -lt 1 -or $resolvedPort -gt 65535) {
    throw "Backend port '$resolvedPort' is outside the valid range 1-65535."
}

$resolvedTimeout = if ($StartupTimeoutSeconds -gt 0) { $StartupTimeoutSeconds } else { [int]$config.backend.startupTimeoutSeconds }
if ($resolvedTimeout -lt 5) {
    throw 'Backend startup timeout must be at least 5 seconds.'
}

$comfyMain = Join-Path $paths.ComfyRoot 'main.py'
$comfyApiInput = Join-Path $paths.ComfyRoot 'comfy_api/input/__init__.py'
foreach ($required in @($paths.TheRockPython, $comfyMain, $comfyApiInput, $paths.ComfyRunner)) {
    if (-not (Test-Path $required)) {
        throw "StableAMD runtime component is missing: '$required'. Complete the TheRock/ComfyUI installation first."
    }
}

function Test-ExistingStableAmdBackend {
    param([psobject]$State)

    if ($null -eq $State -or $null -eq $State.pid) {
        return $null
    }

    $statePid = [int]$State.pid
    $process = Get-Process -Id $statePid -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return $null
    }

    $url = [string]$State.url
    if ([string]::IsNullOrWhiteSpace($url)) {
        return $null
    }
    if (-not $url.EndsWith('/')) { $url += '/' }

    try {
        $stats = Invoke-RestMethod -Uri "${url}system_stats" -Method Get -TimeoutSec 3
        if ($null -ne $stats) {
            return [pscustomobject]@{
                Process = $process
                Stats = $stats
                Url = $url
            }
        }
    }
    catch { }

    return $null
}

$existingState = Read-StableAmdBackendState -Path $paths.BackendStatePath
if ($null -ne $existingState) {
    $existingHealthy = Test-ExistingStableAmdBackend -State $existingState
    if ($null -ne $existingHealthy -and -not $ForceRestart) {
        $existingDevice = @($existingHealthy.Stats.devices) | Select-Object -First 1
        return [pscustomobject]@{
            Status = 'running'
            Running = $true
            Healthy = $true
            Reused = $true
            Pid = [int]$existingState.pid
            Url = $existingHealthy.Url
            Device = $existingDevice
            StatePath = $paths.BackendStatePath
            StdoutLog = $existingState.stdoutLog
            StderrLog = $existingState.stderrLog
        }
    }

    if ($ForceRestart) {
        & (Join-Path $PSScriptRoot 'Stop-StableAMD.ps1') -RepoRoot $RepoRoot -BackendOnly | Out-Null
    }
    elseif ($null -eq (Get-Process -Id ([int]$existingState.pid) -ErrorAction SilentlyContinue)) {
        Remove-StableAmdBackendState -Path $paths.BackendStatePath
    }
    else {
        throw "A StableAMD-managed process with PID $($existingState.pid) exists but is not healthy. Run Stop-StableAMD.ps1 -BackendOnly or retry with -ForceRestart."
    }
}

# ComfyUI reads external checkpoint folders only at backend startup. Build the
# generated extra_model_paths.yaml from every configured StableAMD model root.
$modelRoots = @()
$seenRoots = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($rawRoot in @($config.models.roots)) {
    $raw = [string]$rawRoot
    if ([string]::IsNullOrWhiteSpace($raw)) { continue }
    $resolved = Resolve-StableAmdPath -Path $raw -RepoRoot $RepoRoot
    if (-not (Test-Path $resolved -PathType Container)) { continue }
    if ($seenRoots.Add($resolved)) { $modelRoots += $resolved }
}
if ($seenRoots.Add($paths.CheckpointsRoot)) {
    $modelRoots = @($paths.CheckpointsRoot) + @($modelRoots)
}

$modelConfigPath = Join-Path $paths.GeneratedConfigRoot 'extra_model_paths.yaml'
$yaml = New-Object System.Collections.Generic.List[string]
$rootIndex = 0
foreach ($modelRoot in $modelRoots) {
    $yamlRoot = $modelRoot.Replace('\', '/')
    $yaml.Add("stableamd_root_$rootIndex`:")
    $yaml.Add("    base_path: `"$yamlRoot`"")
    $yaml.Add('    checkpoints: .')
    $rootIndex++
}
$yaml | Set-Content -Path $modelConfigPath -Encoding UTF8

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdoutPath = Join-Path $paths.LogsRoot "backend-$stamp.stdout.log"
$stderrPath = Join-Path $paths.LogsRoot "backend-$stamp.stderr.log"
$url = "http://127.0.0.1:$resolvedPort/"
$statsUrl = "${url}system_stats"

$arguments = "-s `"$($paths.ComfyRunner)`" `"$($paths.ComfyRoot)`" --listen 127.0.0.1 --port $resolvedPort --extra-model-paths-config `"$modelConfigPath`" --output-directory `"$($paths.OutputRoot)`""

$oldOverride = [Environment]::GetEnvironmentVariable('HSA_OVERRIDE_GFX_VERSION', 'Process')
$hadOverride = $null -ne $oldOverride
Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue

$process = $null
try {
    $process = Start-Process `
        -FilePath $paths.TheRockPython `
        -ArgumentList $arguments `
        -WorkingDirectory $paths.ComfyRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -WindowStyle Hidden `
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

$deadline = (Get-Date).AddSeconds($resolvedTimeout)
$stats = $null
while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) { break }
    try {
        $stats = Invoke-RestMethod -Uri $statsUrl -Method Get -TimeoutSec 5
        if ($null -ne $stats) { break }
    }
    catch { }
    Start-Sleep -Seconds 2
}

if ($null -eq $stats) {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    }

    $tail = ''
    if (Test-Path $stderrPath) {
        $tail = (@(Get-Content -Path $stderrPath -Tail 80 -ErrorAction SilentlyContinue) -join "`n")
    }
    if ([string]::IsNullOrWhiteSpace($tail)) {
        throw "StableAMD backend did not become healthy at '$statsUrl' within $resolvedTimeout seconds. See '$stderrPath'."
    }
    throw "StableAMD backend did not become healthy at '$statsUrl'. Last stderr lines:`n$tail"
}

$devices = @($stats.devices)
$device = $devices | Where-Object { [string]$_.name -match '(?i)AMD|Radeon' } | Select-Object -First 1
if ($null -eq $device) {
    $device = $devices | Select-Object -First 1
}
if ($null -eq $device) {
    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    throw 'ComfyUI is reachable but /system_stats reported no compute device.'
}

$state = [pscustomobject]@{
    schemaVersion = 1
    role = 'compute-backend'
    pid = $process.Id
    url = $url
    startedAtUtc = [DateTime]::UtcNow.ToString('o')
    pythonPath = $paths.TheRockPython
    comfyRoot = $paths.ComfyRoot
    modelConfigPath = $modelConfigPath
    outputRoot = $paths.OutputRoot
    stdoutLog = $stdoutPath
    stderrLog = $stderrPath
    device = [pscustomobject]@{
        name = [string]$device.name
        type = [string]$device.type
        vramTotal = $device.vram_total
    }
}
Write-StableAmdBackendState -Path $paths.BackendStatePath -State $state

return [pscustomobject]@{
    Status = 'running'
    Running = $true
    Healthy = $true
    Reused = $false
    Pid = $process.Id
    Url = $url
    Device = $state.device
    StatePath = $paths.BackendStatePath
    StdoutLog = $stdoutPath
    StderrLog = $stderrPath
}
