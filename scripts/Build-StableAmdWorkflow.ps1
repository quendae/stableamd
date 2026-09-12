[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Family,
    [Parameter(Mandatory = $true)][ValidateSet('txt2img', 'img2img', 'inpaint', 'controlnet')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$CheckpointName,
    [Parameter(Mandatory = $true)][string]$Prompt,
    [string]$NegativePrompt = 'low quality, blurry, distorted, artifacts, watermark, text',
    [int]$Width = 1024,
    [int]$Height = 1024,
    [int]$Steps = 20,
    [double]$Cfg = 7.0,
    [long]$Seed = 0,
    [string]$SamplerName = 'euler',
    [string]$Scheduler = 'normal',
    [string]$FilenamePrefix = 'StableAMD',
    [string]$InputImageName = '',
    [double]$Denoise = 0.55,
    [string]$LoraStackJson = '',
    [string]$RepoRoot = ''
)

$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Workflows.psm1') -Force

$loraStack = @()
if (-not [string]::IsNullOrWhiteSpace($LoraStackJson)) {
    try { $parsed = $LoraStackJson | ConvertFrom-Json }
    catch { throw "LoraStackJson must contain valid JSON: $($_.Exception.Message)" }
    if ($null -ne $parsed) { $loraStack = @($parsed) }
}

$params = @{
    Family = $Family
    Mode = $Mode
    CheckpointName = $CheckpointName
    Prompt = $Prompt
    NegativePrompt = $NegativePrompt
    Width = $Width
    Height = $Height
    Steps = $Steps
    Cfg = $Cfg
    Seed = $Seed
    SamplerName = $SamplerName
    Scheduler = $Scheduler
    FilenamePrefix = $FilenamePrefix
    LoraStack = $loraStack
}
if ($Mode -in @('img2img', 'inpaint')) {
    $params.InputImageName = $InputImageName
    $params.Denoise = $Denoise
}

return New-StableAmdWorkflow @params
