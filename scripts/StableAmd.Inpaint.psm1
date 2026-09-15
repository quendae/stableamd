Set-StrictMode -Version 2.0

# Shared generation dependency. Keep the caller-visible exports intact.
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Generation.psm1')

function New-StableAmdSdxlInpaintWorkflow {
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
        [string]$FilenamePrefix = 'StableAMD_SDXL_INPAINT',
        [double]$Denoise = 0.8,
        [int]$GrowMaskBy = 6
    )

    if ([string]::IsNullOrWhiteSpace($InputImageName)) {
        throw 'SDXL inpaint requires an input image name.'
    }
    if ([IO.Path]::GetFileName($InputImageName) -ne $InputImageName) {
        throw 'SDXL inpaint input image name must not contain a path.'
    }
    if ([IO.Path]::GetExtension($InputImageName) -ine '.png') {
        throw 'SDXL inpaint requires a PNG input so the mask can be carried in the alpha channel.'
    }
    if ([double]::IsNaN($Denoise) -or [double]::IsInfinity($Denoise) -or $Denoise -lt 0 -or $Denoise -gt 1) {
        throw 'Denoise must be between 0 and 1.'
    }
    if ($GrowMaskBy -lt 0 -or $GrowMaskBy -gt 64) {
        throw 'GrowMaskBy must be between 0 and 64 pixels.'
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

    # The browser sends one managed PNG: source RGB plus the painted mask in
    # the PNG alpha channel. ComfyUI LoadImage exposes that alpha channel as MASK.
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

    # Keep the mask dimensions aligned with the resized source image. Core
    # ComfyUI mask nodes let us resize through IMAGE without custom nodes.
    $workflow['20'] = [ordered]@{
        class_type = 'MaskToImage'
        inputs = [ordered]@{
            mask = @('5', 1)
        }
    }
    $workflow['21'] = [ordered]@{
        class_type = 'ImageScale'
        inputs = [ordered]@{
            image = @('20', 0)
            upscale_method = 'nearest-exact'
            width = $Width
            height = $Height
            crop = 'center'
        }
    }
    $workflow['22'] = [ordered]@{
        class_type = 'ImageToMask'
        inputs = [ordered]@{
            image = @('21', 0)
            channel = 'red'
        }
    }

    $workflow['19'] = [ordered]@{
        class_type = 'VAEEncodeForInpaint'
        inputs = [ordered]@{
            pixels = @('18', 0)
            vae = @('4', 2)
            mask = @('22', 0)
            grow_mask_by = $GrowMaskBy
        }
    }

    $workflow['3'].inputs.latent_image = @('19', 0)
    $workflow['3'].inputs.denoise = $Denoise

    return $workflow
}

Export-ModuleMember -Function New-StableAmdSdxlInpaintWorkflow
