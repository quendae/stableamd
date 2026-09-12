[CmdletBinding()]
param(
    [int]$Limit = 0,
    [string]$RepoRoot = ''
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Generation.psm1') -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$history = @(Get-StableAmdGenerationHistory -HistoryRoot $paths.HistoryRoot)

if ($Limit -gt 0) {
    return @($history | Select-Object -First $Limit)
}

return $history
