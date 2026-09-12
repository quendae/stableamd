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
        [string]$FilenamePrefix = 'StableAMD_SDXL',
        [string]$LoraName = '',
        [double]$LoraModelStrength = 1.0,
        [double]$LoraClipStrength = 1.0
    )

    if ([string]::IsNullOrWhiteSpace($CheckpointName)) { throw 'CheckpointName cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($Prompt)) { throw 'Prompt cannot be empty.' }
    if ($Width -le 0 -or $Height -le 0) { throw 'Width and Height must be positive.' }
    if (($Width % 8) -ne 0 -or ($Height % 8) -ne 0) { throw 'Width and Height must be divisible by 8 for the StableAMD SDXL workflow.' }
    if ($Steps -lt 1 -or $Steps -gt 1000) { throw 'Steps must be between 1 and 1000.' }
    if ($Cfg -le 0) { throw 'CFG must be greater than zero.' }
    if ($Seed -lt 0) { throw 'Seed must be zero or greater.' }
    if ([string]::IsNullOrWhiteSpace($SamplerName)) { throw 'SamplerName cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($Scheduler)) { throw 'Scheduler cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($FilenamePrefix)) { throw 'FilenamePrefix cannot be empty.' }
    if (-not [string]::IsNullOrWhiteSpace($LoraName)) {
        if ([double]::IsNaN($LoraModelStrength) -or [double]::IsInfinity($LoraModelStrength) -or $LoraModelStrength -lt -100 -or $LoraModelStrength -gt 100) {
            throw 'LoRA model strength must be between -100 and 100.'
        }
        if ([double]::IsNaN($LoraClipStrength) -or [double]::IsInfinity($LoraClipStrength) -or $LoraClipStrength -lt -100 -or $LoraClipStrength -gt 100) {
            throw 'LoRA CLIP strength must be between -100 and 100.'
        }
    }

    $workflow = [ordered]@{
        '4' = [ordered]@{
            class_type = 'CheckpointLoaderSimple'
            inputs = [ordered]@{
                ckpt_name = $CheckpointName
            }
        }
    }

    $modelRef = @('4', 0)
    $clipRef = @('4', 1)
    if (-not [string]::IsNullOrWhiteSpace($LoraName)) {
        $workflow['10'] = [ordered]@{
            class_type = 'LoraLoader'
            inputs = [ordered]@{
                lora_name = $LoraName
                strength_model = $LoraModelStrength
                strength_clip = $LoraClipStrength
                model = @('4', 0)
                clip = @('4', 1)
            }
        }
        $modelRef = @('10', 0)
        $clipRef = @('10', 1)
    }

    $workflow['6'] = [ordered]@{
        class_type = 'CLIPTextEncode'
        inputs = [ordered]@{
            text = $Prompt
            clip = $clipRef
        }
    }
    $workflow['7'] = [ordered]@{
        class_type = 'CLIPTextEncode'
        inputs = [ordered]@{
            text = $NegativePrompt
            clip = $clipRef
        }
    }
    $workflow['5'] = [ordered]@{
        class_type = 'EmptyLatentImage'
        inputs = [ordered]@{
            width = $Width
            height = $Height
            batch_size = 1
        }
    }
    $workflow['3'] = [ordered]@{
        class_type = 'KSampler'
        inputs = [ordered]@{
            seed = $Seed
            steps = $Steps
            cfg = $Cfg
            sampler_name = $SamplerName
            scheduler = $Scheduler
            denoise = 1.0
            model = $modelRef
            positive = @('6', 0)
            negative = @('7', 0)
            latent_image = @('5', 0)
        }
    }
    $workflow['8'] = [ordered]@{
        class_type = 'VAEDecode'
        inputs = [ordered]@{
            samples = @('3', 0)
            vae = @('4', 2)
        }
    }
    $workflow['9'] = [ordered]@{
        class_type = 'SaveImage'
        inputs = [ordered]@{
            filename_prefix = $FilenamePrefix
            images = @('8', 0)
        }
    }

    return $workflow
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

function Resolve-StableAmdGeneratedImagePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowNull()]
        [psobject]$HistoryEntry,

        [Parameter(Mandatory = $true)]
        [string]$OutputRoot,

        [Parameter(Mandatory = $true)]
        [string]$FilenamePrefix,

        [string]$SaveNodeId = '9'
    )

    if ([string]::IsNullOrWhiteSpace($OutputRoot)) { throw 'OutputRoot cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($FilenamePrefix)) { throw 'FilenamePrefix cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($SaveNodeId)) { throw 'SaveNodeId cannot be empty.' }

    $rootFull = [IO.Path]::GetFullPath($OutputRoot)
    $rootWithSeparator = $rootFull.TrimEnd([char[]]@('\', '/')) + [IO.Path]::DirectorySeparatorChar

    if ($null -ne $HistoryEntry) {
        $outputsProperty = $HistoryEntry.PSObject.Properties['outputs']
        if ($null -ne $outputsProperty -and $null -ne $outputsProperty.Value) {
            $saveProperty = $outputsProperty.Value.PSObject.Properties[$SaveNodeId]
            if ($null -ne $saveProperty -and $null -ne $saveProperty.Value) {
                $imagesProperty = $saveProperty.Value.PSObject.Properties['images']
                $images = if ($null -ne $imagesProperty -and $null -ne $imagesProperty.Value) { @($imagesProperty.Value) } else { @() }
                foreach ($imageInfo in $images) {
                    if ($null -eq $imageInfo) { continue }
                    $filenameProperty = $imageInfo.PSObject.Properties['filename']
                    if ($null -eq $filenameProperty -or [string]::IsNullOrWhiteSpace([string]$filenameProperty.Value)) { continue }

                    $candidateRoot = $rootFull
                    $subfolderProperty = $imageInfo.PSObject.Properties['subfolder']
                    if ($null -ne $subfolderProperty -and -not [string]::IsNullOrWhiteSpace([string]$subfolderProperty.Value)) {
                        $candidateRoot = Join-Path $candidateRoot ([string]$subfolderProperty.Value)
                    }

                    try {
                        $candidate = [IO.Path]::GetFullPath((Join-Path $candidateRoot ([string]$filenameProperty.Value)))
                    }
                    catch {
                        continue
                    }

                    if (-not $candidate.StartsWith($rootWithSeparator, [StringComparison]::OrdinalIgnoreCase)) { continue }
                    if (Test-Path $candidate -PathType Leaf) { return $candidate }
                }
            }
        }
    }

    if (-not (Test-Path $rootFull -PathType Container)) { return $null }
    $pattern = $FilenamePrefix + '*.png'
    $fallback = Get-ChildItem -Path $rootFull -Filter $pattern -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if ($null -eq $fallback) { return $null }

    $fallbackFull = [IO.Path]::GetFullPath($fallback.FullName)
    if (-not $fallbackFull.StartsWith($rootWithSeparator, [StringComparison]::OrdinalIgnoreCase)) { return $null }
    return $fallbackFull
}

function New-StableAmdRandomSeed {
    [CmdletBinding()]
    param()

    $bytes = New-Object byte[] 8
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) }
    finally { $rng.Dispose() }

    $bytes[7] = $bytes[7] -band 0x7F
    return [BitConverter]::ToInt64($bytes, 0)
}

