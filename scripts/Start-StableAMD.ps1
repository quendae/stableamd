[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$Port = 0,
    [int]$StartupTimeoutSeconds = 0,
    [switch]$ForceRestart,
    [switch]$DisableDynamicVram
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'StableAMD managed backend is Windows-only.'
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
    throw "StableAMD only supports loopback binding. Configured backend host '$hostAddress' is not allowed."
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

    if ($null -eq $State -or $null -eq $State.pid) { return $null }
    $statePid = [int]$State.pid
    $process = Get-Process -Id $statePid -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }

    $url = [string]$State.url
    if ([string]::IsNullOrWhiteSpace($url)) { return $null }
    if (-not $url.EndsWith('/')) { $url += '/' }

    try {
        $stats = Invoke-RestMethod -Uri "${url}system_stats" -Method Get -TimeoutSec 3
        if ($null -ne $stats) {
            return [pscustomobject]@{ Process = $process; Stats = $stats; Url = $url }
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
        throw "A StableAMD-managed process with PID $($existingState.pid) exists but is not healthy. Run Stop-StableAMD.ps1 or retry with -ForceRestart."
    }
}

function Get-StableAmdExistingRoots {
    param(
        [AllowEmptyCollection()][object[]]$RawRoots,
        [string]$ManagedRoot
    )

    $result = @()
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    if (-not [string]::IsNullOrWhiteSpace($ManagedRoot) -and $seen.Add($ManagedRoot)) {
        $result += $ManagedRoot
    }
    foreach ($rawRoot in @($RawRoots)) {
        $raw = [string]$rawRoot
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        $resolved = Resolve-StableAmdPath -Path $raw -RepoRoot $RepoRoot
        if (-not (Test-Path $resolved -PathType Container)) { continue }
        if ($seen.Add($resolved)) { $result += $resolved }
    }
    return @($result)
}

$modelRoots = @(Get-StableAmdExistingRoots -RawRoots @($config.models.roots) -ManagedRoot $paths.CheckpointsRoot)
$loraRoots = @(Get-StableAmdExistingRoots -RawRoots @($config.loras.roots) -ManagedRoot $paths.LorasRoot)
$diffusionModelRoots = @(Get-StableAmdExistingRoots -RawRoots @($config.bundleAssets.diffusionModels.roots) -ManagedRoot $paths.DiffusionModelsRoot)
$textEncoderRoots = @(Get-StableAmdExistingRoots -RawRoots @($config.bundleAssets.textEncoders.roots) -ManagedRoot $paths.TextEncodersRoot)
$vaeRoots = @(Get-StableAmdExistingRoots -RawRoots @($config.bundleAssets.vae.roots) -ManagedRoot $paths.VaeRoot)

$modelConfigPath = Join-Path $paths.GeneratedConfigRoot 'extra_model_paths.yaml'
$yaml = New-Object System.Collections.Generic.List[string]

function Add-StableAmdExtraModelRoot {
    param(
        [string]$Prefix,
        [string]$FolderType,
        [string[]]$Roots
    )

    $index = 0
    foreach ($root in @($Roots)) {
        $yamlRoot = $root.Replace('\', '/')
        $yaml.Add("stableamd_${Prefix}_root_$index`:")
        $yaml.Add("    base_path: `"$yamlRoot`"")
        $yaml.Add("    ${FolderType}: .")
        $index++
    }
}

Add-StableAmdExtraModelRoot -Prefix 'checkpoint' -FolderType 'checkpoints' -Roots $modelRoots
Add-StableAmdExtraModelRoot -Prefix 'lora' -FolderType 'loras' -Roots $loraRoots
Add-StableAmdExtraModelRoot -Prefix 'diffusion_model' -FolderType 'diffusion_models' -Roots $diffusionModelRoots
Add-StableAmdExtraModelRoot -Prefix 'text_encoder' -FolderType 'text_encoders' -Roots $textEncoderRoots
Add-StableAmdExtraModelRoot -Prefix 'vae' -FolderType 'vae' -Roots $vaeRoots
$yaml | Set-Content -Path $modelConfigPath -Encoding UTF8

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdoutPath = Join-Path $paths.LogsRoot "backend-$stamp.stdout.log"
$stderrPath = Join-Path $paths.LogsRoot "backend-$stamp.stderr.log"
$url = "http://127.0.0.1:$resolvedPort/"
$statsUrl = "${url}system_stats"

$arguments = "-u -s `"$($paths.ComfyRunner)`" `"$($paths.ComfyRoot)`" --listen 127.0.0.1 --port $resolvedPort --extra-model-paths-config `"$modelConfigPath`" --input-directory `"$($paths.InputRoot)`" --output-directory `"$($paths.OutputRoot)`""
if ($DisableDynamicVram) {
    $arguments += ' --disable-dynamic-vram'
}

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
    if ($hadOverride) { $env:HSA_OVERRIDE_GFX_VERSION = $oldOverride }
    else { Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue }
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
if ($null -eq $device) { $device = $devices | Select-Object -First 1 }
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
    inputRoot = $paths.InputRoot
    outputRoot = $paths.OutputRoot
    stdoutLog = $stdoutPath
    stderrLog = $stderrPath
    dynamicVramDisabled = [bool]$DisableDynamicVram
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
    DynamicVramDisabled = [bool]$DisableDynamicVram
    StatePath = $paths.BackendStatePath
    StdoutLog = $stdoutPath
    StderrLog = $stderrPath
}
