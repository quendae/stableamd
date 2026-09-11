[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Prompt,

    [string]$NegativePrompt = 'low quality, blurry, distorted, artifacts, watermark, text',
    [string]$ModelId = '',
    [string]$ModelPath = '',
    [int]$Width = 0,
    [int]$Height = 0,
    [int]$Steps = 0,
    [double]$Cfg = 0,
    [long]$Seed = -1,
    [string]$SamplerName = '',
    [string]$Scheduler = '',
    [int]$GenerationTimeoutSeconds = 900,
    [string]$RepoRoot = '',
    [switch]$StartBackendIfNeeded
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Models.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Generation.psm1') -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$config = Read-StableAmdConfig -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths

$statusScript = Join-Path $PSScriptRoot 'Get-StableAMDStatus.ps1'
$startScript = Join-Path $PSScriptRoot 'Start-StableAMD.ps1'
$listModelsScript = Join-Path $PSScriptRoot 'List-Models.ps1'

$status = & $statusScript -RepoRoot $RepoRoot
if ($status.Status -ne 'running' -or -not $status.Healthy) {
    if (-not $StartBackendIfNeeded) {
        throw "StableAMD backend is '$($status.Status)'. Start it first with Start-StableAMD.ps1 or use -StartBackendIfNeeded."
    }

    if ($status.Status -eq 'degraded') {
        $status = & $startScript -RepoRoot $RepoRoot -ForceRestart
    }
    else {
        $status = & $startScript -RepoRoot $RepoRoot
    }
}
if ($null -eq $status -or -not $status.Healthy) {
    throw 'StableAMD backend could not be made healthy.'
}

if (-not [string]::IsNullOrWhiteSpace($ModelId) -and -not [string]::IsNullOrWhiteSpace($ModelPath)) {
    throw 'Specify ModelId or ModelPath, not both.'
}

$registry = Read-StableAmdModelRegistry -Path $paths.ModelsRegistryPath
if (@($registry.models).Count -eq 0) {
    & $listModelsScript -RepoRoot $RepoRoot | Out-Null
    $registry = Read-StableAmdModelRegistry -Path $paths.ModelsRegistryPath
}

$model = $null
if (-not [string]::IsNullOrWhiteSpace($ModelId)) {
    $model = @($registry.models) | Where-Object { [string]$_.id -eq $ModelId } | Select-Object -First 1
    if ($null -eq $model) {
        throw "StableAMD model registry does not contain ModelId '$ModelId'."
    }
}
elseif (-not [string]::IsNullOrWhiteSpace($ModelPath)) {
    $resolvedRequestedPath = if ([IO.Path]::IsPathRooted($ModelPath)) { [IO.Path]::GetFullPath($ModelPath) } else { Resolve-StableAmdPath -Path $ModelPath -RepoRoot $RepoRoot }
    $model = @($registry.models) | Where-Object {
        -not [string]::IsNullOrWhiteSpace([string]$_.path) -and
        [IO.Path]::GetFullPath([string]$_.path).Equals($resolvedRequestedPath, [StringComparison]::OrdinalIgnoreCase)
    } | Select-Object -First 1
    if ($null -eq $model) {
        throw "StableAMD model registry does not contain '$resolvedRequestedPath'. Run List-Models.ps1 or Install-Model.ps1 first."
    }
}
else {
    $model = @($registry.models) | Where-Object { [string]$_.family -eq 'sdxl' } | Select-Object -First 1
    if ($null -eq $model) {
        throw 'No registered SDXL model is available. Install or discover a model first.'
    }
}

$selectedModelPath = [IO.Path]::GetFullPath([string]$model.path)
if (-not (Test-Path $selectedModelPath -PathType Leaf)) {
    throw "Selected model no longer exists: '$selectedModelPath'."
}
if ([string]$model.family -ne 'sdxl') {
    throw "StableAMD v0.1 txt2img currently supports SDXL models only. Selected model family: '$($model.family)'."
}

$resolvedWidth = if ($Width -gt 0) { $Width } else { [int]$config.generation.defaultWidth }
$resolvedHeight = if ($Height -gt 0) { $Height } else { [int]$config.generation.defaultHeight }
$resolvedSteps = if ($Steps -gt 0) { $Steps } else { [int]$config.generation.defaultSteps }
$resolvedCfg = if ($Cfg -gt 0) { $Cfg } else { [double]$config.generation.defaultCfg }
$resolvedSampler = if (-not [string]::IsNullOrWhiteSpace($SamplerName)) { $SamplerName } else { [string]$config.generation.defaultSampler }
$resolvedScheduler = if (-not [string]::IsNullOrWhiteSpace($Scheduler)) { $Scheduler } else { [string]$config.generation.defaultScheduler }
$resolvedSeed = if ($Seed -ge 0) { $Seed } else { New-StableAmdRandomSeed }

$baseUrl = [string]$status.Url
if ([string]::IsNullOrWhiteSpace($baseUrl)) { throw 'Managed backend status did not include a URL.' }
if (-not $baseUrl.EndsWith('/')) { $baseUrl += '/' }

$objectInfoUrl = "${baseUrl}object_info/CheckpointLoaderSimple"
$loaderInfo = Invoke-RestMethod -Uri $objectInfoUrl -Method Get -TimeoutSec 30
$checkpointNode = $loaderInfo.PSObject.Properties['CheckpointLoaderSimple']
if ($null -eq $checkpointNode) {
    throw 'ComfyUI object_info did not return CheckpointLoaderSimple metadata.'
}
$checkpointChoices = @($checkpointNode.Value.input.required.ckpt_name[0])
$checkpointName = Resolve-StableAmdComfyCheckpointName -ModelPath $selectedModelPath -CheckpointChoices $checkpointChoices
if ([string]::IsNullOrWhiteSpace([string]$checkpointName)) {
    throw "ComfyUI does not expose the selected model '$selectedModelPath'. Restart StableAMD after changing model roots."
}

$workflow = New-StableAmdSdxlWorkflow `
    -CheckpointName $checkpointName `
    -Prompt $Prompt `
    -NegativePrompt $NegativePrompt `
    -Width $resolvedWidth `
    -Height $resolvedHeight `
    -Steps $resolvedSteps `
    -Cfg $resolvedCfg `
    -Seed $resolvedSeed `
    -SamplerName $resolvedSampler `
    -Scheduler $resolvedScheduler `
    -FilenamePrefix 'StableAMD_SDXL'

# The normal product flow always builds this fixed SDXL graph internally:
# CheckpointLoaderSimple -> CLIPTextEncode -> KSampler -> VAEDecode -> SaveImage.
$clientId = [guid]::NewGuid().ToString('N')
$payload = [ordered]@{
    prompt = $workflow
    client_id = $clientId
}
$payloadJson = $payload | ConvertTo-Json -Depth 20 -Compress

$watch = [Diagnostics.Stopwatch]::StartNew()
$queueResponse = Invoke-RestMethod -Uri "${baseUrl}prompt" -Method Post -ContentType 'application/json' -Body $payloadJson -TimeoutSec 60
$promptId = [string]$queueResponse.prompt_id
if ([string]::IsNullOrWhiteSpace($promptId)) {
    throw "ComfyUI /prompt did not return a prompt_id. Response: $($queueResponse | ConvertTo-Json -Depth 8 -Compress)"
}
$nodeErrorsProperty = $queueResponse.PSObject.Properties['node_errors']
if ($null -ne $nodeErrorsProperty -and $null -ne $nodeErrorsProperty.Value -and $nodeErrorsProperty.Value.PSObject.Properties.Count -gt 0) {
    throw "ComfyUI rejected the StableAMD workflow: $($nodeErrorsProperty.Value | ConvertTo-Json -Depth 12 -Compress)"
}

$deadline = (Get-Date).AddSeconds([Math]::Max(5, $GenerationTimeoutSeconds))
$historyEntry = $null
while ((Get-Date) -lt $deadline) {
    try {
        $history = Invoke-RestMethod -Uri "${baseUrl}history/$promptId" -Method Get -TimeoutSec 10
        $historyProperty = $history.PSObject.Properties[$promptId]
        if ($null -ne $historyProperty) {
            $candidate = $historyProperty.Value
            $statusProperty = $candidate.PSObject.Properties['status']
            if ($null -ne $statusProperty) {
                $statusStrProperty = $statusProperty.Value.PSObject.Properties['status_str']
                $statusStr = if ($null -ne $statusStrProperty) { [string]$statusStrProperty.Value } else { '' }
                if ($statusStr -eq 'error') {
                    $statusJson = $statusProperty.Value | ConvertTo-Json -Depth 16 -Compress
                    throw "ComfyUI reported an SDXL execution error for prompt ${promptId}: $statusJson"
                }
                $completedProperty = $statusProperty.Value.PSObject.Properties['completed']
                $completed = ($null -ne $completedProperty -and [bool]$completedProperty.Value)
                if ($completed -or $statusStr -eq 'success') {
                    $historyEntry = $candidate
                    break
                }
            }
        }
    }
    catch {
        if ($_.Exception.Message -match '^ComfyUI reported an SDXL execution error') { throw }
    }
    Start-Sleep -Seconds 1
}
$watch.Stop()

if ($null -eq $historyEntry) {
    throw "SDXL generation did not complete within $GenerationTimeoutSeconds seconds. Prompt ID: $promptId"
}

$outputsProperty = $historyEntry.PSObject.Properties['outputs']
if ($null -eq $outputsProperty) { throw "ComfyUI history for '$promptId' has no outputs." }
$saveProperty = $outputsProperty.Value.PSObject.Properties['9']
if ($null -eq $saveProperty) { throw "ComfyUI history for '$promptId' has no SaveImage output." }
$imagesProperty = $saveProperty.Value.PSObject.Properties['images']
$images = if ($null -ne $imagesProperty) { @($imagesProperty.Value) } else { @() }
if ($images.Count -lt 1) { throw "SaveImage returned no image metadata for prompt '$promptId'." }

$imageInfo = $images[0]
$imagePath = $paths.OutputRoot
$subfolderProperty = $imageInfo.PSObject.Properties['subfolder']
if ($null -ne $subfolderProperty -and -not [string]::IsNullOrWhiteSpace([string]$subfolderProperty.Value)) {
    $imagePath = Join-Path $imagePath ([string]$subfolderProperty.Value)
}
$filenameProperty = $imageInfo.PSObject.Properties['filename']
if ($null -eq $filenameProperty -or [string]::IsNullOrWhiteSpace([string]$filenameProperty.Value)) {
    throw "SaveImage returned an empty filename for prompt '$promptId'."
}
$imagePath = Join-Path $imagePath ([string]$filenameProperty.Value)
if (-not (Test-Path $imagePath -PathType Leaf)) {
    throw "ComfyUI reported generated image '$imagePath', but the file does not exist."
}
$imagePath = [IO.Path]::GetFullPath($imagePath)
$generationSeconds = [Math]::Round($watch.Elapsed.TotalSeconds, 3)
$createdAtUtc = [DateTime]::UtcNow.ToString('o')

$historyRecord = [pscustomobject]@{
    schemaVersion = 1
    createdAtUtc = $createdAtUtc
    promptId = $promptId
    prompt = $Prompt
    negativePrompt = $NegativePrompt
    modelId = [string]$model.id
    modelName = [string]$model.name
    modelPath = $selectedModelPath
    checkpointName = $checkpointName
    width = $resolvedWidth
    height = $resolvedHeight
    steps = $resolvedSteps
    cfg = $resolvedCfg
    seed = $resolvedSeed
    sampler = $resolvedSampler
    scheduler = $resolvedScheduler
    generationSeconds = $generationSeconds
    imagePath = $imagePath
    backendUrl = $baseUrl
}
$historyPath = Save-StableAmdGenerationRecord -HistoryRoot $paths.HistoryRoot -Record $historyRecord

return [pscustomobject]@{
    PromptId = $promptId
    Prompt = $Prompt
    NegativePrompt = $NegativePrompt
    ModelId = [string]$model.id
    ModelName = [string]$model.name
    ModelPath = $selectedModelPath
    CheckpointName = $checkpointName
    Width = $resolvedWidth
    Height = $resolvedHeight
    Steps = $resolvedSteps
    Cfg = $resolvedCfg
    Seed = $resolvedSeed
    Sampler = $resolvedSampler
    Scheduler = $resolvedScheduler
    GenerationSeconds = $generationSeconds
    ImagePath = $imagePath
    HistoryPath = $historyPath
    BackendUrl = $baseUrl
}
