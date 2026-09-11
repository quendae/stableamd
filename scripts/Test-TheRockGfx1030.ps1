[CmdletBinding()]
param(
    [string]$RuntimeRoot = '',
    [string]$OutputDirectory = '',
    [string]$IndexUrl = '',
    [switch]$Reset
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'The TheRock gfx1030 probe is Windows-only.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Hardware.psm1') -Force

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $repoRoot '.runtime'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot 'diagnostics'
}

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$gfxTarget = 'gfx1030'
$installSpec = Get-StableAmdTheRockInstallArgs -GfxTarget $gfxTarget
if ([string]::IsNullOrWhiteSpace($IndexUrl)) {
    $IndexUrl = $installSpec.IndexUrl
}

$swarmPythonRoot = Join-Path $RuntimeRoot 'SwarmUI/dlbackend/comfy/python_embeded'
$sourcePython = Join-Path $swarmPythonRoot 'python.exe'
if (-not (Test-Path $sourcePython)) {
    throw "SwarmUI embedded Python was not found at '$sourcePython'. Complete the SwarmUI AMD backend installation first."
}

$testRoot = Join-Path $RuntimeRoot 'therock-gfx1030'
$testPythonRoot = Join-Path $testRoot 'python_embeded'
$testPython = Join-Path $testPythonRoot 'python.exe'

if ($Reset -and (Test-Path $testRoot)) {
    Write-Host "Resetting isolated TheRock test environment at $testRoot ..." -ForegroundColor Yellow
    Remove-Item -Path $testRoot -Recurse -Force
}

