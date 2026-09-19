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
$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$state = Read-StableAmdBackendState -Path $paths.BackendStatePath
if ($null -eq $state -or [string]::IsNullOrWhiteSpace([string]$state.url)) {
    throw 'StableAMD compute backend is not running.'
}

$url = [string]$state.url
if (-not $url.EndsWith('/')) { $url += '/' }
try {
    $info = Invoke-RestMethod -Uri "${url}object_info/UpscaleModelLoader" -Method Get -TimeoutSec 10
}
catch {
    throw "Could not query ComfyUI object_info/UpscaleModelLoader: $($_.Exception.Message)"
}

$node = $info.UpscaleModelLoader
$choices = @()
if ($null -ne $node -and $null -ne $node.input -and $null -ne $node.input.required -and $null -ne $node.input.required.model_name) {
    $raw = @($node.input.required.model_name)
    if ($raw.Count -gt 0) { $choices = @($raw[0]) }
}

return [pscustomobject]@{
    root = $paths.UpscaleModelsRoot
    models = @($choices | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}
