[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$Tail = 30
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$backend = Read-StableAmdBackendState -Path $paths.BackendStatePath
$app = Read-StableAmdBackendState -Path $paths.AppStatePath

Write-Host ''
Write-Host 'StableAMD live diagnostics' -ForegroundColor Cyan
if ($null -ne $backend) {
    Write-Host "Compute backend PID: $($backend.pid)" -ForegroundColor Green
    Write-Host "Compute backend URL: $($backend.url)" -ForegroundColor DarkGray
}
else {
    Write-Host 'Compute backend state: not running / not tracked' -ForegroundColor Yellow
}
if ($null -ne $app) {
    Write-Host "Application PID: $($app.pid)" -ForegroundColor Green
    Write-Host "Application URL: $($app.url)" -ForegroundColor DarkGray
}
else {
    Write-Host 'Application state: not running / not tracked' -ForegroundColor Yellow
}

$logs = New-Object System.Collections.Generic.List[string]
foreach ($state in @($backend, $app)) {
    if ($null -eq $state) { continue }
    foreach ($propertyName in @('stdoutLog', 'stderrLog')) {
        $property = $state.PSObject.Properties[$propertyName]
        if ($null -eq $property) { continue }
        $path = [string]$property.Value
        if (-not [string]::IsNullOrWhiteSpace($path) -and (Test-Path $path -PathType Leaf) -and -not $logs.Contains($path)) {
            $logs.Add($path)
        }
    }
}

if ($logs.Count -eq 0) {
    throw 'No active StableAMD log files were found. Start StableAMD first.'
}

Write-Host ''
Write-Host 'Watching logs (Ctrl+C to stop watching; StableAMD keeps running):' -ForegroundColor Cyan
foreach ($log in $logs) {
    Write-Host "  $log" -ForegroundColor DarkGray
}
Write-Host ''

# ComfyUI emits model-loading, execution and sampler/tqdm progress through its
# stdout/stderr streams. Tailing both managed processes keeps those details
# available for diagnostics without exposing separate Python console windows.
Get-Content -Path @($logs) -Tail ([Math]::Max(0, $Tail)) -Wait
