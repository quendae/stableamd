[CmdletBinding()]
param(
    [string]$RepoRoot = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.BundleRoots.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Bundles.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.TemplateBundles.psm1') -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths

function Get-ExistingStableAmdBundleRoots {
    param([Parameter(Mandatory = $true)][string]$Role)

    return @(
        Get-StableAmdBundleAssetRootRecords -RepoRoot $RepoRoot -Role $Role |
            Where-Object { $_.exists } |
            ForEach-Object { [string]$_.path }
    )
}

$diffusionRoots = @(Get-ExistingStableAmdBundleRoots -Role 'diffusion_model')
$textEncoderRoots = @(Get-ExistingStableAmdBundleRoots -Role 'text_encoder')
$vaeRoots = @(Get-ExistingStableAmdBundleRoots -Role 'vae')

$discovered = @(
    Find-StableAmdTemplateBundles `
        -DiffusionRoots $diffusionRoots `
        -TextEncoderRoots $textEncoderRoots `
        -VaeRoots $vaeRoots
)

$complete = @()
foreach ($bundle in $discovered) {
    $validation = Test-StableAmdBundleEntry `
        -Entry $bundle `
        -RequiredRoles @('diffusion_model', 'text_encoder', 'vae') `
        -RequireFiles
    if ($validation.complete) { $complete += $bundle }
}

$registry = New-StableAmdEmptyBundleRegistry
foreach ($bundle in $complete) {
    $registry = Upsert-StableAmdBundleRegistryEntry -Registry $registry -Entry $bundle
}
Write-StableAmdBundleRegistry -Path $paths.BundlesRegistryPath -Registry $registry

[pscustomobject]@{
    count = @($complete).Count
    models = @($complete)
}
