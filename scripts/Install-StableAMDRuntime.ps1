[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [switch]$PlanOnly,
    [switch]$ForceRepair,
    [switch]$SkipGpuCheck
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

$lockPath = Join-Path $RepoRoot 'config/runtime-lock.v0.1.json'
if (-not (Test-Path $lockPath -PathType Leaf)) {
    throw "StableAMD runtime lock is missing: '$lockPath'."
}
$lock = Get-Content -Path $lockPath -Raw | ConvertFrom-Json

$pythonVersion = [string]$lock.runtime.python
$gfxTarget = [string]$lock.gpu.gfxTarget
$theRockIndexUrl = [string]$lock.runtime.indexUrl
$torchVersion = [string]$lock.runtime.torch
$torchVisionVersion = [string]$lock.runtime.torchvision
$torchAudioVersion = [string]$lock.runtime.torchaudio
$comfyVersion = [string]$lock.runtime.comfyui
$comfyCommit = [string]$lock.runtime.comfyCommit

foreach ($value in @($pythonVersion, $gfxTarget, $theRockIndexUrl, $torchVersion, $torchVisionVersion, $torchAudioVersion, $comfyVersion, $comfyCommit)) {
    if ([string]::IsNullOrWhiteSpace([string]$value)) {
        throw 'StableAMD runtime lock is incomplete. A pinned runtime component is missing.'
    }
}
if ($comfyCommit -notmatch '^[0-9a-fA-F]{40}$') {
    throw "Invalid locked ComfyUI commit '$comfyCommit'."
}

$pythonInstallerUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
$torchPackage = "torch[device-$gfxTarget]==$torchVersion"
$torchVisionPackage = "torchvision[device-$gfxTarget]==$torchVisionVersion"
$torchAudioPackage = "torchaudio==$torchAudioVersion"
$comfyArchiveUrl = "https://github.com/Comfy-Org/ComfyUI/archive/$comfyCommit.zip"

$plan = [pscustomobject]@{
    SchemaVersion = 1
    PythonVersion = $pythonVersion
    GfxTarget = $gfxTarget
    PythonInstallerUrl = $pythonInstallerUrl
    TheRockIndexUrl = $theRockIndexUrl
    TorchPackage = $torchPackage
    TorchVisionPackage = $torchVisionPackage
    TorchAudioPackage = $torchAudioPackage
    ComfyVersion = $comfyVersion
    ComfyCommit = $comfyCommit
    ComfyArchiveUrl = $comfyArchiveUrl
}

if ($PlanOnly) {
    return $plan
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'StableAMD v0.1 runtime bootstrap is Windows-only.'
}

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Hardware.psm1') -Force
$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths

$cacheRoot = Join-Path $paths.StableAmdRoot 'cache'
New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
$manifestPath = Join-Path $paths.StableAmdRoot 'runtime-install.json'
$probePath = Join-Path $PSScriptRoot 'probes/amd_backend_probe.py'
if (-not (Test-Path $probePath -PathType Leaf)) {
    throw "StableAMD GPU probe is missing: '$probePath'."
}

function Invoke-StableAmdCheckedNative {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )

    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host $_ }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }
    if ($exitCode -ne 0) {
        throw "$FailureMessage (exit code $exitCode)."
    }
}

