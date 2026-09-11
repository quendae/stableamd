[CmdletBinding()]
param(
    [string]$RuntimeRoot = '',
    [string]$OutputDirectory = '',
    [int]$Port = 8191,
    [int]$StartupTimeoutSeconds = 240,
    [int]$GenerationTimeoutSeconds = 900,
    [string]$Prompt = 'A cinematic photograph of a red vintage airplane parked on a small grass airfield at golden hour, highly detailed, natural light',
    [long]$Seed = 123456789
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'The TheRock SDXL generation test is Windows-only.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $repoRoot '.runtime'
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot 'diagnostics'
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$swarmRoot = Join-Path $RuntimeRoot 'SwarmUI'
$swarmModelsRoot = Join-Path $swarmRoot 'Models'
$checkpointPath = Join-Path $swarmRoot 'Models/Stable-Diffusion/OfficialStableDiffusion/sd_xl_base_1.0.safetensors'
$comfyRoot = Join-Path $RuntimeRoot 'therock-comfy/ComfyUI'
$comfyMain = Join-Path $comfyRoot 'main.py'
$comfyApiInput = Join-Path $comfyRoot 'comfy_api/input/__init__.py'
$theRockPython = Join-Path $RuntimeRoot 'therock-gfx1030/python_embeded/python.exe'
$comfyRunner = Join-Path $PSScriptRoot 'probes/run_comfy_isolated.py'
$validatorPath = Join-Path $PSScriptRoot 'probes/validate_safetensors.py'
$comfySmoke = Join-Path $PSScriptRoot 'Test-TheRockComfy.ps1'

# The generation gate intentionally reuses the isolated ComfyUI checkout that
# passed Test-TheRockComfy.ps1. If it is absent/incomplete, rebuild it through
# that gate rather than silently creating a different environment here.
if (-not (Test-Path $comfyMain) -or -not (Test-Path $comfyApiInput)) {
    Write-Host 'The isolated ComfyUI checkout is missing or incomplete; rebuilding it through the backend smoke gate first...' -ForegroundColor Yellow
    & $comfySmoke -RuntimeRoot $RuntimeRoot -OutputDirectory $OutputDirectory | Out-Null
}

foreach ($required in @($comfyMain, $comfyApiInput, $theRockPython, $comfyRunner, $validatorPath)) {
    if (-not (Test-Path $required)) {
        throw "Required generation-test component is missing: '$required'."
    }
}
if (-not (Test-Path $checkpointPath)) {
    throw "The SwarmUI SDXL checkpoint was not found at '$checkpointPath'. Finish the SwarmUI model download (sdxl1) before running this gate."
}

# Safetensors exposes all tensor byte ranges in its JSON header. Validate those
# ranges before starting ComfyUI so a truncated multi-GB model fails in seconds
# instead of being queued and then waiting for the generation timeout.
$validatorRaw = @()
$oldEap = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    $validatorRaw = @(& $theRockPython -s $validatorPath $checkpointPath 2>$null | ForEach-Object { [string]$_ })
    $validatorExit = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldEap
}

$validatorJson = $validatorRaw | Where-Object { $_.Trim().StartsWith('{') -and $_.Trim().EndsWith('}') } | Select-Object -Last 1
$checkpointValidation = $null
if ($validatorJson) {
    try { $checkpointValidation = $validatorJson | ConvertFrom-Json } catch { $checkpointValidation = $null }
}
if ($validatorExit -ne 0 -or $null -eq $checkpointValidation -or -not $checkpointValidation.valid) {
    $reason = if ($null -ne $checkpointValidation -and $checkpointValidation.reason) { [string]$checkpointValidation.reason } else { 'validator did not return a valid result' }
    $sizeText = if ($null -ne $checkpointValidation -and $null -ne $checkpointValidation.file_size) { " Local size: $($checkpointValidation.file_size) bytes." } else { '' }
    $missingText = if ($null -ne $checkpointValidation -and $null -ne $checkpointValidation.missing_bytes) { " Missing at least $($checkpointValidation.missing_bytes) bytes for the tensor declared in the header." } else { '' }
    throw "Checkpoint safetensors is incomplete or corrupt: $reason.$sizeText$missingText File: '$checkpointPath'. Re-download this checkpoint before rerunning the SDXL gate."
}
Write-Host "Checkpoint structure valid: $($checkpointValidation.tensor_count) tensors, $($checkpointValidation.file_size) bytes." -ForegroundColor DarkGreen

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$runRoot = Join-Path $RuntimeRoot "therock-sdxl-$stamp"
$imageOutputRoot = Join-Path $runRoot 'output'
$modelConfigPath = Join-Path $runRoot 'extra_model_paths.yaml'
$stdoutPath = Join-Path $OutputDirectory "therock-sdxl-$stamp.stdout.log"
$stderrPath = Join-Path $OutputDirectory "therock-sdxl-$stamp.stderr.log"
$reportPath = Join-Path $OutputDirectory "therock-sdxl-$stamp.json"
New-Item -ItemType Directory -Path $runRoot -Force | Out-Null
New-Item -ItemType Directory -Path $imageOutputRoot -Force | Out-Null

