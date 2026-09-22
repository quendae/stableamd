Set-StrictMode -Version 2.0

# Shared dependency: avoid a forced nested reload that can hide Generation
# exports from a caller that imported them directly.
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Generation.psm1')

function New-StableAmdSdxlImg2ImgWorkflow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$CheckpointName,

        [Parameter(Mandatory = $true)]
        [string]$Prompt,

        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$InputImageName,

        [string]$NegativePrompt = 'low quality, blurry, distorted, artifacts, watermark, text',
        [int]$Width = 1024,
        [int]$Height = 1024,
        [int]$Steps = 20,
        [double]$Cfg = 7.0,
        [long]$Seed = 0,
        [string]$SamplerName = 'euler',
        [string]$Scheduler = 'normal',
        [string]$FilenamePrefix = 'StableAMD_SDXL_IMG2IMG',
        [double]$Denoise = 0.55
    )

    if ([string]::IsNullOrWhiteSpace($InputImageName)) {
        throw 'SDXL img2img requires an input image name.'
    }
    if ([IO.Path]::GetFileName($InputImageName) -ne $InputImageName) {
        throw 'SDXL img2img input image name must not contain a path.'
    }
    if ([double]::IsNaN($Denoise) -or [double]::IsInfinity($Denoise) -or $Denoise -lt 0 -or $Denoise -gt 1) {
        throw 'Denoise must be between 0 and 1.'
    }

    $workflow = New-StableAmdSdxlWorkflow `
        -CheckpointName $CheckpointName `
        -Prompt $Prompt `
        -NegativePrompt $NegativePrompt `
        -Width $Width `
        -Height $Height `
        -Steps $Steps `
        -Cfg $Cfg `
        -Seed $Seed `
        -SamplerName $SamplerName `
        -Scheduler $Scheduler `
        -FilenamePrefix $FilenamePrefix

    # Nodes 10-17 are reserved by the v0.3 ordered LoRA stack.
    $workflow['5'] = [ordered]@{
        class_type = 'LoadImage'
        inputs = [ordered]@{
            image = $InputImageName
        }
    }
    $workflow['18'] = [ordered]@{
        class_type = 'ImageScale'
        inputs = [ordered]@{
            image = @('5', 0)
            upscale_method = 'lanczos'
            width = $Width
            height = $Height
            crop = 'center'
        }
    }
    $workflow['19'] = [ordered]@{
        class_type = 'VAEEncode'
        inputs = [ordered]@{
            pixels = @('18', 0)
            vae = @('4', 2)
        }
    }
    $workflow['3'].inputs.latent_image = @('19', 0)
    $workflow['3'].inputs.denoise = $Denoise

    return $workflow
}

Export-ModuleMember -Function New-StableAmdSdxlImg2ImgWorkflow
