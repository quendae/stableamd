Set-StrictMode -Version 2.0

function New-StableAmdSdxlWorkflow {
    [CmdletBinding()]
    param(
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
        [string]$FilenamePrefix = 'StableAMD_SDXL'
    )

    if ([string]::IsNullOrWhiteSpace($CheckpointName)) { throw 'CheckpointName cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($Prompt)) { throw 'Prompt cannot be empty.' }
    if ($Width -le 0 -or $Height -le 0) { throw 'Width and Height must be positive.' }
    if (($Width % 8) -ne 0 -or ($Height % 8) -ne 0) { throw 'Width and Height must be divisible by 8 for the v0.1 SDXL workflow.' }
    if ($Steps -lt 1 -or $Steps -gt 1000) { throw 'Steps must be between 1 and 1000.' }
    if ($Cfg -le 0) { throw 'CFG must be greater than zero.' }
    if ($Seed -lt 0) { throw 'Seed must be zero or greater.' }
    if ([string]::IsNullOrWhiteSpace($SamplerName)) { throw 'SamplerName cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($Scheduler)) { throw 'Scheduler cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($FilenamePrefix)) { throw 'FilenamePrefix cannot be empty.' }

    return [ordered]@{
        '4' = [ordered]@{
            class_type = 'CheckpointLoaderSimple'
            inputs = [ordered]@{
                ckpt_name = $CheckpointName
            }
        }
        '6' = [ordered]@{
            class_type = 'CLIPTextEncode'
            inputs = [ordered]@{
                text = $Prompt
                clip = @('4', 1)
            }
        }
        '7' = [ordered]@{
            class_type = 'CLIPTextEncode'
            inputs = [ordered]@{
                text = $NegativePrompt
                clip = @('4', 1)
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
                model = @('4', 0)
                positive = @('6', 0)
                negative = @('7', 0)
                latent_image = @('5', 0)
            }
        }
        '8' = [ordered]@{
            class_type = 'VAEDecode'
            inputs = [ordered]@{
                samples = @('3', 0)
                vae = @('4', 2)
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

function Resolve-StableAmdComfyCheckpointName {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$ModelPath,

        [Parameter(Mandatory = $true)]
        [string[]]$CheckpointChoices
    )

    $leaf = [IO.Path]::GetFileName($ModelPath)
    if ([string]::IsNullOrWhiteSpace($leaf)) { return $null }

    $exact = @($CheckpointChoices | Where-Object { [string]$_ -ieq $leaf })
    if ($exact.Count -eq 1) { return [string]$exact[0] }

    $suffixPattern = '(?i)(^|[\\/])' + [regex]::Escape($leaf) + '$'
    $suffix = @($CheckpointChoices | Where-Object { [string]$_ -match $suffixPattern })
    if ($suffix.Count -eq 1) { return [string]$suffix[0] }

    return $null
}

function New-StableAmdRandomSeed {
    [CmdletBinding()]
    param()

    $bytes = New-Object byte[] 8
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) }
    finally { $rng.Dispose() }

    # Clear the sign bit so the value fits the non-negative Int64 contract used
    # by the Windows PowerShell API wrapper while still providing 63 random bits.
    $bytes[7] = $bytes[7] -band 0x7F
    return [BitConverter]::ToInt64($bytes, 0)
}

Export-ModuleMember -Function New-StableAmdSdxlWorkflow, Resolve-StableAmdComfyCheckpointName, New-StableAmdRandomSeed
