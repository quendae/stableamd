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
    [string]$LoraName = '',
    [double]$LoraModelStrength = 1.0,
    [double]$LoraClipStrength = 1.0,
    [string]$LoraStackJson = '',
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
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Workflows.psm1') -Force

function Write-StableAmdProgressEvent {
    param(
        [string]$Stage,
        [string]$Message,
        [object]$Percent = $null,
        [object]$Step = $null,
        [object]$MaxSteps = $null,
        [object]$EtaSeconds = $null,
        [string]$PromptId = '',
        [Diagnostics.Stopwatch]$Stopwatch = $null
    )

    $event = [ordered]@{
        type = 'generation-progress'
        stage = $Stage
        message = $Message
        timestampUtc = [DateTime]::UtcNow.ToString('o')
    }
    if (-not [string]::IsNullOrWhiteSpace($PromptId)) { $event.promptId = $PromptId }
    if ($null -ne $Percent) { $event.percent = [Math]::Max(0, [Math]::Min(100, [double]$Percent)) }
    if ($null -ne $Step) { $event.step = [int]$Step }
    if ($null -ne $MaxSteps) { $event.maxSteps = [int]$MaxSteps }
    if ($null -ne $EtaSeconds) { $event.etaSeconds = [Math]::Max(0, [Math]::Round([double]$EtaSeconds, 1)) }
    if ($null -ne $Stopwatch) { $event.elapsedSeconds = [Math]::Round($Stopwatch.Elapsed.TotalSeconds, 1) }

    $json = $event | ConvertTo-Json -Depth 8 -Compress
    [Console]::Out.WriteLine("STABLEAMD_PROGRESS $json")
    [Console]::Out.Flush()
}

function Open-StableAmdProgressSocket {
    param(
        [string]$BaseUrl,
        [string]$ClientId
    )

    try {
        $wsBase = if ($BaseUrl.StartsWith('https://', [StringComparison]::OrdinalIgnoreCase)) {
            'wss://' + $BaseUrl.Substring(8)
        }
        elseif ($BaseUrl.StartsWith('http://', [StringComparison]::OrdinalIgnoreCase)) {
            'ws://' + $BaseUrl.Substring(7)
        }
        else {
            return $null
        }
        if (-not $wsBase.EndsWith('/')) { $wsBase += '/' }
        $uri = [Uri]("${wsBase}ws?clientId=$ClientId")
        $socket = New-Object System.Net.WebSockets.ClientWebSocket
        $socket.Options.KeepAliveInterval = [TimeSpan]::FromSeconds(20)
        $connectTask = $socket.ConnectAsync($uri, [Threading.CancellationToken]::None)
        if (-not $connectTask.Wait(10000) -or $socket.State -ne [System.Net.WebSockets.WebSocketState]::Open) {
            $socket.Dispose()
            return $null
        }
        return $socket
    }
    catch {
        return $null
    }
}

