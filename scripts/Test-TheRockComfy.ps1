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
$sourceComfyPackage = Join-Path $sourceComfyRoot 'comfy/options.py'
$sourceComfyApiInput = Join-Path $sourceComfyRoot 'comfy_api/input/__init__.py'
$isolatedComfyBase = Join-Path $RuntimeRoot 'therock-comfy'
$comfyRoot = Join-Path $isolatedComfyBase 'ComfyUI'
$comfyMain = Join-Path $comfyRoot 'main.py'
$isolatedComfyPackage = Join-Path $comfyRoot 'comfy/options.py'
$isolatedComfyApiInput = Join-Path $comfyRoot 'comfy_api/input/__init__.py'
$theRockRoot = Join-Path $RuntimeRoot 'therock-gfx1030'
$theRockPythonRoot = Join-Path $theRockRoot 'python_embeded'
$theRockPython = Join-Path $theRockPythonRoot 'python.exe'
$probePath = Join-Path $PSScriptRoot 'probes/amd_backend_probe.py'
$comfyRunner = Join-Path $PSScriptRoot 'probes/run_comfy_isolated.py'
$nightlyIndex = 'https://rocm.nightlies.amd.com/whl-multi-arch/'

if (-not (Test-Path $sourceComfyMain)) {
    throw "SwarmUI ComfyUI main.py was not found at '$sourceComfyMain'. Complete the SwarmUI backend installation first."
}
if (-not (Test-Path $sourceComfyPackage)) {
    throw "SwarmUI ComfyUI source is incomplete: '$sourceComfyPackage' is missing. The source backend itself needs repair before testing TheRock."
}
if (-not (Test-Path $sourceComfyApiInput)) {
    throw "SwarmUI ComfyUI source is internally incomplete for this revision: '$sourceComfyApiInput' is missing, but current comfy_api code imports comfy_api.input. Repair or refresh the source ComfyUI checkout before testing TheRock."
}
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    throw 'git.exe is required to make a complete isolated ComfyUI checkout.'
}
if (-not (Test-Path $theRockPython)) {
    throw "The tested TheRock Python was not found at '$theRockPython'. Run scripts/Test-TheRockGfx1030.ps1 first."
}
if (-not (Test-Path $probePath)) {
    throw "GPU probe was not found at '$probePath'."
}
if (-not (Test-Path $comfyRunner)) {
    throw "ComfyUI bootstrap was not found at '$comfyRunner'."
}

$copyIsComplete = (Test-Path $comfyMain) -and (Test-Path $isolatedComfyPackage) -and (Test-Path $isolatedComfyApiInput)
if ($RefreshCopy -or ((Test-Path $isolatedComfyBase) -and -not $copyIsComplete)) {
    if (Test-Path $isolatedComfyBase) {
        if ($RefreshCopy) {
            Write-Host "Refreshing isolated ComfyUI copy at $isolatedComfyBase ..." -ForegroundColor Yellow
        }
        else {
            Write-Host "Removing incomplete isolated ComfyUI copy at $isolatedComfyBase ..." -ForegroundColor Yellow
            Write-Host "Required file missing: $isolatedComfyApiInput" -ForegroundColor DarkGray
        }
        Remove-Item -Path $isolatedComfyBase -Recurse -Force
    }
    $copyIsComplete = $false
}

