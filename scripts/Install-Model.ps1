[CmdletBinding(DefaultParameterSetName = 'Local')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Local')]
    [string]$LocalPath,

    [Parameter(Mandatory = $true, ParameterSetName = 'HuggingFace')]
    [string]$HuggingFaceRepository,

    [Parameter(Mandatory = $true, ParameterSetName = 'HuggingFace')]
    [string]$HuggingFaceFilename,

    [Parameter(ParameterSetName = 'HuggingFace')]
    [string]$Revision = 'main',

    [Parameter(ParameterSetName = 'HuggingFace')]
    [string]$HuggingFaceToken = '',

    [string]$ExpectedSha256 = '',
    [string]$RepoRoot = '',

    [Parameter(ParameterSetName = 'Local')]
    [switch]$MoveLocal
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'StableAMD v0.1 model installation is Windows-only.'
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Models.psm1') -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths
$validateScript = Join-Path $PSScriptRoot 'Validate-Model.ps1'
if (-not (Test-Path $validateScript -PathType Leaf)) {
    throw "StableAMD model validator is missing: '$validateScript'."
}

if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and $ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
    throw 'ExpectedSha256 must contain exactly 64 hexadecimal characters.'
}

function Register-StableAmdInstalledModel {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][psobject]$SourceMetadata,
        [string]$KnownSha256 = ''
    )

    $validation = & $validateScript -ModelPath $Path -RepoRoot $RepoRoot -IncludeSha256
    if ($null -eq $validation -or -not $validation.Valid) {
        throw "Installed checkpoint failed safetensors validation: '$Path'."
    }

    $file = Get-Item -Path $Path
    $sha256 = if (-not [string]::IsNullOrWhiteSpace($KnownSha256)) { $KnownSha256.ToLowerInvariant() } else { [string]$validation.Sha256 }
    $entry = [pscustomobject]@{
        id = Get-StableAmdModelId -Path $file.FullName
        name = $file.Name
        path = [IO.Path]::GetFullPath($file.FullName)
        family = [string]$validation.Family
        sizeBytes = [Int64]$file.Length
        lastWriteTimeUtc = $file.LastWriteTimeUtc.ToString('o')
        validation = 'valid'
        sha256 = $sha256
        source = $Source
        sourceMetadata = $SourceMetadata
    }

    $registry = Read-StableAmdModelRegistry -Path $paths.ModelsRegistryPath
    $registry = Upsert-StableAmdModelRegistryEntry -Registry $registry -Entry $entry
    Write-StableAmdModelRegistry -Path $paths.ModelsRegistryPath -Registry $registry
    return $entry
}

if ($PSCmdlet.ParameterSetName -eq 'Local') {
    $sourcePath = if ([IO.Path]::IsPathRooted($LocalPath)) {
        [IO.Path]::GetFullPath($LocalPath)
    }
    else {
        Resolve-StableAmdPath -Path $LocalPath -RepoRoot $RepoRoot
    }

    if (-not (Test-Path $sourcePath -PathType Leaf)) {
        throw "Local model file was not found: '$sourcePath'."
    }
    if ([IO.Path]::GetExtension($sourcePath) -ine '.safetensors') {
        throw "StableAMD v0.1 imports .safetensors checkpoints only: '$sourcePath'."
    }

    # Validate the original before copying/moving so a failed import never
    # destroys the user's only source file.
    $sourceValidation = & $validateScript -ModelPath $sourcePath -RepoRoot $RepoRoot -IncludeSha256
    if ($null -eq $sourceValidation -or -not $sourceValidation.Valid) {
        throw "Local model is not a valid safetensors checkpoint: '$sourcePath'."
    }
    if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and -not (Test-StableAmdModelSha256 -Path $sourcePath -ExpectedSha256 $ExpectedSha256)) {
        throw "Local model SHA256 does not match ExpectedSha256: '$sourcePath'."
    }

    $destination = Get-StableAmdModelDestinationPath -DestinationRoot $paths.CheckpointsRoot -FileName ([IO.Path]::GetFileName($sourcePath))
    if ($MoveLocal) {
        Move-Item -Path $sourcePath -Destination $destination
    }
    else {
        Copy-Item -Path $sourcePath -Destination $destination
    }

    try {
        return Register-StableAmdInstalledModel `
            -Path $destination `
            -Source 'local' `
            -KnownSha256 ([string]$sourceValidation.Sha256) `
            -SourceMetadata ([pscustomobject]@{
                originalPath = $sourcePath
                operation = if ($MoveLocal) { 'move' } else { 'copy' }
                importedAtUtc = [DateTime]::UtcNow.ToString('o')
            })
    }
    catch {
        if (Test-Path $destination) {
            if ($MoveLocal -and -not (Test-Path $sourcePath)) {
                Move-Item -Path $destination -Destination $sourcePath -Force -ErrorAction SilentlyContinue
            }
            else {
                Remove-Item -Path $destination -Force -ErrorAction SilentlyContinue
            }
        }
        throw
    }
}