function ConvertFrom-StableAmdLoraStackJson {
    param([string]$Json)

    if ([string]::IsNullOrWhiteSpace($Json)) { return @() }
    try {
        $parsed = $Json | ConvertFrom-Json
    }
    catch {
        throw "LoraStackJson must contain valid JSON: $($_.Exception.Message)"
    }

    $entries = if ($null -eq $parsed) { @() } else { @($parsed) }
    if ($entries.Count -gt 8) {
        throw 'StableAMD supports at most 8 LoRAs in one stack.'
    }

    $result = @()
    for ($index = 0; $index -lt $entries.Count; $index++) {
        $entry = $entries[$index]
        if ($null -eq $entry) { throw "LoRA stack entry $($index + 1) cannot be null." }
        $nameProperty = $entry.PSObject.Properties['name']
        $name = if ($null -ne $nameProperty) { [string]$nameProperty.Value } else { '' }
        if ([string]::IsNullOrWhiteSpace($name)) {
            throw "LoRA stack entry $($index + 1) must contain a non-empty name."
        }

        $enabledProperty = $entry.PSObject.Properties['enabled']
        $enabled = if ($null -ne $enabledProperty) { [bool]$enabledProperty.Value } else { $true }
        try {
            $modelProperty = $entry.PSObject.Properties['modelStrength']
            $clipProperty = $entry.PSObject.Properties['clipStrength']
            $modelStrength = if ($null -ne $modelProperty) { [double]$modelProperty.Value } else { 1.0 }
            $clipStrength = if ($null -ne $clipProperty) { [double]$clipProperty.Value } else { 1.0 }
        }
        catch {
            throw "LoRA stack entry $($index + 1) strengths must be numeric."
        }
        foreach ($strength in @($modelStrength, $clipStrength)) {
            if ([double]::IsNaN($strength) -or [double]::IsInfinity($strength) -or $strength -lt -100 -or $strength -gt 100) {
                throw "LoRA stack entry $($index + 1) strengths must be between -100 and 100."
            }
        }

        $result += [pscustomobject]@{
            name = $name.Trim()
            modelStrength = $modelStrength
            clipStrength = $clipStrength
            enabled = $enabled
        }
    }
    return @($result)
}

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

    Write-StableAmdProgressEvent -Stage 'backend' -Message 'Starting Radeon compute backend...'
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
if (-not [string]::IsNullOrWhiteSpace($LoraStackJson) -and -not [string]::IsNullOrWhiteSpace($LoraName)) {
    throw 'Specify LoraStackJson or legacy single LoRA parameters, not both.'
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
    throw "StableAMD txt2img currently supports SDXL models only. Selected model family: '$($model.family)'."
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

Write-StableAmdProgressEvent -Stage 'preparing' -Message "Preparing $([IO.Path]::GetFileName($selectedModelPath))..."
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

$requestedLoraStack = @(ConvertFrom-StableAmdLoraStackJson -Json $LoraStackJson)
if ($requestedLoraStack.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace($LoraName)) {
    $requestedLoraStack = @(
        [pscustomobject]@{
            name = $LoraName
            modelStrength = $LoraModelStrength
            clipStrength = $LoraClipStrength
            enabled = $true
        }
    )
}

$resolvedLoraStack = @()
if ($requestedLoraStack.Count -gt 0) {
    $loraInfo = Invoke-RestMethod -Uri "${baseUrl}object_info/LoraLoader" -Method Get -TimeoutSec 30
    $loraNode = $loraInfo.PSObject.Properties['LoraLoader']
    if ($null -eq $loraNode) {
        throw 'ComfyUI object_info did not return LoraLoader metadata.'
    }
    $loraChoices = @($loraNode.Value.input.required.lora_name[0])

    foreach ($entry in $requestedLoraStack) {
        $resolvedName = [string]$entry.name
        if ([bool]$entry.enabled) {
            $nameMatches = @($loraChoices | Where-Object { [string]$_ -ieq [string]$entry.name })
            if ($nameMatches.Count -ne 1) {
                throw "ComfyUI does not expose LoRA '$($entry.name)'. Restart StableAMD after changing LoRA roots."
            }
            $resolvedName = [string]$nameMatches[0]
        }
        $resolvedLoraStack += [pscustomobject]@{
            name = $resolvedName
            modelStrength = [double]$entry.modelStrength
            clipStrength = [double]$entry.clipStrength
            enabled = [bool]$entry.enabled
        }
    }
}

$generationToken = [guid]::NewGuid().ToString('N')
$filenamePrefix = "StableAMD_SDXL_$generationToken"

$workflow = New-StableAmdWorkflow `
    -Family ([string]$model.family) `
    -Mode 'txt2img' `
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
    -FilenamePrefix $filenamePrefix `
    -LoraStack $resolvedLoraStack

# StableAMD owns the graph shape. The v0.3 provider dispatcher now chains an
# ordered LoRA stack while preserving the legacy single-LoRA contract.
$clientId = [guid]::NewGuid().ToString('N')
$payload = [ordered]@{
    prompt = $workflow
    client_id = $clientId
}
$payloadJson = $payload | ConvertTo-Json -Depth 20 -Compress

$progressSocket = Open-StableAmdProgressSocket -BaseUrl $baseUrl -ClientId $clientId
$receiveTask = $null
$receiveBuffer = New-Object byte[] 65536
$textBuilder = New-Object Text.StringBuilder
$samplingWatch = $null
$lastProgressValue = -1

$watch = [Diagnostics.Stopwatch]::StartNew()
Write-StableAmdProgressEvent -Stage 'queued' -Message 'Submitting workflow to ComfyUI...' -Stopwatch $watch
$queueResponse = Invoke-RestMethod -Uri "${baseUrl}prompt" -Method Post -ContentType 'application/json' -Body $payloadJson -TimeoutSec 60
$promptId = [string]$queueResponse.prompt_id
if ([string]::IsNullOrWhiteSpace($promptId)) {
    throw "ComfyUI /prompt did not return a prompt_id. Response: $($queueResponse | ConvertTo-Json -Depth 8 -Compress)"
}
$nodeErrorsProperty = $queueResponse.PSObject.Properties['node_errors']
if ($null -ne $nodeErrorsProperty -and $null -ne $nodeErrorsProperty.Value -and $nodeErrorsProperty.Value.PSObject.Properties.Count -gt 0) {
    throw "ComfyUI rejected the StableAMD workflow: $($nodeErrorsProperty.Value | ConvertTo-Json -Depth 12 -Compress)"
}
Write-StableAmdProgressEvent -Stage 'queued' -Message "Queued as $promptId" -PromptId $promptId -Stopwatch $watch

$nodeStages = @{
    '4' = @('loading-model', 'Loading checkpoint into GPU memory...')
    '6' = @('encoding', 'Encoding prompt...')
    '7' = @('encoding', 'Encoding negative prompt...')
    '5' = @('latent', 'Preparing latent image...')
    '3' = @('sampling', 'Starting sampler...')
    '8' = @('decoding', 'Decoding image with VAE...')
    '9' = @('saving', 'Saving generated image...')
}
for ($index = 0; $index -lt $resolvedLoraStack.Count; $index++) {
    $entry = $resolvedLoraStack[$index]
    if (-not [bool]$entry.enabled) { continue }
    $nodeId = [string](10 + $index)
    $nodeStages[$nodeId] = @('loading-lora', "Applying LoRA $($index + 1)/$($resolvedLoraStack.Count): $($entry.name)")
}

$deadline = (Get-Date).AddSeconds([Math]::Max(5, $GenerationTimeoutSeconds))
$historyEntry = $null
$nextHistoryPoll = Get-Date
try {
    while ((Get-Date) -lt $deadline) {
        if ($null -ne $progressSocket -and $progressSocket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
            if ($null -eq $receiveTask) {
                try {
                    $segment = New-Object 'System.ArraySegment[byte]' -ArgumentList (,$receiveBuffer)
                    $receiveTask = $progressSocket.ReceiveAsync($segment, [Threading.CancellationToken]::None)
                }
                catch {
                    $receiveTask = $null
                    try { $progressSocket.Abort() } catch { }
                }
            }

            if ($null -ne $receiveTask -and $receiveTask.IsCompleted) {
                try {
                    $receiveResult = $receiveTask.GetAwaiter().GetResult()
                    $receiveTask = $null
                    if ($receiveResult.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Close) {
                        try { $progressSocket.Abort() } catch { }
                    }
                    elseif ($receiveResult.MessageType -eq [System.Net.WebSockets.WebSocketMessageType]::Text) {
                        [void]$textBuilder.Append([Text.Encoding]::UTF8.GetString($receiveBuffer, 0, $receiveResult.Count))
                        if ($receiveResult.EndOfMessage) {
                            $messageText = $textBuilder.ToString()
                            [void]$textBuilder.Clear()
                            try {
                                $event = $messageText | ConvertFrom-Json
                                $eventType = [string]$event.type
                                $eventData = $event.data
                                $eventPromptId = if ($null -ne $eventData -and $null -ne $eventData.PSObject.Properties['prompt_id']) { [string]$eventData.prompt_id } else { '' }
                                if ([string]::IsNullOrWhiteSpace($eventPromptId) -or $eventPromptId -eq $promptId) {
                                    if ($eventType -eq 'executing' -and $null -ne $eventData) {
                                        $node = [string]$eventData.node
                                        if ($nodeStages.ContainsKey($node)) {
                                            $stageInfo = $nodeStages[$node]
                                            Write-StableAmdProgressEvent -Stage $stageInfo[0] -Message $stageInfo[1] -PromptId $promptId -Stopwatch $watch
                                        }
                                    }
                                    elseif ($eventType -eq 'progress' -and $null -ne $eventData) {
                                        $value = [int]$eventData.value
                                        $maxValue = [int]$eventData.max
                                        if ($maxValue -gt 0 -and $value -ne $lastProgressValue) {
                                            if ($null -eq $samplingWatch) { $samplingWatch = [Diagnostics.Stopwatch]::StartNew() }
                                            $lastProgressValue = $value
                                            $percent = [Math]::Round(($value * 100.0) / $maxValue, 1)
                                            $eta = $null
                                            if ($value -gt 0 -and $samplingWatch.Elapsed.TotalSeconds -gt 0) {
                                                $secondsPerStep = $samplingWatch.Elapsed.TotalSeconds / $value
                                                $eta = $secondsPerStep * [Math]::Max(0, $maxValue - $value)
                                            }
                                            $etaText = if ($null -ne $eta) { " · ETA ~$([Math]::Ceiling($eta)) s" } else { '' }
                                            Write-StableAmdProgressEvent -Stage 'sampling' -Message "Sampling $value/$maxValue$etaText" -Percent $percent -Step $value -MaxSteps $maxValue -EtaSeconds $eta -PromptId $promptId -Stopwatch $watch
                                            Write-Progress -Activity 'StableAMD SDXL generation' -Status "Sampling $value/$maxValue$etaText" -PercentComplete ([int][Math]::Round($percent))
                                        }
                                    }
                                    elseif ($eventType -eq 'execution_error') {
                                        $detail = $eventData | ConvertTo-Json -Depth 12 -Compress
                                        throw "ComfyUI reported an SDXL execution error for prompt ${promptId}: $detail"
                                    }
                                }
                            }
                            catch {
                                if ($_.Exception.Message -match '^ComfyUI reported an SDXL execution error') { throw }
                            }
                        }
                    }
                }
                catch {
                    if ($_.Exception.Message -match '^ComfyUI reported an SDXL execution error') { throw }
                    $receiveTask = $null
                    try { $progressSocket.Abort() } catch { }
                }
            }
        }

        if ((Get-Date) -ge $nextHistoryPoll) {
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
            $nextHistoryPoll = (Get-Date).AddSeconds(1)
        }
        Start-Sleep -Milliseconds 50
    }
}
finally {
    Write-Progress -Activity 'StableAMD SDXL generation' -Completed
    if ($null -ne $progressSocket) {
        try { $progressSocket.Abort() } catch { }
        try { $progressSocket.Dispose() } catch { }
    }
}
$watch.Stop()

if ($null -eq $historyEntry) {
    throw "SDXL generation did not complete within $GenerationTimeoutSeconds seconds. Prompt ID: $promptId"
}

Write-StableAmdProgressEvent -Stage 'finalizing' -Message 'Finalizing image and metadata...' -Percent 100 -PromptId $promptId -Stopwatch $watch
$imagePath = Resolve-StableAmdGeneratedImagePath `
    -HistoryEntry $historyEntry `
    -OutputRoot $paths.OutputRoot `
    -FilenamePrefix $filenamePrefix `
    -SaveNodeId '9'
if ([string]::IsNullOrWhiteSpace([string]$imagePath)) {
    $outputsSummary = '{}'
    $outputsProperty = $historyEntry.PSObject.Properties['outputs']
    if ($null -ne $outputsProperty -and $null -ne $outputsProperty.Value) {
        try { $outputsSummary = $outputsProperty.Value | ConvertTo-Json -Depth 8 -Compress } catch { $outputsSummary = '{}' }
    }
    throw "ComfyUI completed prompt '$promptId', but StableAMD could not correlate its generated image. Expected prefix '$filenamePrefix' under '$($paths.OutputRoot)'. History outputs: $outputsSummary"
}

$generationSeconds = [Math]::Round($watch.Elapsed.TotalSeconds, 3)
$createdAtUtc = [DateTime]::UtcNow.ToString('o')
$enabledLoras = @($resolvedLoraStack | Where-Object { [bool]$_.enabled })
$legacyLoraNameMetadata = if ($enabledLoras.Count -eq 1) { [string]$enabledLoras[0].name } else { '' }
$loraModelMetadata = if ($enabledLoras.Count -eq 1) { [double]$enabledLoras[0].modelStrength } else { $null }
$loraClipMetadata = if ($enabledLoras.Count -eq 1) { [double]$enabledLoras[0].clipStrength } else { $null }

$historyRecord = [pscustomobject]@{
    schemaVersion = 3
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
    loraStack = @($resolvedLoraStack)
    loraName = $legacyLoraNameMetadata
    loraModelStrength = $loraModelMetadata
    loraClipStrength = $loraClipMetadata
    generationSeconds = $generationSeconds
    imagePath = $imagePath
    backendUrl = $baseUrl
}
$historyPath = Save-StableAmdGenerationRecord -HistoryRoot $paths.HistoryRoot -Record $historyRecord

Write-StableAmdProgressEvent -Stage 'completed' -Message "Generation complete in $generationSeconds s" -Percent 100 -Step $resolvedSteps -MaxSteps $resolvedSteps -EtaSeconds 0 -PromptId $promptId -Stopwatch $watch

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
    LoraStack = @($resolvedLoraStack)
    LoraName = $legacyLoraNameMetadata
    LoraModelStrength = $loraModelMetadata
    LoraClipStrength = $loraClipMetadata
    GenerationSeconds = $generationSeconds
    ImagePath = $imagePath
    HistoryPath = $historyPath
    BackendUrl = $baseUrl
}