function Invoke-StableAmdGpuProbe {
    param([Parameter(Mandatory = $true)][string]$PythonPath)

    $probeStderr = Join-Path $paths.LogsRoot ("runtime-probe-{0}.stderr.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    $oldOverride = [Environment]::GetEnvironmentVariable('HSA_OVERRIDE_GFX_VERSION', 'Process')
    $hadOverride = $null -ne $oldOverride
    Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
    try {
        $raw = @(& $PythonPath -s $probePath 2> $probeStderr | ForEach-Object { [string]$_ })
        $exitCode = $LASTEXITCODE
    }
    finally {
        if ($hadOverride) { $env:HSA_OVERRIDE_GFX_VERSION = $oldOverride }
        else { Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue }
    }

    $jsonLine = $raw | Where-Object { $_.Trim().StartsWith('{') -and $_.Trim().EndsWith('}') } | Select-Object -Last 1
    $parsed = $null
    if ($jsonLine) {
        try { $parsed = $jsonLine | ConvertFrom-Json } catch { $parsed = $null }
    }
    return [pscustomobject]@{
        ExitCode = $exitCode
        Parsed = $parsed
        StderrLog = $probeStderr
        Passed = ($exitCode -eq 0 -and $null -ne $parsed -and [bool]$parsed.gpu_available -and [bool]$parsed.fp16_matmul_ok)
    }
}

function Test-StableAmdLockedComfySource {
    if (-not (Test-Path (Join-Path $paths.ComfyRoot 'main.py') -PathType Leaf)) { return $false }
    if (-not (Test-Path (Join-Path $paths.ComfyRoot 'comfy_api/input/__init__.py') -PathType Leaf)) { return $false }
    $pyproject = Join-Path $paths.ComfyRoot 'pyproject.toml'
    if (-not (Test-Path $pyproject -PathType Leaf)) { return $false }
    $versionLine = Get-Content -Path $pyproject -ErrorAction SilentlyContinue | Where-Object { $_ -match '^version\s*=\s*"' } | Select-Object -First 1
    return ($null -ne $versionLine -and [string]$versionLine -match [regex]::Escape("`"$comfyVersion`""))
}

$runtimeLooksComplete = (Test-Path $paths.TheRockPython -PathType Leaf) -and (Test-StableAmdLockedComfySource)
if ($runtimeLooksComplete -and -not $ForceRepair) {
    Write-Host 'Checking existing StableAMD runtime before downloading anything...' -ForegroundColor Cyan
    $existingProbe = Invoke-StableAmdGpuProbe -PythonPath $paths.TheRockPython
    if ($existingProbe.Passed -and [string]$existingProbe.Parsed.torch_version -eq $torchVersion) {
        Write-Host "Existing locked runtime is healthy: $($existingProbe.Parsed.device_name)" -ForegroundColor Green
        return [pscustomobject]@{
            Status = 'reused'
            Reused = $true
            Repaired = $false
            PythonPath = $paths.TheRockPython
            ComfyRoot = $paths.ComfyRoot
            ManifestPath = $manifestPath
            Probe = $existingProbe.Parsed
            Plan = $plan
        }
    }
    Write-Warning 'Existing runtime is incomplete, unhealthy, or does not match the v0.1 torch lock. StableAMD will repair managed runtime components.'
}

if (-not $SkipGpuCheck) {
    $controllers = @(Get-CimInstance Win32_VideoController -ErrorAction Stop)
    $supported = $controllers | Where-Object { (Resolve-StableAmdGfxTarget -Name ([string]$_.Name)) -eq $gfxTarget } | Select-Object -First 1
    if ($null -eq $supported) {
        $detected = if ($controllers.Count -gt 0) { (@($controllers | ForEach-Object { [string]$_.Name }) -join ', ') } else { '<none>' }
        throw "StableAMD v0.1 runtime is locked to $gfxTarget. No supported Radeon was detected. Detected adapters: $detected"
    }
    Write-Host "Detected supported GPU: $($supported.Name) -> $gfxTarget" -ForegroundColor Green
}

if ($ForceRepair) {
    $stopScript = Join-Path $PSScriptRoot 'Stop-StableAMD.ps1'
    if (Test-Path $stopScript -PathType Leaf) {
        try { & $stopScript -RepoRoot $RepoRoot | Out-Null } catch { }
    }
}

$pythonRoot = Split-Path -Parent $paths.TheRockPython
if ($ForceRepair -and (Test-Path $pythonRoot)) {
    Write-Host "Resetting managed Python runtime at $pythonRoot ..." -ForegroundColor Yellow
    Remove-Item -Path $pythonRoot -Recurse -Force
}

if (-not (Test-Path $paths.TheRockPython -PathType Leaf)) {
    if (Test-Path $pythonRoot) {
        Remove-Item -Path $pythonRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null

    $pythonInstaller = Join-Path $cacheRoot "python-$pythonVersion-amd64.exe"
    if (-not (Test-Path $pythonInstaller -PathType Leaf)) {
        Write-Host "Downloading Python $pythonVersion..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $pythonInstallerUrl -OutFile $pythonInstaller -UseBasicParsing
    }

    $signature = Get-AuthenticodeSignature -FilePath $pythonInstaller
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.SignerCertificate -or [string]$signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw "Downloaded Python installer did not have a valid Python Software Foundation signature. Status: $($signature.Status)"
    }

    Write-Host "Installing private Python $pythonVersion runtime..." -ForegroundColor Cyan
    $installerArgs = "/quiet InstallAllUsers=0 TargetDir=`"$pythonRoot`" Include_pip=1 Include_launcher=0 PrependPath=0 Shortcuts=0 AssociateFiles=0 Include_doc=0 Include_test=0 Include_tcltk=0 CompileAll=0 SimpleInstall=1"
    $pythonInstall = Start-Process -FilePath $pythonInstaller -ArgumentList $installerArgs -Wait -PassThru
    if ($pythonInstall.ExitCode -ne 0 -or -not (Test-Path $paths.TheRockPython -PathType Leaf)) {
        throw "Python $pythonVersion private runtime installation failed with exit code $($pythonInstall.ExitCode)."
    }
}

Write-Host ''
Write-Host 'Installing pinned TheRock PyTorch stack...' -ForegroundColor Cyan
$pipInstallArgs = @(
    '-m', 'pip', 'install', '--pre', '--no-cache-dir',
    '--index-url', $theRockIndexUrl,
    $torchPackage, $torchVisionPackage, $torchAudioPackage
)
Invoke-StableAmdCheckedNative -FilePath $paths.TheRockPython -Arguments $pipInstallArgs -FailureMessage 'Pinned TheRock PyTorch installation failed'

$comfyParent = Split-Path -Parent $paths.ComfyRoot
if ($ForceRepair -and (Test-Path $paths.ComfyRoot)) {
    Write-Host "Resetting managed ComfyUI source at $($paths.ComfyRoot) ..." -ForegroundColor Yellow
    Remove-Item -Path $paths.ComfyRoot -Recurse -Force
}

if (-not (Test-StableAmdLockedComfySource)) {
    if (Test-Path $paths.ComfyRoot) {
        Remove-Item -Path $paths.ComfyRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Path $comfyParent -Force | Out-Null

    $comfyArchive = Join-Path $cacheRoot "ComfyUI-$comfyCommit.zip"
    if (-not (Test-Path $comfyArchive -PathType Leaf)) {
        Write-Host "Downloading ComfyUI $comfyVersion at locked commit $comfyCommit..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $comfyArchiveUrl -OutFile $comfyArchive -UseBasicParsing
    }

    $extractRoot = Join-Path $cacheRoot "ComfyUI-$comfyCommit-extracted"
    if (Test-Path $extractRoot) { Remove-Item -Path $extractRoot -Recurse -Force }
    New-Item -ItemType Directory -Path $extractRoot -Force | Out-Null
    Expand-Archive -Path $comfyArchive -DestinationPath $extractRoot -Force

    $sourceRoot = Get-ChildItem -Path $extractRoot -Directory | Select-Object -First 1
    if ($null -eq $sourceRoot -or -not (Test-Path (Join-Path $sourceRoot.FullName 'main.py') -PathType Leaf)) {
        throw 'Locked ComfyUI archive did not contain the expected source tree.'
    }
    Move-Item -Path $sourceRoot.FullName -Destination $paths.ComfyRoot
    Remove-Item -Path $extractRoot -Recurse -Force
}

if (-not (Test-StableAmdLockedComfySource)) {
    throw "ComfyUI source at '$($paths.ComfyRoot)' does not match locked v$comfyVersion."
}

$requirementsPath = Join-Path $paths.ComfyRoot 'requirements.txt'
if (-not (Test-Path $requirementsPath -PathType Leaf)) {
    throw "ComfyUI requirements file is missing: '$requirementsPath'."
}

# The PyTorch family is installed first from the pinned TheRock index. Remove those
# three generic lines from ComfyUI requirements so PyPI can never replace the AMD
# wheels with a different CPU/CUDA/nightly build during dependency installation.
$stableRequirements = Join-Path $cacheRoot "comfyui-$comfyVersion-stableamd-requirements.txt"
Get-Content -Path $requirementsPath | Where-Object {
    $line = ([string]$_).Trim()
    $line -notmatch '^(?i)(torch|torchvision|torchaudio)(\s|$)'
} | Set-Content -Path $stableRequirements -Encoding UTF8

Write-Host 'Installing ComfyUI dependencies without replacing the pinned PyTorch family...' -ForegroundColor Cyan
$comfyPipArgs = @('-m', 'pip', 'install', '--no-cache-dir', '-r', $stableRequirements)
Invoke-StableAmdCheckedNative -FilePath $paths.TheRockPython -Arguments $comfyPipArgs -FailureMessage 'ComfyUI dependency installation failed'

$importProbe = Join-Path $cacheRoot 'verify_stableamd_runtime_imports.py'
@'
import json
import torch
import torchvision
import torchaudio
print(json.dumps({
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
    "torchaudio": torchaudio.__version__,
    "hip": torch.version.hip,
}))
'@ | Set-Content -Path $importProbe -Encoding UTF8

Write-Host 'Verifying pinned PyTorch package imports...' -ForegroundColor Cyan
$importRaw = @(& $paths.TheRockPython -s $importProbe 2>&1 | ForEach-Object { [string]$_ })
$importExit = $LASTEXITCODE
if ($importExit -ne 0) {
    throw "Pinned torch/torchvision/torchaudio import verification failed: $($importRaw -join ' ')"
}
$importRaw | ForEach-Object { Write-Host $_ }

Write-Host 'Running real FP16 Radeon compute probe...' -ForegroundColor Cyan
$probe = Invoke-StableAmdGpuProbe -PythonPath $paths.TheRockPython
if (-not $probe.Passed) {
    $probeError = if ($probe.Parsed -and $probe.Parsed.error) { [string]$probe.Parsed.error } else { 'GPU probe did not pass.' }
    throw "StableAMD runtime installed, but Radeon compute validation failed. $probeError See '$($probe.StderrLog)'."
}
if ([string]$probe.Parsed.torch_version -ne $torchVersion) {
    throw "Installed torch version '$($probe.Parsed.torch_version)' does not match locked version '$torchVersion'."
}

$manifest = [pscustomobject]@{
    schemaVersion = 1
    installedAtUtc = [DateTime]::UtcNow.ToString('o')
    release = [string]$lock.release
    pythonPath = $paths.TheRockPython
    comfyRoot = $paths.ComfyRoot
    pythonVersion = $pythonVersion
    gfxTarget = $gfxTarget
    torch = $torchVersion
    torchvision = $torchVisionVersion
    torchaudio = $torchAudioVersion
    comfyui = $comfyVersion
    comfyCommit = $comfyCommit
    gpu = $probe.Parsed
}
$manifest | ConvertTo-Json -Depth 12 | Set-Content -Path $manifestPath -Encoding UTF8

Write-Host ''
Write-Host 'StableAMD runtime bootstrap passed.' -ForegroundColor Green
Write-Host "Python:  $($paths.TheRockPython)"
Write-Host "ComfyUI: $($paths.ComfyRoot)"
Write-Host "GPU:     $($probe.Parsed.device_name)"
Write-Host "Manifest: $manifestPath"

return [pscustomobject]@{
    Status = 'installed'
    Reused = $false
    Repaired = [bool]$ForceRepair
    PythonPath = $paths.TheRockPython
    ComfyRoot = $paths.ComfyRoot
    ManifestPath = $manifestPath
    Probe = $probe.Parsed
    Plan = $plan
}
