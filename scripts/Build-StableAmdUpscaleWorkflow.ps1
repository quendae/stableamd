[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InputImageName,
    [Parameter(Mandatory = $true)][string]$ModelName,
    [string]$FilenamePrefix = 'StableAMD_UPSCALE'
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Upscale.psm1') -Force

return New-StableAmdUpscaleWorkflow -InputImageName $InputImageName -ModelName $ModelName -FilenamePrefix $FilenamePrefix
