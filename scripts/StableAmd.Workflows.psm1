Set-StrictMode -Version 2.0

# Generation is a shared dependency. Do not use -Force here: callers such as
# Invoke-Txt2Img.ps1 also import it directly for helper commands, and a forced
# nested reload can remove those exported commands from the caller session.
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Generation.psm1')
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Img2Img.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Inpaint.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.ZImageTurbo.psm1') -Force

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

        [string]$CheckpointName = '',

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
        [string]$DiffusionModelName = '',
        [string]$TextEncoderName = '',
        [string]$VaeName = '',
        [AllowEmptyCollection()]
        [object[]]$LoraStack = @(),
        [string]$LoraName = '',
        [double]$LoraModelStrength = 1.0,
        [double]$LoraClipStrength = 1.0
    )

    $normalizedFamily = $Family.Trim().ToLowerInvariant()
    $normalizedMode = $Mode.Trim().ToLowerInvariant()

    if ($normalizedFamily -eq 'sdxl' -and $normalizedMode -in @('txt2img', 'img2img', 'inpaint')) {
        if ([string]::IsNullOrWhiteSpace($CheckpointName)) {
            throw 'CheckpointName is required for the SDXL checkpoint provider.'
        }
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
        elseif ($normalizedMode -eq 'inpaint') {
            $workflow = New-StableAmdSdxlInpaintWorkflow @parameters -InputImageName $InputImageName -Denoise $Denoise
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

    if ($normalizedFamily -eq 'z-image-turbo' -and $normalizedMode -eq 'txt2img') {
        if (@($LoraStack).Count -gt 0 -or -not [string]::IsNullOrWhiteSpace($LoraName)) {
            throw 'LoRA execution is not implemented for Z-Image Turbo yet.'
        }

        $zSteps = if ($PSBoundParameters.ContainsKey('Steps')) { $Steps } else { 8 }
        $zCfg = if ($PSBoundParameters.ContainsKey('Cfg')) { $Cfg } else { 1.0 }
        $zSampler = if ($PSBoundParameters.ContainsKey('SamplerName')) { $SamplerName } else { 'res_multistep' }
        $zScheduler = if ($PSBoundParameters.ContainsKey('Scheduler')) { $Scheduler } else { 'simple' }
        $zPrefix = if ($PSBoundParameters.ContainsKey('FilenamePrefix')) { $FilenamePrefix } else { 'StableAMD_ZIMAGE_TURBO' }

        return New-StableAmdZImageTurboWorkflow `
            -DiffusionModelName $DiffusionModelName `
            -TextEncoderName $TextEncoderName `
            -VaeName $VaeName `
            -Prompt $Prompt `
            -Width $Width `
            -Height $Height `
            -Steps $zSteps `
            -Cfg $zCfg `
            -Seed $Seed `
            -SamplerName $zSampler `
            -Scheduler $zScheduler `
            -FilenamePrefix $zPrefix
    }

    throw "StableAMD workflow provider is not implemented for family '$normalizedFamily' and mode '$normalizedMode'."
}

Export-ModuleMember -Function New-StableAmdWorkflow, Add-StableAmdLoraStackToWorkflow
