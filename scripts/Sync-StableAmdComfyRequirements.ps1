[CmdletBinding()]
param(
    [string]$RepoRoot = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

$runtimeModule = Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1'
if (-not (Test-Path $runtimeModule -PathType Leaf)) {
    throw "StableAMD runtime module is missing: '$runtimeModule'."
}
Import-Module $runtimeModule -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$requirementsPath = Join-Path $paths.ComfyRoot 'requirements.txt'
$markerPath = Join-Path $paths.StableAmdRoot 'comfy-requirements.sha256'
$filteredRequirementsPath = Join-Path $paths.StableAmdRoot 'comfy-requirements.stableamd.txt'

foreach ($required in @($paths.TheRockPython, $requirementsPath)) {
    if (-not (Test-Path $required -PathType Leaf)) {
        throw "StableAMD cannot synchronize ComfyUI requirements because '$required' is missing."
    }
}

$requirementsHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $requirementsPath).Hash.ToLowerInvariant()
$recordedHash = ''
if (Test-Path $markerPath -PathType Leaf) {
    $recordedHash = ([string](Get-Content -LiteralPath $markerPath -Raw)).Trim().ToLowerInvariant()
}

if ($recordedHash -eq $requirementsHash) {
    return [pscustomobject]@{
        Status = 'current'
        Hash = $requirementsHash
        MarkerPath = $markerPath
    }
}

# The Radeon runtime owns the exact ROCm torch build. ComfyUI's requirements
# intentionally list the torch family without a version, so never feed those
# entries back to pip during an in-place dependency refresh.
$protectedTorchPackages = 'torch|torchvision|torchaudio'
$filtered = @(
    Get-Content -LiteralPath $requirementsPath | Where-Object {
        $line = ([string]$_).Trim()
        $line -notmatch "^(?i)($protectedTorchPackages)(\s|$)"
    }
)
$filtered | Set-Content -LiteralPath $filteredRequirementsPath -Encoding UTF8

Write-Host 'Managed ComfyUI requirements changed; synchronizing dependencies without replacing the pinned ROCm torch stack...' -ForegroundColor Yellow
$pipArguments = @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-cache-dir', '-r', $filteredRequirementsPath)
& $paths.TheRockPython @pipArguments
if ($LASTEXITCODE -ne 0) {
    throw "ComfyUI dependency synchronization failed with exit code $LASTEXITCODE. The previous requirements marker was left unchanged."
}

Set-Content -LiteralPath $markerPath -Value $requirementsHash -Encoding ASCII
return [pscustomobject]@{
    Status = 'updated'
    Hash = $requirementsHash
    MarkerPath = $markerPath
    FilteredRequirementsPath = $filteredRequirementsPath
}
