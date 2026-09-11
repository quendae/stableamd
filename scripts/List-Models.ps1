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

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths
$config = Read-StableAmdConfig -RepoRoot $RepoRoot

$roots = @()
foreach ($root in @($config.models.roots)) {
    if ([string]::IsNullOrWhiteSpace([string]$root)) { continue }
    $roots += Resolve-StableAmdPath -Path ([string]$root) -RepoRoot $RepoRoot
}

$discovered = @(Find-StableAmdCheckpoints -Roots $roots)
if ($NoRegistryUpdate) {
    Write-Output -NoEnumerate ([object[]]$discovered)
    return
}

$existing = Read-StableAmdModelRegistry -Path $paths.ModelsRegistryPath
$registry = Merge-StableAmdModelRegistry -ExistingRegistry $existing -DiscoveredModels $discovered
Write-StableAmdModelRegistry -Path $paths.ModelsRegistryPath -Registry $registry

Write-Output -NoEnumerate ([object[]]@($registry.models))
