[CmdletBinding()]
param(
    [ValidateSet('Baseline', 'GfxOverride')]
    [string]$Mode = 'Baseline',

    [string]$RuntimeRoot = '',

    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'The SwarmUI backend smoke test must be run on Windows.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Hardware.psm1') -Force

if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $repoRoot '.runtime'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot 'diagnostics'
}

$swarmPath = Join-Path $RuntimeRoot 'SwarmUI'
$pythonPath = Join-Path $swarmPath 'dlbackend/comfy/python_embeded/python.exe'
$probePath = Join-Path $PSScriptRoot 'probes/amd_backend_probe.py'

if (-not (Test-Path $pythonPath)) {
    throw "SwarmUI's embedded ComfyUI Python was not found at '$pythonPath'. Start SwarmUI, finish its installer, and choose the AMD-compatible ComfyUI backend first."
}
if (-not (Test-Path $probePath)) {
    throw "StableAMD backend probe was not found at '$probePath'. Run 'git pull' on the spike branch and retry."
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$environmentForChild = Get-StableAmdSpikeEnvironment -Mode $Mode
$oldOverride = [Environment]::GetEnvironmentVariable('HSA_OVERRIDE_GFX_VERSION', 'Process')
$hadOverride = $null -ne $oldOverride
$oldErrorActionPreference = $ErrorActionPreference
$rawOutput = @()
$pythonExitCode = $null

try {
    if ($Mode -eq 'GfxOverride') {
        $env:HSA_OVERRIDE_GFX_VERSION = $environmentForChild['HSA_OVERRIDE_GFX_VERSION']
        Write-Warning 'Backend probe is running with HSA_OVERRIDE_GFX_VERSION=10.3.0.'
    }
    else {
        Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
        Write-Host 'Backend probe is running in baseline mode with no HSA override.' -ForegroundColor Yellow
    }

    # Windows PowerShell 5.1 can mangle nested quotes in a multiline `python -c` argument.
    # Run a real .py file instead, and temporarily avoid promoting native stderr to a
    # terminating PowerShell NativeCommandError so diagnostics can still be collected.
    $ErrorActionPreference = 'Continue'
    $rawOutput = @(& $pythonPath -s $probePath 2>&1)
    $pythonExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldErrorActionPreference
    if ($hadOverride) {
        $env:HSA_OVERRIDE_GFX_VERSION = $oldOverride
    }
    else {
        Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
    }
}

$jsonLine = $rawOutput | ForEach-Object { [string]$_ } | Where-Object { $_.Trim().StartsWith('{') -and $_.Trim().EndsWith('}') } | Select-Object -Last 1
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
    $parseError = 'The standalone Python probe did not emit a JSON result line.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = [pscustomobject]@{
    CreatedAtUtc = [DateTime]::UtcNow.ToString('o')
    Mode = $Mode
    HsaOverrideApplied = ($Mode -eq 'GfxOverride')
    PythonPath = $pythonPath
    ProbePath = $probePath
    PythonExitCode = $pythonExitCode
    Parsed = $parsedProbe
    ParseError = $parseError
    RawOutput = @($rawOutput | ForEach-Object { [string]$_ })
}

$reportPath = Join-Path $OutputDirectory "backend-$($Mode.ToLowerInvariant())-$stamp.json"
$report | ConvertTo-Json -Depth 8 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ''
Write-Host 'StableAMD SwarmUI backend smoke test' -ForegroundColor Cyan
Write-Host "Mode: $Mode"
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
else {
    Write-Warning "Probe result could not be parsed: $parseError"
    if ($rawOutput.Count -gt 0) {
        Write-Host 'Raw probe output:' -ForegroundColor DarkCyan
        $rawOutput | ForEach-Object { Write-Host ([string]$_) }
    }
}

if ($pythonExitCode -ne 0 -or $null -eq $parsedProbe -or -not $parsedProbe.gpu_available -or -not $parsedProbe.fp16_matmul_ok) {
    throw "AMD backend smoke test failed in $Mode mode. Share '$reportPath' for diagnosis."
}

Write-Host 'GPU compute smoke test PASSED.' -ForegroundColor Green
Write-Host 'Next gate: generate one SDXL 1024x1024 image in SwarmUI and record time/VRAM.' -ForegroundColor Cyan

return $report
