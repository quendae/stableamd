[CmdletBinding()]
param(
    [string]$RuntimeRoot = '',
    [string]$OutputDirectory = '',
    [int]$Port = 8190,
    [int]$StartupTimeoutSeconds = 240,
    [switch]$RefreshCopy,
    [switch]$KeepRunning
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'The TheRock ComfyUI integration test is Windows-only.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $repoRoot '.runtime'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot 'diagnostics'
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$swarmRoot = Join-Path $RuntimeRoot 'SwarmUI'
$sourceComfyRoot = Join-Path $swarmRoot 'dlbackend/comfy/ComfyUI'
$sourceComfyMain = Join-Path $sourceComfyRoot 'main.py'
$isolatedComfyBase = Join-Path $RuntimeRoot 'therock-comfy'
$comfyRoot = Join-Path $isolatedComfyBase 'ComfyUI'
$comfyMain = Join-Path $comfyRoot 'main.py'
$theRockRoot = Join-Path $RuntimeRoot 'therock-gfx1030'
$theRockPythonRoot = Join-Path $theRockRoot 'python_embeded'
$theRockPython = Join-Path $theRockPythonRoot 'python.exe'
$probePath = Join-Path $PSScriptRoot 'probes/amd_backend_probe.py'

if (-not (Test-Path $sourceComfyMain)) {
    throw "SwarmUI ComfyUI main.py was not found at '$sourceComfyMain'. Complete the SwarmUI backend installation first."
}
if (-not (Test-Path $theRockPython)) {
    throw "The tested TheRock Python was not found at '$theRockPython'. Run scripts/Test-TheRockGfx1030.ps1 first."
}
if (-not (Test-Path $probePath)) {
    throw "GPU probe was not found at '$probePath'."
}

if ($RefreshCopy -and (Test-Path $isolatedComfyBase)) {
    Write-Host "Refreshing isolated ComfyUI copy at $isolatedComfyBase ..." -ForegroundColor Yellow
    Remove-Item -Path $isolatedComfyBase -Recurse -Force
}

if (-not (Test-Path $comfyMain)) {
    Write-Host ''
    Write-Host 'Creating an isolated copy of the SwarmUI ComfyUI code...' -ForegroundColor Cyan
    Write-Host 'Models, outputs, user data, git metadata, and caches are not copied.' -ForegroundColor DarkGray
    New-Item -ItemType Directory -Path $comfyRoot -Force | Out-Null

    $robocopyArgs = @(
        $sourceComfyRoot,
        $comfyRoot,
        '/MIR', '/NFL', '/NDL', '/NJH', '/NJS', '/NP',
        '/XD', '.git', 'output', 'input', 'temp', 'user', '__pycache__'
    )
    $null = & robocopy.exe @robocopyArgs
    $copyExit = $LASTEXITCODE
    if ($copyExit -gt 7) {
        throw "robocopy failed while cloning the ComfyUI code (exit code $copyExit)."
    }
}

Write-Host ''
Write-Host 'StableAMD TheRock -> ComfyUI integration test' -ForegroundColor Cyan
Write-Host "Source ComfyUI:   $sourceComfyRoot"
Write-Host "Isolated ComfyUI: $comfyRoot"
Write-Host "Python:           $theRockPython"
Write-Host 'The original SwarmUI/ComfyUI backend will not be modified.' -ForegroundColor DarkGray

# The isolated Python was initially cloned from SwarmUI's ROCm 7.2 portable package.
# Remove its legacy custom library bundle so this test uses one coherent TheRock stack.
$legacyPackage = 'rocm-sdk-libraries-custom'
$legacyShow = @(& $theRockPython -s -m pip show $legacyPackage 2>$null)
if ($LASTEXITCODE -eq 0 -and $legacyShow.Count -gt 0) {
    Write-Host "Removing legacy $legacyPackage from the isolated environment..." -ForegroundColor Yellow
    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $theRockPython -s -m pip uninstall -y $legacyPackage 2>&1 | ForEach-Object { Write-Host $_ }
        $uninstallExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    if ($uninstallExit -ne 0) {
        throw "Failed to remove legacy package '$legacyPackage' from the isolated TheRock environment."
    }
}

Write-Host 'Rechecking GPU compute after cleanup...' -ForegroundColor Cyan
$probeStderr = Join-Path $OutputDirectory ("therock-comfy-preflight-{0}.stderr.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$probeRaw = @(& $theRockPython -s $probePath 2> $probeStderr | ForEach-Object { [string]$_ })
$probeExit = $LASTEXITCODE
$probeJson = $probeRaw | Where-Object { $_.Trim().StartsWith('{') -and $_.Trim().EndsWith('}') } | Select-Object -Last 1
$probe = $null
if ($probeJson) {
    try { $probe = $probeJson | ConvertFrom-Json } catch { $probe = $null }
}
if ($probeExit -ne 0 -or $null -eq $probe -or -not $probe.gpu_available -or -not $probe.fp16_matmul_ok) {
    throw "The isolated TheRock GPU probe stopped working after cleanup. See '$probeStderr'."
}
Write-Host "GPU preflight passed: $($probe.device_name), $([math]::Round([double]$probe.vram_bytes / 1GB, 2)) GiB" -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$stdoutPath = Join-Path $OutputDirectory "therock-comfy-$stamp.stdout.log"
$stderrPath = Join-Path $OutputDirectory "therock-comfy-$stamp.stderr.log"
$reportPath = Join-Path $OutputDirectory "therock-comfy-$stamp.json"
$url = "http://127.0.0.1:$Port/"
$statsUrl = "${url}system_stats"

$oldOverride = [Environment]::GetEnvironmentVariable('HSA_OVERRIDE_GFX_VERSION', 'Process')
$hadOverride = $null -ne $oldOverride
Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue

$process = $null
try {
    Write-Host "Starting isolated ComfyUI on $url ..." -ForegroundColor Cyan
    $arguments = "-s `"$comfyMain`" --listen 127.0.0.1 --port $Port"
    $process = Start-Process `
        -FilePath $theRockPython `
        -ArgumentList $arguments `
        -WorkingDirectory $comfyRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $stats = $null
    $reachable = $false
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) {
            break
        }
        try {
            $stats = Invoke-RestMethod -Uri $statsUrl -Method Get -TimeoutSec 5
            if ($null -ne $stats) {
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
        $process.WaitForExit()
        $process.Refresh()
        try { $exitCode = $process.ExitCode } catch { $exitCode = $null }
    }

    $result = [pscustomobject]@{
        CreatedAtUtc = [DateTime]::UtcNow.ToString('o')
        SourceComfyRoot = $sourceComfyRoot
        ComfyRoot = $comfyRoot
        ComfyMain = $comfyMain
        PythonPath = $theRockPython
        Url = $url
        SystemStatsUrl = $statsUrl
        HttpReachable = $reachable
        ProcessId = if ($process) { $process.Id } else { $null }
        ProcessExited = if ($process) { $process.HasExited } else { $true }
        ExitCode = $exitCode
        GpuProbe = $probe
        SystemStats = $stats
        StdoutLog = $stdoutPath
        StderrLog = $stderrPath
        LegacyRocmPackageRemoved = ($legacyShow.Count -gt 0)
    }
    $result | ConvertTo-Json -Depth 12 | Set-Content -Path $reportPath -Encoding UTF8

    if (-not $reachable) {
        Write-Host ''
        Write-Host '===== ComfyUI stdout tail =====' -ForegroundColor DarkCyan
        if (Test-Path $stdoutPath) { Get-Content $stdoutPath -Tail 100 | ForEach-Object { Write-Host $_ } }
        Write-Host ''
        Write-Host '===== ComfyUI stderr tail =====' -ForegroundColor DarkCyan
        if (Test-Path $stderrPath) { Get-Content $stderrPath -Tail 100 | ForEach-Object { Write-Host $_ } }
        throw "ComfyUI did not become reachable at '$statsUrl'. Report: '$reportPath'."
    }

    Write-Host ''
    Write-Host 'THE ROCK COMFYUI BACKEND START PASSED.' -ForegroundColor Green
    Write-Host "ComfyUI: $url"
    Write-Host "System stats: $statsUrl"
    Write-Host "Report: $reportPath"
    if ($stats.devices) {
        foreach ($device in @($stats.devices)) {
            Write-Host "Comfy device: $($device.name) / type=$($device.type) / VRAM=$($device.vram_total)"
        }
    }

    if ($KeepRunning) {
        Write-Host 'KeepRunning was requested; leaving isolated ComfyUI alive for manual testing.' -ForegroundColor Yellow
        $process = $null
    }
    else {
        Write-Host 'Stopping isolated ComfyUI after successful smoke test.' -ForegroundColor DarkGray
    }

    return $result
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        try { $process.WaitForExit() } catch { }
    }
    if ($hadOverride) {
        $env:HSA_OVERRIDE_GFX_VERSION = $oldOverride
    }
    else {
        Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
    }
}
