[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ModelPath,
    [string]$RepoRoot = '',
    [switch]$IncludeSha256
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Models.psm1') -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$resolvedModelPath = if ([IO.Path]::IsPathRooted($ModelPath)) {
    [IO.Path]::GetFullPath($ModelPath)
}
else {
    Resolve-StableAmdPath -Path $ModelPath -RepoRoot $RepoRoot
}

if (-not (Test-Path $resolvedModelPath -PathType Leaf)) {
    throw "Model file was not found: '$resolvedModelPath'."
}

# Hugging Face downloads are staged as `<name>.safetensors.partial` so they can
# be resumed and structurally checked before the atomic rename to the final
# `.safetensors` path. Both forms contain the same safetensors bytes.
$modelLeaf = [IO.Path]::GetFileName($resolvedModelPath)
if ($modelLeaf -notmatch '(?i)\.safetensors(?:\.partial)?$') {
    throw "StableAMD v0.1 validation supports .safetensors and .safetensors.partial files only: '$resolvedModelPath'."
}
$logicalModelName = $modelLeaf -replace '(?i)\.partial$', ''

if (-not (Test-Path $paths.TheRockPython -PathType Leaf)) {
    throw "StableAMD TheRock Python is missing at '$($paths.TheRockPython)'. Install the runtime before validating models."
}

$validatorPath = Join-Path $PSScriptRoot 'probes/validate_safetensors.py'
if (-not (Test-Path $validatorPath -PathType Leaf)) {
    throw "Safetensors validator is missing at '$validatorPath'."
}

$stderrPath = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-validate-' + [guid]::NewGuid().ToString('N') + '.stderr.log')
try {
    $raw = @()
    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $raw = @(& $paths.TheRockPython -s $validatorPath $resolvedModelPath 2> $stderrPath | ForEach-Object { [string]$_ })
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }

    $jsonLine = $raw | Where-Object { $_.Trim().StartsWith('{') -and $_.Trim().EndsWith('}') } | Select-Object -Last 1
    if ([string]::IsNullOrWhiteSpace([string]$jsonLine)) {
        $stderrText = if (Test-Path $stderrPath) { @(Get-Content $stderrPath -ErrorAction SilentlyContinue) -join "`n" } else { '' }
        throw "Safetensors validator did not return JSON. Exit code: $exitCode. $stderrText"
    }

    try { $validation = $jsonLine | ConvertFrom-Json }
    catch { throw "Could not parse safetensors validation result: $($_.Exception.Message)" }

    $valid = ($exitCode -eq 0 -and [bool]$validation.valid)
    $sha256 = $null
    if ($IncludeSha256) {
        $sha256 = (Get-FileHash -Path $resolvedModelPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }

    return [pscustomobject]@{
        Id = Get-StableAmdModelId -Path $resolvedModelPath
        Name = $logicalModelName
        Path = $resolvedModelPath
        Family = Get-StableAmdModelFamily -Name $logicalModelName
        Valid = $valid
        Validation = if ($valid) { 'valid' } else { 'invalid' }
        Sha256 = $sha256
        Details = $validation
    }
}
finally {
    Remove-Item -Path $stderrPath -Force -ErrorAction SilentlyContinue
}
