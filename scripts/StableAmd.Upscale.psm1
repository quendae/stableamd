Set-StrictMode -Version 2.0

function New-StableAmdUpscaleWorkflow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$InputImageName,
        [Parameter(Mandatory = $true)][string]$ModelName,
        [string]$FilenamePrefix = 'StableAMD_UPSCALE'
    )

    foreach ($value in @(
        @{ Name = 'InputImageName'; Value = $InputImageName },
        @{ Name = 'ModelName'; Value = $ModelName },
        @{ Name = 'FilenamePrefix'; Value = $FilenamePrefix }
    )) {
        if ([string]::IsNullOrWhiteSpace([string]$value.Value)) {
            throw "$($value.Name) cannot be empty."
        }
    }
    if ([IO.Path]::IsPathRooted($InputImageName) -or $InputImageName.Contains('..')) {
        throw 'InputImageName must be a managed ComfyUI input filename.'
    }

    return [ordered]@{
        '1' = [ordered]@{
            class_type = 'LoadImage'
            inputs = [ordered]@{
                image = $InputImageName
                upload = 'image'
            }
        }
        '2' = [ordered]@{
            class_type = 'UpscaleModelLoader'
            inputs = [ordered]@{
                model_name = $ModelName
            }
        }
        '3' = [ordered]@{
            class_type = 'ImageUpscaleWithModel'
            inputs = [ordered]@{
                upscale_model = @('2', 0)
                image = @('1', 0)
            }
        }
        '9' = [ordered]@{
            class_type = 'SaveImage'
            inputs = [ordered]@{
                filename_prefix = $FilenamePrefix
                images = @('3', 0)
            }
        }
    }
}

Export-ModuleMember -Function New-StableAmdUpscaleWorkflow