if (-not $copyIsComplete) {
    Write-Host ''
    Write-Host 'Creating a complete isolated checkout of the SwarmUI ComfyUI code...' -ForegroundColor Cyan
    Write-Host 'A local git clone copies tracked source files only; models, outputs, user data, and caches are not copied.' -ForegroundColor DarkGray
    New-Item -ItemType Directory -Path $isolatedComfyBase -Force | Out-Null

    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $sourceCommitLines = @(& git.exe -C $sourceComfyRoot rev-parse HEAD 2>&1 | ForEach-Object { [string]$_ })
        $revParseExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    if ($revParseExit -ne 0 -or $sourceCommitLines.Count -eq 0) {
        throw "The SwarmUI ComfyUI source at '$sourceComfyRoot' is not a readable git checkout. git rev-parse output: $($sourceCommitLines -join ' ')"
    }
    $sourceCommit = $sourceCommitLines[-1].Trim()

    $cloneOutput = @()
    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $cloneOutput = @(& git.exe clone --no-hardlinks --local --no-tags $sourceComfyRoot $comfyRoot 2>&1 | ForEach-Object { [string]$_ })
        $cloneExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    if ($cloneExit -ne 0) {
        throw "Local ComfyUI git clone failed with exit code $cloneExit. Output: $($cloneOutput -join ' ')"
    }

    $checkoutOutput = @()
    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $checkoutOutput = @(& git.exe -C $comfyRoot checkout --detach $sourceCommit 2>&1 | ForEach-Object { [string]$_ })
        $checkoutExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    if ($checkoutExit -ne 0) {
        throw "Could not pin the isolated ComfyUI copy to source commit $sourceCommit. Output: $($checkoutOutput -join ' ')"
    }

    if (-not (Test-Path $comfyMain) -or -not (Test-Path $isolatedComfyPackage) -or -not (Test-Path $isolatedComfyApiInput)) {
        throw "The isolated ComfyUI checkout is incomplete after git clone. Expected '$comfyMain', '$isolatedComfyPackage', and '$isolatedComfyApiInput'. Source commit: $sourceCommit"
    }

    # The copy is now self-contained source code. Git metadata is not needed for this smoke test.
    $isolatedGit = Join-Path $comfyRoot '.git'
    if (Test-Path $isolatedGit) {
        Remove-Item -Path $isolatedGit -Recurse -Force
    }
}

Write-Host ''
Write-Host 'StableAMD TheRock -> ComfyUI integration test' -ForegroundColor Cyan
Write-Host "Source ComfyUI:   $sourceComfyRoot"
Write-Host "Isolated ComfyUI: $comfyRoot"
Write-Host "Python:           $theRockPython"
Write-Host 'The original SwarmUI/ComfyUI backend will not be modified.' -ForegroundColor DarkGray

# The isolated Python may have been cloned before StableAMD learned to remove
# AMD portable's legacy ROCm 7.2 custom library bundle. Query the installed
# package list in one successful pip command instead of using `pip show` on an
# absent package: Windows PowerShell 5.1 can turn that harmless stderr warning
# into a terminating NativeCommandError when ErrorActionPreference is Stop.
$legacyPackage = 'rocm-sdk-libraries-custom'
$pipListRaw = @()
$oldEap = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $pipListRaw = @(& $theRockPython -s -m pip list --format=json 2>$null | ForEach-Object { [string]$_ })
    $pipListExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldEap
}
if ($pipListExit -ne 0) {
    throw 'Could not query packages installed in the isolated TheRock environment.'
}

try {
    $pipPackages = @(($pipListRaw -join "`n") | ConvertFrom-Json)
}
catch {
    throw "Could not parse pip package list from the isolated TheRock environment: $($_.Exception.Message)"
}

$legacyPackageInfo = $pipPackages | Where-Object { $_.name -ieq $legacyPackage } | Select-Object -First 1
$legacyWasPresent = $null -ne $legacyPackageInfo
if ($legacyWasPresent) {
    $rocmLibrariesInfo = $pipPackages | Where-Object { $_.name -ieq 'rocm-sdk-libraries' } | Select-Object -First 1
    if ($null -eq $rocmLibrariesInfo -or [string]::IsNullOrWhiteSpace([string]$rocmLibrariesInfo.version)) {
        throw 'rocm-sdk-libraries is missing from the isolated TheRock environment. Re-run Test-TheRockGfx1030.ps1 -Reset.'
    }
    $rocmLibrariesVersion = [string]$rocmLibrariesInfo.version

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

    Write-Host "Restoring rocm-sdk-libraries $rocmLibrariesVersion from TheRock nightlies..." -ForegroundColor Yellow
    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $theRockPython -s -m pip install --force-reinstall --no-deps --no-cache-dir --index-url $nightlyIndex "rocm-sdk-libraries==$rocmLibrariesVersion" 2>&1 | ForEach-Object { Write-Host $_ }
        $repairExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    if ($repairExit -ne 0) {
        throw "Failed to restore rocm-sdk-libraries $rocmLibrariesVersion after legacy cleanup."
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
    $arguments = "-s `"$comfyRunner`" `"$comfyRoot`" --listen 127.0.0.1 --port $Port"
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
        SourceCommit = if ($sourceCommit) { $sourceCommit } else { $null }
        ComfyRoot = $comfyRoot
        ComfyMain = $comfyMain
        ComfyRunner = $comfyRunner
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
        LegacyRocmPackageRemoved = $legacyWasPresent
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
