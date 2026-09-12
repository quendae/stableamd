[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$RepoRoot = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.ModelRoots.psm1') -Force
return Add-StableAmdModelRoot -RepoRoot $RepoRoot -Path $Path
