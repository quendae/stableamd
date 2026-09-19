[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [Parameter(Mandatory = $true)]
    [ValidateSet('diffusion_model', 'text_encoder', 'vae')]
    [string]$Role
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
Import-Module (Join-Path $PSScriptRoot 'StableAmd.BundleRoots.psm1') -Force
return @(Get-StableAmdBundleAssetRootRecords -RepoRoot $RepoRoot -Role $Role)
