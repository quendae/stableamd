Set-StrictMode -Version 2.0

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Generation.psm1') -Force

function New-StableAmdWorkflow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Family,

        [Parameter(Mandatory = $true)]
        [ValidateSet('txt2img', 'img2img', 'inpaint', 'controlnet')]
        [string]$Mode,

        [Parameter(Mandatory = $true)]
        [string]$CheckpointName,

        [Parameter(Mandatory = $true)]
        [string]$Prompt,

        [string]$NegativePrompt = 'low quality, blurry, distorted, artifacts, watermark, text',
        [int]$Width = 1024,
        [int]$Height = 1024,
        [int]$Steps = 20,
        [double]$Cfg = 7.0,
        [long]$Seed = 0,
        [string]$SamplerName = 'euler',
        [string]$Scheduler = 'normal',
        [string]$FilenamePrefix = 'StableAMD',
        [string]$LoraName = '',
        [double]$LoraModelStrength = 1.0,
        [double]$LoraClipStrength = 1.0
    )

    $normalizedFamily = $Family.Trim().ToLowerInvariant()
    $normalizedMode = $Mode.Trim().ToLowerInvariant()

    if ($normalizedFamily -eq 'sdxl' -and $normalizedMode -eq 'txt2img') {
        $parameters = @{
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
        }
        if (-not [string]::IsNullOrWhiteSpace($LoraName)) {
            $parameters.LoraName = $LoraName
            $parameters.LoraModelStrength = $LoraModelStrength
            $parameters.LoraClipStrength = $LoraClipStrength
        }
        return New-StableAmdSdxlWorkflow @parameters
    }

    throw "StableAMD workflow provider is not implemented for family '$normalizedFamily' and mode '$normalizedMode'."
}

Export-ModuleMember -Function New-StableAmdWorkflow