if (-not (Test-Path $testPython)) {
    Write-Host ''
    Write-Host 'Creating an isolated copy of SwarmUI embedded Python...' -ForegroundColor Cyan
    Write-Host 'The original SwarmUI/ComfyUI environment will not be modified.' -ForegroundColor DarkGray
    New-Item -ItemType Directory -Path $testPythonRoot -Force | Out-Null

    $null = & robocopy.exe $swarmPythonRoot $testPythonRoot /MIR /NFL /NDL /NJH /NJS /NP
    $copyExit = $LASTEXITCODE
    if ($copyExit -gt 7) {
        throw "robocopy failed while cloning the embedded Python environment (exit code $copyExit)."
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$pipLog = Join-Path $OutputDirectory "therock-gfx1030-pip-$stamp.log"
$probeStderr = Join-Path $OutputDirectory "therock-gfx1030-probe-$stamp.stderr.log"
$reportPath = Join-Path $OutputDirectory "therock-gfx1030-$stamp.json"
$probePath = Join-Path $PSScriptRoot 'probes/amd_backend_probe.py'

if (-not (Test-Path $probePath)) {
    throw "GPU probe was not found at '$probePath'."
}

Write-Host ''
Write-Host 'StableAMD isolated TheRock gfx1030 test' -ForegroundColor Cyan
Write-Host "Python: $testPython"
Write-Host "Index:  $IndexUrl"
Write-Host 'Packages:'
$installSpec.Packages | ForEach-Object { Write-Host "  $_" }
Write-Host ''
Write-Host 'Installing current TheRock multi-arch nightly packages into the isolated copy.' -ForegroundColor Yellow
Write-Host 'This can download roughly 1-2 GB and may take several minutes.' -ForegroundColor Yellow

$pipArgs = @(
    '-s', '-m', 'pip', 'install',
    '--upgrade', '--force-reinstall', '--no-cache-dir',
    '--index-url', $IndexUrl
) + @($installSpec.Packages)

$oldEap = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $testPython @pipArgs 2>&1 | Tee-Object -FilePath $pipLog
    $pipExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldEap
}

if ($pipExitCode -ne 0) {
    throw "TheRock nightly pip installation failed with exit code $pipExitCode. See '$pipLog'."
}

Write-Host ''
Write-Host 'Collecting installed package versions...' -ForegroundColor Cyan
$freeze = @(& $testPython -s -m pip freeze 2>$null | ForEach-Object { [string]$_ })
$relevantPackages = @($freeze | Where-Object { $_ -match '^(?i)(torch|torchvision|torchaudio|rocm|amd-|triton)' })
$relevantPackages | ForEach-Object { Write-Host "  $_" }

$offloadArch = Get-ChildItem -Path $testPythonRoot -Filter 'offload-arch.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
$hipInfo = Get-ChildItem -Path $testPythonRoot -Filter 'hipInfo.exe' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1

$offloadOutput = @()
if ($null -ne $offloadArch) {
    Write-Host ''
    Write-Host "offload-arch: $($offloadArch.FullName)" -ForegroundColor Cyan
    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $offloadOutput = @(& $offloadArch.FullName 2>&1 | ForEach-Object { [string]$_ })
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    $offloadOutput | ForEach-Object { Write-Host "  $_" }
}

$hipInfoOutput = @()
if ($null -ne $hipInfo) {
    Write-Host ''
    Write-Host "hipInfo: $($hipInfo.FullName)" -ForegroundColor Cyan
    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $hipInfoOutput = @(& $hipInfo.FullName 2>&1 | Select-Object -First 120 | ForEach-Object { [string]$_ })
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    $hipInfoOutput | ForEach-Object { Write-Host "  $_" }
}

Write-Host ''
Write-Host 'Running the same FP16 PyTorch GPU probe against the TheRock nightly...' -ForegroundColor Cyan
$rawOutput = @(& $testPython -s $probePath 2> $probeStderr | ForEach-Object { [string]$_ })
$pythonExitCode = $LASTEXITCODE
$jsonLine = $rawOutput | Where-Object { $_.Trim().StartsWith('{') -and $_.Trim().EndsWith('}') } | Select-Object -Last 1
$parsedProbe = $null
$parseError = $null

if ($null -ne $jsonLine) {
    try {
        $parsedProbe = $jsonLine | ConvertFrom-Json
    }
    catch {
        $parseError = $_.Exception.Message
    }
}
else {
    $parseError = 'The Python probe did not emit a JSON result line.'
}

$report = [pscustomobject]@{
    CreatedAtUtc = [DateTime]::UtcNow.ToString('o')
    GfxTarget = $gfxTarget
    IndexUrl = $IndexUrl
    PackagesRequested = @($installSpec.Packages)
    TestRoot = $testRoot
    PythonPath = $testPython
    PipExitCode = $pipExitCode
    InstalledPackages = @($relevantPackages)
    OffloadArchPath = if ($offloadArch) { $offloadArch.FullName } else { $null }
    OffloadArchOutput = @($offloadOutput)
    HipInfoPath = if ($hipInfo) { $hipInfo.FullName } else { $null }
    HipInfoOutput = @($hipInfoOutput)
    PythonExitCode = $pythonExitCode
    Parsed = $parsedProbe
    ParseError = $parseError
    RawOutput = @($rawOutput)
    ProbeStderr = if (Test-Path $probeStderr) { @(Get-Content $probeStderr -ErrorAction SilentlyContinue) } else { @() }
}

$report | ConvertTo-Json -Depth 10 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ''
Write-Host 'TheRock gfx1030 result' -ForegroundColor Cyan
Write-Host "Report: $reportPath"
if ($null -ne $parsedProbe) {
    Write-Host "PyTorch: $($parsedProbe.torch_version)"
    Write-Host "HIP: $($parsedProbe.hip_version)"
    Write-Host "GPU available: $($parsedProbe.gpu_available)"
    Write-Host "Device: $($parsedProbe.device_name)"
    if ($parsedProbe.vram_bytes) {
        Write-Host ("VRAM: {0:N2} GiB" -f ([double]$parsedProbe.vram_bytes / 1GB))
    }
    Write-Host "FP16 matmul: $($parsedProbe.fp16_matmul_ok) ($($parsedProbe.fp16_matmul_ms) ms)"
    if ($parsedProbe.error) {
        Write-Warning "$($parsedProbe.error_type): $($parsedProbe.error)"
    }
}

if ($pythonExitCode -ne 0 -or $null -eq $parsedProbe -or -not $parsedProbe.gpu_available -or -not $parsedProbe.fp16_matmul_ok) {
    throw "TheRock nightly gfx1030 probe failed. Share '$reportPath'. Do not modify the SwarmUI environment yet."
}

Write-Host ''
Write-Host 'THE ROCK GFX1030 GPU COMPUTE PASSED.' -ForegroundColor Green
Write-Host 'The next step is to transplant these tested packages into a copied SwarmUI backend before touching the real installation.' -ForegroundColor Cyan

return $report
