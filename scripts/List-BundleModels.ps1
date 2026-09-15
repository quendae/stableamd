[CmdletBinding()]
param(
    [string]$RepoRoot = ''
)

$ErrorActionPreference = 'Stop'
$WarningPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

# Import shared primitives explicitly. Dependent modules must not force-reload
# these dependencies because this scanner uses their exports directly below.
# -DisableNameChecking keeps machine-facing discovery free of unapproved-verb
# warnings that otherwise pollute captured stdout on Windows PowerShell hosts.
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot 'StableAmd.BundleRoots.psm1') -Force -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Bundles.psm1') -Force -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot 'StableAmd.TemplateBundles.psm1') -Force -DisableNameChecking

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

# Find-StableAmdTemplateBundles remains the ready-only compatibility helper.
# Product discovery uses packages so incomplete known models stay visible.
$packages = @(
    Find-StableAmdTemplatePackages `
        -DiffusionRoots $diffusionRoots `
        -TextEncoderRoots $textEncoderRoots `
        -VaeRoots $vaeRoots
)

# The product model list keeps incomplete packages visible for diagnostics and
# setup UX. Only ready packages are persisted as executable bundle models.
$readyBundles = @($packages | Where-Object { $_.ready })
$complete = @()
foreach ($bundle in $readyBundles) {
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

# The bundle registry is derived state. Publish it atomically so concurrent API
# readers never observe a partially written JSON document during model refresh.
$tempRegistry = $paths.BundlesRegistryPath + '.tmp-' + [guid]::NewGuid().ToString('N')
try {
    Write-StableAmdBundleRegistry -Path $tempRegistry -Registry $registry
    Move-Item -LiteralPath $tempRegistry -Destination $paths.BundlesRegistryPath -Force
}
finally {
    Remove-Item -LiteralPath $tempRegistry -Force -ErrorAction SilentlyContinue
}

[pscustomobject]@{
    count = @($packages).Count
    readyCount = @($complete).Count
    models = [object[]]@($packages)
}