$curl = Get-Command curl.exe -ErrorAction SilentlyContinue
if ($null -eq $curl) {
    throw 'curl.exe is required for resumable Hugging Face downloads.'
}

$url = Resolve-StableAmdHuggingFaceUrl -RepositoryId $HuggingFaceRepository -Filename $HuggingFaceFilename -Revision $Revision
$leafName = [IO.Path]::GetFileName($HuggingFaceFilename.Replace('/', '\'))
if ([IO.Path]::GetExtension($leafName) -ine '.safetensors') {
    throw "StableAMD v0.1 downloads .safetensors checkpoints only: '$HuggingFaceFilename'."
}

$canonicalDestination = [IO.Path]::GetFullPath((Join-Path $paths.CheckpointsRoot $leafName))
if (Test-Path $canonicalDestination) {
    $destination = Get-StableAmdModelDestinationPath -DestinationRoot $paths.CheckpointsRoot -FileName $leafName
}
else {
    # Reuse a matching .partial from an interrupted prior attempt. curl's
    # --continue-at sends the appropriate HTTP Range request automatically.
    $destination = $canonicalDestination
}
$partialPath = "$destination.partial"
$resume = (Test-Path $partialPath -PathType Leaf) -and ((Get-Item $partialPath).Length -gt 0)

$curlArgs = @(
    '--location',
    '--fail',
    '--retry', '5',
    '--retry-delay', '2',
    '--retry-all-errors',
    '--progress-bar'
)
if ($resume) {
    $curlArgs += @('--continue-at', '-')
}
if (-not [string]::IsNullOrWhiteSpace($HuggingFaceToken)) {
    $curlArgs += @('--header', "Authorization: Bearer $HuggingFaceToken")
}
$curlArgs += @('--output', $partialPath, $url)

$oldEap = $ErrorActionPreference
try {
    $ErrorActionPreference = 'Continue'
    & $curl.Source @curlArgs 2>&1 | ForEach-Object { Write-Host $_ }
    $downloadExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $oldEap
}

if ($downloadExitCode -ne 0) {
    throw "Hugging Face model download failed with curl exit code $downloadExitCode. Partial file retained at '$partialPath' for resume."
}

if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256) -and -not (Test-StableAmdModelSha256 -Path $partialPath -ExpectedSha256 $ExpectedSha256)) {
    throw "Downloaded model failed SHA256 verification. Partial file retained at '$partialPath'."
}

$partialValidation = & $validateScript -ModelPath $partialPath -RepoRoot $RepoRoot -IncludeSha256
if ($null -eq $partialValidation -or -not $partialValidation.Valid) {
    throw "Downloaded model failed safetensors validation. Partial file retained at '$partialPath'."
}

Move-Item -Path $partialPath -Destination $destination -Force
try {
    return Register-StableAmdInstalledModel `
        -Path $destination `
        -Source 'huggingface' `
        -KnownSha256 ([string]$partialValidation.Sha256) `
        -SourceMetadata ([pscustomobject]@{
            repository = $HuggingFaceRepository
            filename = $HuggingFaceFilename
            revision = $Revision
            url = $url
            resumed = $resume
            importedAtUtc = [DateTime]::UtcNow.ToString('o')
        })
}
catch {
    # The downloaded file is retained when registry/secondary validation fails;
    # it may be large and already passed the primary structural validation.
    throw
}
