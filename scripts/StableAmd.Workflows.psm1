Set-StrictMode -Version 2.0

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Generation.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Img2Img.psm1') -Force

function Get-StableAmdLoraValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowNull()]
        [object]$Entry,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [AllowNull()]
        $Default = $null
    )

    if ($null -eq $Entry) { return $Default }
    if ($Entry -is [System.Collections.IDictionary]) {
        if ($Entry.Contains($Name)) { return $Entry[$Name] }
        return $Default
    }

    $property = $Entry.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Add-StableAmdLoraStackToWorkflow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Workflow,

        [AllowEmptyCollection()]
        [object[]]$LoraStack = @(),

        [int]$FirstNodeId = 10,
        [int]$MaxLoras = 8
    )

    $entries = @($LoraStack | Where-Object { $null -ne $_ })
    if ($entries.Count -eq 0) { return $Workflow }
    if ($entries.Count -gt $MaxLoras) {
        throw "StableAMD supports at most $MaxLoras LoRAs in one stack."
    }

    $modelRef = @('4', 0)
    $clipRef = @('4', 1)

    for ($index = 0; $index -lt $entries.Count; $index++) {
        $entry = $entries[$index]
        $name = [string](Get-StableAmdLoraValue -Entry $entry -Name 'name' -Default '')
        if ([string]::IsNullOrWhiteSpace($name)) {
            throw "LoRA stack entry $($index + 1) does not contain a name."
        }

        $enabled = [bool](Get-StableAmdLoraValue -Entry $entry -Name 'enabled' -Default $true)
        if (-not $enabled) { continue }

        $modelStrength = [double](Get-StableAmdLoraValue -Entry $entry -Name 'modelStrength' -Default 1.0)
        $clipStrength = [double](Get-StableAmdLoraValue -Entry $entry -Name 'clipStrength' -Default 1.0)
        foreach ($value in @($modelStrength, $clipStrength)) {
            if ([double]::IsNaN($value) -or [double]::IsInfinity($value) -or $value -lt -100 -or $value -gt 100) {
                throw 'LoRA strengths must be between -100 and 100.'
            }
        }

        $nodeId = [string]($FirstNodeId + $index)
        $Workflow[$nodeId] = [ordered]@{
            class_type = 'LoraLoader'
            inputs = [ordered]@{
                lora_name = $name
                strength_model = $modelStrength
                strength_clip = $clipStrength
                model = $modelRef
                clip = $clipRef
            }
        }
        $modelRef = @($nodeId, 0)
        $clipRef = @($nodeId, 1)
    }

    $Workflow['3'].inputs.model = $modelRef
    $Workflow['6'].inputs.clip = $clipRef
    $Workflow['7'].inputs.clip = $clipRef
    return $Workflow
}

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
        [string]$InputImageName = '',
        [double]$Denoise = 0.55,
        [AllowEmptyCollection()]
        [object[]]$LoraStack = @(),
        [string]$LoraName = '',
        [double]$LoraModelStrength = 1.0,
        [double]$LoraClipStrength = 1.0
    )

    $normalizedFamily = $Family.Trim().ToLowerInvariant()
    $normalizedMode = $Mode.Trim().ToLowerInvariant()

    if ($normalizedFamily -eq 'sdxl' -and $normalizedMode -in @('txt2img', 'img2img')) {
        if (@($LoraStack).Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($LoraName)) {
            throw 'Specify LoraStack or the legacy single LoraName fields, not both.'
        }

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

        if ($normalizedMode -eq 'img2img') {
            $workflow = New-StableAmdSdxlImg2ImgWorkflow @parameters -InputImageName $InputImageName -Denoise $Denoise
        }
        else {
            $workflow = New-StableAmdSdxlWorkflow @parameters
        }

        $resolvedStack = @($LoraStack)
        if ($resolvedStack.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace($LoraName)) {
            $resolvedStack = @(
                [pscustomobject]@{
                    name = $LoraName
                    modelStrength = $LoraModelStrength
                    clipStrength = $LoraClipStrength
                    enabled = $true
                }
            )
        }

        return Add-StableAmdLoraStackToWorkflow -Workflow $workflow -LoraStack $resolvedStack
    }

    throw "StableAMD workflow provider is not implemented for family '$normalizedFamily' and mode '$normalizedMode'."
}

Export-ModuleMember -Function New-StableAmdWorkflow, Add-StableAmdLoraStackToWorkflow