function Save-StableAmdGenerationRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$HistoryRoot,

        [Parameter(Mandatory = $true)]
        [psobject]$Record
    )

    if ([string]::IsNullOrWhiteSpace($HistoryRoot)) { throw 'HistoryRoot cannot be empty.' }
    if ($null -eq $Record) { throw 'Record cannot be null.' }

    New-Item -ItemType Directory -Path $HistoryRoot -Force | Out-Null

    $createdAtText = [string]$Record.createdAtUtc
    $createdAt = [DateTimeOffset]::UtcNow
    if (-not [string]::IsNullOrWhiteSpace($createdAtText)) {
        $parsed = [DateTimeOffset]::MinValue
        if ([DateTimeOffset]::TryParse($createdAtText, [ref]$parsed)) {
            $createdAt = $parsed.ToUniversalTime()
        }
    }

    $promptId = [string]$Record.promptId
    if ([string]::IsNullOrWhiteSpace($promptId)) {
        $promptId = [guid]::NewGuid().ToString('N')
    }
    $safePromptId = [regex]::Replace($promptId, '[^A-Za-z0-9._-]', '_')
    if ($safePromptId.Length -gt 64) { $safePromptId = $safePromptId.Substring(0, 64) }

    $baseName = '{0}_{1}' -f $createdAt.ToString('yyyyMMddTHHmmssfffZ'), $safePromptId
    $destination = Join-Path $HistoryRoot ($baseName + '.json')
    $counter = 1
    while (Test-Path $destination) {
        $destination = Join-Path $HistoryRoot ('{0}_{1}.json' -f $baseName, $counter)
        $counter++
    }

    $temporary = $destination + '.tmp-' + [guid]::NewGuid().ToString('N')
    try {
        $Record | ConvertTo-Json -Depth 20 | Set-Content -Path $temporary -Encoding UTF8
        Move-Item -Path $temporary -Destination $destination -Force
    }
    finally {
        Remove-Item -Path $temporary -Force -ErrorAction SilentlyContinue
    }

    return [IO.Path]::GetFullPath($destination)
}

function Get-StableAmdGenerationHistory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$HistoryRoot
    )

    if ([string]::IsNullOrWhiteSpace($HistoryRoot) -or -not (Test-Path $HistoryRoot -PathType Container)) {
        return @()
    }

    $records = @()
    foreach ($file in @(Get-ChildItem -Path $HistoryRoot -Filter '*.json' -File -ErrorAction SilentlyContinue)) {
        try {
            $record = Get-Content -Path $file.FullName -Raw | ConvertFrom-Json
            if ($null -eq $record) { continue }

            $createdAt = [DateTimeOffset]::MinValue
            $createdAtText = [string]$record.createdAtUtc
            if (-not [string]::IsNullOrWhiteSpace($createdAtText)) {
                $parsed = [DateTimeOffset]::MinValue
                if ([DateTimeOffset]::TryParse($createdAtText, [ref]$parsed)) {
                    $createdAt = $parsed.ToUniversalTime()
                }
            }

            $records += [pscustomobject]@{
                SortCreatedAtUtc = $createdAt
                Record = $record
            }
        }
        catch {
            continue
        }
    }

    return @($records | Sort-Object SortCreatedAtUtc -Descending | ForEach-Object { $_.Record })
}

Export-ModuleMember -Function New-StableAmdSdxlWorkflow, Resolve-StableAmdComfyCheckpointName, Resolve-StableAmdGeneratedImagePath, New-StableAmdRandomSeed, Save-StableAmdGenerationRecord, Get-StableAmdGenerationHistory
