[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [string]$OutputDirectory = '',
    [string]$Version = '0.1.0'
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $RepoRoot 'dist'
}
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)

if ($Version -notmatch '^[0-9A-Za-z][0-9A-Za-z._-]*$') {
    throw "Package version '$Version' contains unsupported characters."
}

$requiredFiles = @(
    'README.md',
    'Start-StableAMD.cmd',
    'Stop-StableAMD.cmd'
)
$requiredDirectories = @(
    'app',
    'config',
    'scripts'
)

foreach ($relativePath in $requiredFiles) {
    $path = Join-Path $RepoRoot $relativePath
    if (-not (Test-Path $path -PathType Leaf)) {
        throw "Required package file is missing: '$path'."
    }
}
foreach ($relativePath in $requiredDirectories) {
    $path = Join-Path $RepoRoot $relativePath
    if (-not (Test-Path $path -PathType Container)) {
        throw "Required package directory is missing: '$path'."
    }
}

$runtimeLock = Join-Path $RepoRoot 'config/runtime-lock.v0.1.json'
if (-not (Test-Path $runtimeLock -PathType Leaf)) {
    throw "Runtime lock is missing: '$runtimeLock'."
}

$packageName = "StableAMD-$Version"
$packageRoot = Join-Path $OutputDirectory $packageName
$zipPath = Join-Path $OutputDirectory "$packageName.zip"

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
if (Test-Path $packageRoot) {
    Remove-Item -Path $packageRoot -Recurse -Force
}
if (Test-Path $zipPath) {
    Remove-Item -Path $zipPath -Force
}
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null

foreach ($relativePath in $requiredFiles) {
    Copy-Item -Path (Join-Path $RepoRoot $relativePath) -Destination (Join-Path $packageRoot $relativePath) -Force
}
foreach ($relativePath in $requiredDirectories) {
    Copy-Item -Path (Join-Path $RepoRoot $relativePath) -Destination (Join-Path $packageRoot $relativePath) -Recurse -Force
}

$validationSource = Join-Path $RepoRoot 'docs/v0.1-validation.md'
if (Test-Path $validationSource -PathType Leaf) {
    $docsDestination = Join-Path $packageRoot 'docs'
    New-Item -ItemType Directory -Path $docsDestination -Force | Out-Null
    Copy-Item -Path $validationSource -Destination (Join-Path $docsDestination 'v0.1-validation.md') -Force
}

# Release packages intentionally contain source and configuration only. Multi-gigabyte
# runtimes, models, outputs and diagnostics remain machine-local under .runtime/.
foreach ($forbidden in @('.runtime', 'diagnostics', 'tests', '.git')) {
    $candidate = Join-Path $packageRoot $forbidden
    if (Test-Path $candidate) {
        Remove-Item -Path $candidate -Recurse -Force
    }
}

Compress-Archive -Path $packageRoot -DestinationPath $zipPath -CompressionLevel Optimal -Force

return [pscustomobject]@{
    Version = $Version
    PackageName = $packageName
    PackageRoot = $packageRoot
    ZipPath = $zipPath
    RuntimeIncluded = $false
    ModelsIncluded = $false
}
