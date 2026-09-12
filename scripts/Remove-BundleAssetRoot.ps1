[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [Parameter(Mandatory = $true)]
    [ValidateSet('diffusion_model', 'text_encoder', 'vae')]
    [string]$Role,
    [Parameter(Mandatory = $true)]
    [string]$Path
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path -Parent $PSScriptRoot }
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
Import-Module (Join-Path $PSScriptRoot 'StableAmd.BundleRoots.psm1') -Force
return Remove-StableAmdBundleAssetRoot -RepoRoot $RepoRoot -Role $Role -Path $Path
