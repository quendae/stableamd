[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [switch]$NoRegistryUpdate
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Models.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.ModelFamilies.psm1') -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths
$config = Read-StableAmdConfig -RepoRoot $RepoRoot

$roots = @()
foreach ($root in @($config.models.roots)) {
    if ([string]::IsNullOrWhiteSpace([string]$root)) { continue }
    $roots += Resolve-StableAmdPath -Path ([string]$root) -RepoRoot $RepoRoot
}

$discovered = @(Find-StableAmdCheckpoints -Roots $roots)
# v0.3 keeps discovery/storage separate from family identification so newer
# model lineages can be added without destabilizing the v0.1 registry module.
foreach ($entry in $discovered) {
    $entry.Family = Get-StableAmdModelFamily -Name ([string]$entry.Name)
}

if ($NoRegistryUpdate) {
    return [pscustomobject]@{
        models = [object[]]@($discovered)
        count = @($discovered).Count
    }
}

# The registry is derived cache/state, not the source of truth. Earlier v0.3
# builds could leave models.json truncated if two HTTP requests refreshed model
# discovery while Set-Content was replacing the file. Never let a broken cache
# make the whole Generate page unusable: quarantine it and rebuild from disk.
try {
    $existing = Read-StableAmdModelRegistry -Path $paths.ModelsRegistryPath
}
catch {
    if (Test-Path -LiteralPath $paths.ModelsRegistryPath -PathType Leaf) {
        $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
        $quarantine = $paths.ModelsRegistryPath + '.corrupt-' + $stamp
        try {
            Move-Item -LiteralPath $paths.ModelsRegistryPath -Destination $quarantine -Force -ErrorAction Stop
            Write-Warning "StableAMD recovered a corrupt model registry. Previous file: $quarantine"
        }
        catch {
            Remove-Item -LiteralPath $paths.ModelsRegistryPath -Force -ErrorAction SilentlyContinue
            Write-Warning 'StableAMD recovered a corrupt model registry and removed the unreadable cache.'
        }
    }
    $existing = New-StableAmdEmptyModelRegistry
}

$registry = Merge-StableAmdModelRegistry -ExistingRegistry $existing -DiscoveredModels $discovered

# Write through a sibling temporary file and rename it into place. Readers now
# see either the previous complete registry or the new complete registry, never
# a half-written JSON document.
$tempRegistry = $paths.ModelsRegistryPath + '.tmp-' + [guid]::NewGuid().ToString('N')
try {
    Write-StableAmdModelRegistry -Path $tempRegistry -Registry $registry
    Move-Item -LiteralPath $tempRegistry -Destination $paths.ModelsRegistryPath -Force
}
finally {
    Remove-Item -LiteralPath $tempRegistry -Force -ErrorAction SilentlyContinue
}

return [pscustomobject]@{
    models = [object[]]@($registry.models)
    count = @($registry.models).Count
}