# Point ComfyUI at SwarmUI's existing model library. No multi-gigabyte model is
# copied or hard-linked. Forward slashes keep the YAML path portable on Windows.
$yamlModelRoot = $swarmModelsRoot.Replace('\', '/')
@"
stableamd_swarm:
    base_path: "$yamlModelRoot"
    checkpoints: Stable-Diffusion
"@ | Set-Content -Path $modelConfigPath -Encoding UTF8

$baseUrl = "http://127.0.0.1:$Port"
$statsUrl = "$baseUrl/system_stats"
$objectInfoUrl = "$baseUrl/object_info/CheckpointLoaderSimple"
$promptUrl = "$baseUrl/prompt"
$historyBaseUrl = "$baseUrl/history/"

$process = $null
$oldOverride = [Environment]::GetEnvironmentVariable('HSA_OVERRIDE_GFX_VERSION', 'Process')
$hadOverride = $null -ne $oldOverride
Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue

try {
    Write-Host ''
    Write-Host 'StableAMD TheRock SDXL 1024x1024 generation gate' -ForegroundColor Cyan
    Write-Host "Checkpoint: $checkpointPath"
    Write-Host "ComfyUI:    $baseUrl/"
    Write-Host "Output:     $imageOutputRoot"
    Write-Host 'The checkpoint remains in the SwarmUI model library; no model copy is made.' -ForegroundColor DarkGray

    $arguments = "-s `"$comfyRunner`" `"$comfyRoot`" --listen 127.0.0.1 --port $Port --extra-model-paths-config `"$modelConfigPath`" --output-directory `"$imageOutputRoot`""
    $process = Start-Process `
        -FilePath $theRockPython `
        -ArgumentList $arguments `
        -WorkingDirectory $comfyRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $startupDeadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $stats = $null
    while ((Get-Date) -lt $startupDeadline) {
        if ($process.HasExited) { break }
        try {
            $stats = Invoke-RestMethod -Uri $statsUrl -Method Get -TimeoutSec 5
            if ($null -ne $stats) { break }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    if ($null -eq $stats) {
        Write-Host ''
        Write-Host '===== ComfyUI stderr tail =====' -ForegroundColor DarkCyan
        if (Test-Path $stderrPath) { Get-Content $stderrPath -Tail 120 | ForEach-Object { Write-Host $_ } }
        throw "The isolated ComfyUI server did not become reachable at '$statsUrl'."
    }

    $devices = @($stats.devices)
    $gpuDevice = $devices | Where-Object { [string]$_.name -match 'AMD Radeon RX 6950 XT' } | Select-Object -First 1
    if ($null -eq $gpuDevice) {
        throw 'ComfyUI started, but /system_stats did not report AMD Radeon RX 6950 XT.'
    }
    Write-Host "GPU: $($gpuDevice.name)" -ForegroundColor Green

    # Ask the running ComfyUI instance for its actual checkpoint names rather
    # than guessing whether it uses slash or backslash separators internally.
    $loaderInfo = Invoke-RestMethod -Uri $objectInfoUrl -Method Get -TimeoutSec 30
    $checkpointChoices = @($loaderInfo.CheckpointLoaderSimple.input.required.ckpt_name[0])
    $checkpointName = $checkpointChoices |
        Where-Object { [string]$_ -match '(^|[\\/])sd_xl_base_1\.0\.safetensors$|^sd_xl_base_1\.0\.safetensors$' } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace([string]$checkpointName)) {
        throw "ComfyUI did not expose sd_xl_base_1.0.safetensors through extra_model_paths. Checkpoint choices: $($checkpointChoices -join ', ')"
    }
    Write-Host "Comfy checkpoint name: $checkpointName"

    $width = 1024
    $height = 1024
    $workflow = [ordered]@{
        '4' = [ordered]@{
            class_type = 'CheckpointLoaderSimple'
            inputs = [ordered]@{ ckpt_name = [string]$checkpointName }
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
                text = 'low quality, blurry, distorted, artifacts, watermark, text'
                clip = @('4', 1)
            }
        }
        '5' = [ordered]@{
            class_type = 'EmptyLatentImage'
            inputs = [ordered]@{
                width = 1024
                height = 1024
                batch_size = 1
            }
        }
        '3' = [ordered]@{
            class_type = 'KSampler'
            inputs = [ordered]@{
                seed = $Seed
                steps = 20
                cfg = 7.0
                sampler_name = 'euler'
                scheduler = 'normal'
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
                filename_prefix = 'StableAMD_RX6950XT_SDXL'
                images = @('8', 0)
            }
        }
    }

    $clientId = [guid]::NewGuid().ToString('N')
    $payload = [ordered]@{
        prompt = $workflow
        client_id = $clientId
    }
    $payloadJson = $payload | ConvertTo-Json -Depth 20 -Compress

    Write-Host "Submitting SDXL generation: ${width}x${height}, 20 steps, seed $Seed ..." -ForegroundColor Cyan
    $generationWatch = [System.Diagnostics.Stopwatch]::StartNew()
    $queueResponse = Invoke-RestMethod -Uri $promptUrl -Method Post -ContentType 'application/json' -Body $payloadJson -TimeoutSec 60
    $promptId = [string]$queueResponse.prompt_id
    if ([string]::IsNullOrWhiteSpace($promptId)) {
        throw "ComfyUI /prompt did not return a prompt_id. Response: $($queueResponse | ConvertTo-Json -Depth 8 -Compress)"
    }
    if ($queueResponse.node_errors -and $queueResponse.node_errors.PSObject.Properties.Count -gt 0) {
        throw "ComfyUI rejected one or more workflow nodes: $($queueResponse.node_errors | ConvertTo-Json -Depth 12 -Compress)"
    }
    Write-Host "Prompt ID: $promptId"

    $generationDeadline = (Get-Date).AddSeconds($GenerationTimeoutSeconds)
    $historyEntry = $null
    $vramTotal = $null
    $minimumVramFree = $null

    while ((Get-Date) -lt $generationDeadline) {
        if ($process.HasExited) {
            break
        }

        try {
            $liveStats = Invoke-RestMethod -Uri $statsUrl -Method Get -TimeoutSec 5
            $liveDevice = @($liveStats.devices) | Where-Object { [string]$_.name -match 'AMD Radeon RX 6950 XT' } | Select-Object -First 1
            if ($null -ne $liveDevice) {
                if ($null -ne $liveDevice.vram_total) { $vramTotal = [double]$liveDevice.vram_total }
                if ($null -ne $liveDevice.vram_free) {
                    $vramFree = [double]$liveDevice.vram_free
                    if ($null -eq $minimumVramFree -or $vramFree -lt $minimumVramFree) {
                        $minimumVramFree = $vramFree
                    }
                }
            }
        }
        catch { }

        try {
            $history = Invoke-RestMethod -Uri "$historyBaseUrl$promptId" -Method Get -TimeoutSec 10
            $historyProperty = $history.PSObject.Properties[$promptId]
            if ($null -ne $historyProperty) {
                $candidate = $historyProperty.Value
                $candidateStatus = [string]$candidate.status.status_str
                if ($candidateStatus -eq 'error') {
                    $historyEntry = $candidate
                    break
                }
                if ($candidate.status.completed -or $candidateStatus -eq 'success') {
                    $historyEntry = $candidate
                    break
                }
            }
        }
        catch { }

        Start-Sleep -Seconds 1
    }
    $generationWatch.Stop()

    if ($null -eq $historyEntry) {
        Write-Host ''
        Write-Host '===== ComfyUI stderr tail =====' -ForegroundColor DarkCyan
        if (Test-Path $stderrPath) { Get-Content $stderrPath -Tail 160 | ForEach-Object { Write-Host $_ } }
        if ($process.HasExited) {
            throw "ComfyUI exited before SDXL generation completed. Prompt ID: $promptId"
        }
        throw "SDXL generation did not complete within $GenerationTimeoutSeconds seconds. Prompt ID: $promptId"
    }

    $statusString = [string]$historyEntry.status.status_str
    if ($statusString -eq 'error') {
        $statusJson = $historyEntry.status | ConvertTo-Json -Depth 16 -Compress
        throw "ComfyUI reported an SDXL execution error for prompt $promptId: $statusJson"
    }
    if ($statusString -ne 'success') {
        throw "ComfyUI completed the prompt with status '$statusString': $($historyEntry.status | ConvertTo-Json -Depth 12 -Compress)"
    }

    $saveOutput = $historyEntry.outputs.'9'
    $images = @($saveOutput.images)
    if ($images.Count -lt 1) {
        throw "SDXL prompt completed successfully but SaveImage returned no image metadata. Prompt ID: $promptId"
    }

    $imageInfo = $images[0]
    $generatedImagePath = $imageOutputRoot
    if (-not [string]::IsNullOrWhiteSpace([string]$imageInfo.subfolder)) {
        $generatedImagePath = Join-Path $generatedImagePath ([string]$imageInfo.subfolder)
    }
    $generatedImagePath = Join-Path $generatedImagePath ([string]$imageInfo.filename)
    if (-not (Test-Path $generatedImagePath)) {
        throw "SaveImage reported '$($imageInfo.filename)' but the file was not found at '$generatedImagePath'."
    }

    $peakVramUsed = $null
    if ($null -ne $vramTotal -and $null -ne $minimumVramFree) {
        $peakVramUsed = $vramTotal - $minimumVramFree
    }

    $result = [pscustomobject]@{
        CreatedAtUtc = [DateTime]::UtcNow.ToString('o')
        PromptId = $promptId
        Prompt = $Prompt
        Seed = $Seed
        Width = $width
        Height = $height
        Steps = 20
        CheckpointPath = $checkpointPath
        CheckpointName = [string]$checkpointName
        CheckpointValidation = $checkpointValidation
        PythonPath = $theRockPython
        TorchDevice = [string]$gpuDevice.name
        GenerationSeconds = [math]::Round($generationWatch.Elapsed.TotalSeconds, 3)
        VramTotalBytes = $vramTotal
        MinimumVramFreeBytes = $minimumVramFree
        ApproxPeakVramUsedBytes = $peakVramUsed
        ImagePath = $generatedImagePath
        StdoutLog = $stdoutPath
        StderrLog = $stderrPath
        ExtraModelPathsConfig = $modelConfigPath
    }
    $result | ConvertTo-Json -Depth 12 | Set-Content -Path $reportPath -Encoding UTF8

    Write-Host ''
    Write-Host 'THE ROCK SDXL 1024x1024 GENERATION PASSED.' -ForegroundColor Green
    Write-Host "Image: $generatedImagePath"
    Write-Host "Generation time: $($result.GenerationSeconds) s"
    if ($null -ne $peakVramUsed) {
        Write-Host "Approx. peak VRAM used: $([math]::Round($peakVramUsed / 1GB, 2)) GiB / $([math]::Round($vramTotal / 1GB, 2)) GiB"
    }
    Write-Host "Report: $reportPath"

    return $result
}
finally {
    if ($null -ne $process -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        try { $process.WaitForExit() } catch { }
    }
    if ($hadOverride) {
        $env:HSA_OVERRIDE_GFX_VERSION = $oldOverride
    }
    else {
        Remove-Item Env:HSA_OVERRIDE_GFX_VERSION -ErrorAction SilentlyContinue
    }
}
