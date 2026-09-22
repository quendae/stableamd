Set-StrictMode -Version 2.0

function New-StableAmdKrea2Workflow {
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
        [string]$SamplerName = 'euler',
        [string]$Scheduler = 'simple',
        [string]$FilenamePrefix = 'StableAMD_KREA2_TURBO',
        [ValidateSet('default', 'cpu')][string]$TextEncoderDevice = 'default'
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
    if ($Width -le 0 -or $Height -le 0 -or ($Width % 16) -ne 0 -or ($Height % 16) -ne 0) {
        throw 'Width and Height must be positive and divisible by 16 for Krea 2.'
    }
    if ($Steps -lt 1 -or $Steps -gt 1000) { throw 'Steps must be between 1 and 1000.' }
    if ($Cfg -le 0) { throw 'CFG must be greater than zero.' }
    if ($Seed -lt 0) { throw 'Seed must be zero or greater.' }

    # Flat equivalent of Comfy-Org/workflow_templates image_krea2_turbo_t2i.
    # The official Turbo path is 8 steps, CFG 1, Euler + simple scheduler.
    # Let ComfyUI place/offload Qwen3-VL through the managed GPU/DynamicVRAM
    # policy by default. Physical v2 testing showed that forcing the ~5 GB text
    # encoder to CPU can saturate the host for many minutes before sampling.
    # An explicit CPU fallback remains available for constrained hosts.
    return [ordered]@{
        '10' = [ordered]@{
            class_type = 'UNETLoader'
            inputs = [ordered]@{
                unet_name = $DiffusionModelName
                weight_dtype = 'default'
            }
        }
        '11' = [ordered]@{
            class_type = 'CLIPLoader'
            inputs = [ordered]@{
                clip_name = $TextEncoderName
                type = 'krea2'
                device = $TextEncoderDevice
            }
        }
        '12' = [ordered]@{
            class_type = 'VAELoader'
            inputs = [ordered]@{
                vae_name = $VaeName
            }
        }
        '6' = [ordered]@{
            class_type = 'CLIPTextEncode'
            inputs = [ordered]@{
                text = $Prompt
                clip = @('11', 0)
            }
        }
        '13' = [ordered]@{
            class_type = 'ConditioningZeroOut'
            inputs = [ordered]@{
                conditioning = @('6', 0)
            }
        }
        '5' = [ordered]@{
            class_type = 'EmptyLatentImage'
            inputs = [ordered]@{
                width = $Width
                height = $Height
                batch_size = 1
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
                model = @('10', 0)
                positive = @('6', 0)
                negative = @('13', 0)
                latent_image = @('5', 0)
            }
        }
        '8' = [ordered]@{
            class_type = 'VAEDecode'
            inputs = [ordered]@{
                samples = @('3', 0)
                vae = @('12', 0)
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

Export-ModuleMember -Function New-StableAmdKrea2Workflow
