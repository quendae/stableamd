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

if (-not (Test-Path $pythonPath)) {
    throw "SwarmUI's embedded ComfyUI Python was not found at '$pythonPath'. Start SwarmUI, finish its installer, and choose the AMD-compatible ComfyUI backend first."
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$pythonProbe = @'
import json
import platform
import sys
import time

result = {
    "python_version": platform.python_version(),
    "torch_version": None,
    "hip_version": None,
    "gpu_available": False,
    "device_name": None,
    "device_index": None,
    "vram_bytes": None,
    "fp16_matmul_ok": False,
    "fp16_matmul_ms": None,
    "error_type": None,
    "error": None,
}

try:
    import torch

    result["torch_version"] = torch.__version__
    result["hip_version"] = getattr(torch.version, "hip", None)
    result["gpu_available"] = bool(torch.cuda.is_available())

    if not result["gpu_available"]:
        raise RuntimeError("torch.cuda.is_available() returned False; ROCm PyTorch did not expose a usable GPU")

    device_index = torch.cuda.current_device()
    props = torch.cuda.get_device_properties(device_index)
    result["device_index"] = int(device_index)
    result["device_name"] = torch.cuda.get_device_name(device_index)
    result["vram_bytes"] = int(props.total_memory)

    a = torch.randn((2048, 2048), device="cuda", dtype=torch.float16)
    b = torch.randn((2048, 2048), device="cuda", dtype=torch.float16)
    torch.cuda.synchronize()
    started = time.perf_counter()
    c = a @ b
    torch.cuda.synchronize()
    result["fp16_matmul_ms"] = round((time.perf_counter() - started) * 1000.0, 3)
    result["fp16_matmul_ok"] = bool(torch.isfinite(c).all().item())

    if not result["fp16_matmul_ok"]:
        raise RuntimeError("FP16 matrix multiplication completed but produced non-finite values")
except Exception as exc:
    result["error_type"] = type(exc).__name__
    result["error"] = str(exc)
    print(json.dumps(result, separators=(",", ":")))
    sys.exit(1)

print(json.dumps(result, separators=(",", ":")))
'@

$environmentForChild = Get-StableAmdSpikeEnvironment -Mode $Mode
$oldOverride = [Environment]::GetEnvironmentVariable('HSA_OVERRIDE_GFX_VERSION', 'Process')
$hadOverride = $null -ne $oldOverride

try {
    if ($Mode -eq 'GfxOverride') {
        $env:HSA_OVERRIDE_GFX_VERSION = $environmentForChild['HSA_OVERRIDE_GFX_VERSION']
        Write-Warning 'Backend probe is running with HSA_OVERRIDE_GFX_VERSION=10.3.0.'
    }
    else {
        Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
        Write-Host 'Backend probe is running in baseline mode with no HSA override.' -ForegroundColor Yellow
    }

    $rawOutput = @(& $pythonPath -s -c $pythonProbe 2>&1)
    $pythonExitCode = $LASTEXITCODE
}
finally {
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
    $parseError = 'The embedded Python probe did not emit a JSON result line.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$report = [pscustomobject]@{
    CreatedAtUtc = [DateTime]::UtcNow.ToString('o')
    Mode = $Mode
    HsaOverrideApplied = ($Mode -eq 'GfxOverride')
    PythonPath = $pythonPath
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

if ($pythonExitCode -ne 0 -or $null -eq $parsedProbe -or -not $parsedProbe.gpu_available -or -not $parsedProbe.fp16_matmul_ok) {
    throw "AMD backend smoke test failed in $Mode mode. Share '$reportPath' and the SwarmUI launch logs for diagnosis."
}

Write-Host 'GPU compute smoke test PASSED.' -ForegroundColor Green
Write-Host 'Next gate: install an SDXL model in SwarmUI and generate one 1024x1024 image.' -ForegroundColor Cyan

return $report
