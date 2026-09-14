Set-StrictMode -Version 2.0

function New-StableAmdZImageTurboWorkflow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$DiffusionModelName,
        [Parameter(Mandatory = $true)][string]$TextEncoderName,
        [Parameter(Mandatory = $true)][string]$VaeName,
        [Parameter(Mandatory = $true)][string]$Prompt,
        [int]$Width = 1024,
        [int]$Height = 1024,
        [int]$Steps = 8,
        [double]$Cfg = 1.0,
        [long]$Seed = 0,
        [string]$SamplerName = 'res_multistep',
        [string]$Scheduler = 'simple',
        [string]$FilenamePrefix = 'StableAMD_ZIMAGE_TURBO'
    )

    foreach ($value in @(
        @{ Name = 'DiffusionModelName'; Value = $DiffusionModelName },
        @{ Name = 'TextEncoderName'; Value = $TextEncoderName },
        @{ Name = 'VaeName'; Value = $VaeName },
        @{ Name = 'Prompt'; Value = $Prompt },
        @{ Name = 'SamplerName'; Value = $SamplerName },
        @{ Name = 'Scheduler'; Value = $Scheduler },
        @{ Name = 'FilenamePrefix'; Value = $FilenamePrefix }
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$value.Value)) {
            throw "$($value.Name) cannot be empty."
        }
    }
    if ($Width -le 0 -or $Height -le 0 -or ($Width % 8) -ne 0 -or ($Height % 8) -ne 0) {
        throw 'Width and Height must be positive and divisible by 8 for Z-Image Turbo.'
    }
    if ($Steps -lt 1 -or $Steps -gt 1000) { throw 'Steps must be between 1 and 1000.' }
    if ($Cfg -le 0) { throw 'CFG must be greater than zero.' }
    if ($Seed -lt 0) { throw 'Seed must be zero or greater.' }

    # Graph follows Comfy-Org/workflow_templates image_z_image_turbo.json.
    # Z-Image Turbo uses Lumina2 text conditioning, an SD3 latent layout and
    # AuraFlow model sampling with shift=3. Keep the large text encoder on CPU
    # so the diffusion model can use the RX 6950 XT VRAM during sampling.
    #
    # The Windows ROCm/gfx1030 path uses tiled VAE decode as a stability guard.
    # A full-frame CPU VAEDecode has intermittently crashed in ComfyUI's split
    # attention torch.bmm path even after successful sampling. 512px tiles keep
    # the same VAE and image dimensions while bounding the attention workspace.
    return [ordered]@{
        '28' = [ordered]@{
            class_type = 'UNETLoader'
            inputs = [ordered]@{
                unet_name = $DiffusionModelName
                weight_dtype = 'default'
            }
        }
        '30' = [ordered]@{
            class_type = 'CLIPLoader'
            inputs = [ordered]@{
                clip_name = $TextEncoderName
                type = 'lumina2'
                device = 'cpu'
            }
        }
        '29' = [ordered]@{
            class_type = 'VAELoader'
            inputs = [ordered]@{
                vae_name = $VaeName
            }
        }
        '27' = [ordered]@{
            class_type = 'CLIPTextEncode'
            inputs = [ordered]@{
                text = $Prompt
                clip = @('30', 0)
            }
        }
        '33' = [ordered]@{
            class_type = 'ConditioningZeroOut'
            inputs = [ordered]@{
                conditioning = @('27', 0)
            }
        }
        '13' = [ordered]@{
            class_type = 'EmptySD3LatentImage'
            inputs = [ordered]@{
                width = $Width
                height = $Height
                batch_size = 1
            }
        }
        '11' = [ordered]@{
            class_type = 'ModelSamplingAuraFlow'
            inputs = [ordered]@{
                model = @('28', 0)
                shift = 3.0
            }
        }
        '3' = [ordered]@{
            class_type = 'KSampler'
            inputs = [ordered]@{
                seed = $Seed
                steps = $Steps
                cfg = $Cfg
                sampler_name = $SamplerName
                scheduler = $Scheduler
                denoise = 1.0
                model = @('11', 0)
                positive = @('27', 0)
                negative = @('33', 0)
                latent_image = @('13', 0)
            }
        }
        '8' = [ordered]@{
            class_type = 'VAEDecodeTiled'
            inputs = [ordered]@{
                samples = @('3', 0)
                vae = @('29', 0)
                tile_size = 512
                overlap = 64
                temporal_size = 64
                temporal_overlap = 8
            }
        }
        '9' = [ordered]@{
            class_type = 'SaveImage'
            inputs = [ordered]@{
                filename_prefix = $FilenamePrefix
                images = @('8', 0)
            }
        }
    }
}

Export-ModuleMember -Function New-StableAmdZImageTurboWorkflow
