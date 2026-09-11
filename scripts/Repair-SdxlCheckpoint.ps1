[CmdletBinding()]
param(
    [string]$RuntimeRoot = '',
    [switch]$Fresh
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'The SDXL checkpoint repair helper is Windows-only.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
    $RuntimeRoot = Join-Path $repoRoot '.runtime'
}

$checkpointPath = Join-Path $RuntimeRoot 'SwarmUI/Models/Stable-Diffusion/OfficialStableDiffusion/sd_xl_base_1.0.safetensors'
$checkpointDirectory = Split-Path -Parent $checkpointPath
$partialPath = "$checkpointPath.partial"
$expectedSha256 = '31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b'
$downloadUrl = 'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors?download=true'

New-Item -ItemType Directory -Path $checkpointDirectory -Force | Out-Null

$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if ($null -eq $curl) {
    throw 'curl.exe is required for the verified checkpoint repair. It is included with current Windows 10/11 builds.'
}

function Get-SdxlSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Invoke-SdxlDownload {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][bool]$Resume
    )

    $arguments = @(
        '--location',
        '--fail',
        '--retry', '5',
        '--retry-delay', '2',
        '--retry-all-errors',
        '--progress-bar'
    )
    if ($Resume) {
        $arguments += @('--continue-at', '-')
    }
    $arguments += @('--output', $Destination, $downloadUrl)

    $oldEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $curl.Source @arguments 2>&1 | ForEach-Object { Write-Host $_ }
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $oldEap
    }

    return $exitCode
}

Write-Host ''
Write-Host 'StableAMD SDXL checkpoint repair' -ForegroundColor Cyan
Write-Host "Target: $checkpointPath"
Write-Host "Expected SHA256: $expectedSha256"

if (Test-Path $checkpointPath) {
    $existingLength = (Get-Item $checkpointPath).Length
    Write-Host "Existing checkpoint: $existingLength bytes"
    Write-Host 'Checking existing SHA256...' -ForegroundColor Cyan
    $existingHash = Get-SdxlSha256 -Path $checkpointPath
    if ($existingHash -eq $expectedSha256) {
        Write-Host 'Checkpoint already matches the official SHA256. No repair is needed.' -ForegroundColor Green
        return [pscustomobject]@{
            Path = $checkpointPath
            SizeBytes = $existingLength
            SHA256 = $existingHash
            Downloaded = $false
            Resumed = $false
        }
    }
    Write-Warning "Existing checkpoint SHA256 does not match the official file: $existingHash"
}

if ($Fresh) {
    if (Test-Path $checkpointPath) { Remove-Item -Path $checkpointPath -Force }
    if (Test-Path $partialPath) { Remove-Item -Path $partialPath -Force }
}
elseif ((Test-Path $checkpointPath) -and -not (Test-Path $partialPath)) {
    # The observed safetensors failure is an EOF/truncation error. Reuse the
    # bytes already downloaded and ask curl to continue from that offset first.
    Move-Item -Path $checkpointPath -Destination $partialPath
}
elseif (Test-Path $checkpointPath) {
    # A previous partial repair already exists. Avoid keeping two known-bad
    # copies of the same multi-GB model.
    Remove-Item -Path $checkpointPath -Force
}

$resume = (Test-Path $partialPath) -and ((Get-Item $partialPath).Length -gt 0) -and -not $Fresh
if ($resume) {
    Write-Host "Attempting to resume the incomplete checkpoint from $((Get-Item $partialPath).Length) bytes..." -ForegroundColor Cyan
}
else {
    Write-Host 'Downloading a fresh SDXL checkpoint...' -ForegroundColor Cyan
}

$downloadExit = Invoke-SdxlDownload -Destination $partialPath -Resume $resume
$needsFreshRetry = $downloadExit -ne 0

if (-not $needsFreshRetry) {
    Write-Host 'Verifying downloaded SHA256...' -ForegroundColor Cyan
    $downloadedHash = Get-SdxlSha256 -Path $partialPath
    if ($downloadedHash -ne $expectedSha256) {
        Write-Warning "The resumed/downloaded file failed SHA256 verification: $downloadedHash"
        $needsFreshRetry = $true
    }
}

if ($needsFreshRetry -and $resume) {
    Write-Warning 'Resume did not produce the official checkpoint. Retrying once from a clean file.'
    if (Test-Path $partialPath) { Remove-Item -Path $partialPath -Force }
    $downloadExit = Invoke-SdxlDownload -Destination $partialPath -Resume $false
    if ($downloadExit -ne 0) {
        throw "Fresh SDXL download failed with curl exit code $downloadExit. Partial file: '$partialPath'."
    }
    Write-Host 'Verifying fresh download SHA256...' -ForegroundColor Cyan
    $downloadedHash = Get-SdxlSha256 -Path $partialPath
}
elseif ($needsFreshRetry) {
    throw "SDXL download failed with curl exit code $downloadExit. Partial file: '$partialPath'."
}

if ($downloadedHash -ne $expectedSha256) {
    throw "Downloaded SDXL checkpoint failed SHA256 verification. Expected $expectedSha256, got $downloadedHash. Partial file: '$partialPath'."
}

Move-Item -Path $partialPath -Destination $checkpointPath -Force
$finalLength = (Get-Item $checkpointPath).Length

Write-Host ''
Write-Host 'SDXL CHECKPOINT REPAIR PASSED.' -ForegroundColor Green
Write-Host "File: $checkpointPath"
Write-Host "Size: $finalLength bytes"
Write-Host "SHA256: $downloadedHash"
Write-Host 'You can now rerun scripts/Test-TheRockSdxl.ps1.' -ForegroundColor Cyan

return [pscustomobject]@{
    Path = $checkpointPath
    SizeBytes = $finalLength
    SHA256 = $downloadedHash
    Downloaded = $true
    Resumed = $resume
}
