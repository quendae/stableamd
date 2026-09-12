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

$existing = Read-StableAmdModelRegistry -Path $paths.ModelsRegistryPath
$registry = Merge-StableAmdModelRegistry -ExistingRegistry $existing -DiscoveredModels $discovered
Write-StableAmdModelRegistry -Path $paths.ModelsRegistryPath -Registry $registry

return [pscustomobject]@{
    models = [object[]]@($registry.models)
    count = @($registry.models).Count
}
