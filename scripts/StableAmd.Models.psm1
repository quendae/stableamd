Set-StrictMode -Version 2.0

function Get-StableAmdObjectPropertyValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowNull()]
        [psobject]$Object,

        [Parameter(Mandatory = $true)]
        [string]$Name,

        [AllowNull()]
        $Default = $null
    )

    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

function Get-StableAmdModelId {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $normalized = [IO.Path]::GetFullPath($Path).Replace('/', '\').TrimEnd('\').ToLowerInvariant()
    $bytes = [Text.Encoding]::UTF8.GetBytes($normalized)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash($bytes)
    }
    finally {
        $sha.Dispose()
    }
    $hex = -join ($hash | ForEach-Object { $_.ToString('x2') })
    return 'mdl_' + $hex.Substring(0, 16)
}

function Get-StableAmdModelFamily {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $leaf = [IO.Path]::GetFileNameWithoutExtension($Name)
    if ($leaf -match '(?i)(sd[_-]?xl|sdxl|xl(?:[_\-.]|$))') {
        return 'sdxl'
    }
    if ($leaf -match '(?i)(stable[_ -]?diffusion[_ -]?1[._-]?5|sd[_-]?1[._-]?5)') {
        return 'sd15'
    }
    return 'unknown'
}

function Resolve-StableAmdHuggingFaceUrl {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[^/]+/[^/]+$')]
        [string]$RepositoryId,

        [Parameter(Mandatory = $true)]
        [string]$Filename,

        [string]$Revision = 'main'
    )

    if ([string]::IsNullOrWhiteSpace($Filename)) {
        throw 'Hugging Face filename cannot be empty.'
    }
    if ([string]::IsNullOrWhiteSpace($Revision)) {
        throw 'Hugging Face revision cannot be empty.'
    }

    $repoParts = $RepositoryId.Split('/') | ForEach-Object { [Uri]::EscapeDataString($_) }
    $revisionPart = [Uri]::EscapeDataString($Revision)
    $fileParts = $Filename.Replace('\', '/').Split('/') | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { [Uri]::EscapeDataString($_) }
    if (@($fileParts).Count -eq 0) {
        throw 'Hugging Face filename did not contain a usable path segment.'
    }

    return 'https://huggingface.co/{0}/resolve/{1}/{2}?download=true' -f ($repoParts -join '/'), $revisionPart, ($fileParts -join '/')
}

function Get-StableAmdModelDestinationPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$DestinationRoot,

        [Parameter(Mandatory = $true)]
        [string]$FileName
    )

    $leaf = [IO.Path]::GetFileName($FileName)
    if ([string]::IsNullOrWhiteSpace($leaf)) {
        throw 'Model filename cannot be empty.'
    }

    $extension = [IO.Path]::GetExtension($leaf)
    $stem = [IO.Path]::GetFileNameWithoutExtension($leaf)
    $candidate = Join-Path $DestinationRoot $leaf
    $counter = 0
    while ((Test-Path $candidate) -or (Test-Path "$candidate.partial")) {
        $counter++
        $candidate = Join-Path $DestinationRoot ("{0}-{1}{2}" -f $stem, $counter, $extension)
    }
    return [IO.Path]::GetFullPath($candidate)
}

function Test-StableAmdModelSha256 {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [ValidatePattern('^[0-9a-fA-F]{64}$')]
        [string]$ExpectedSha256
    )

    if (-not (Test-Path $Path -PathType Leaf)) {
        return $false
    }
    $actual = (Get-FileHash -Path $Path -Algorithm SHA256).Hash
    return $actual.Equals($ExpectedSha256, [StringComparison]::OrdinalIgnoreCase)
}

function New-StableAmdEmptyModelRegistry {
    [CmdletBinding()]
    param()

    return [pscustomobject]@{
        schemaVersion = 1
        models = @()
    }
}

function Read-StableAmdModelRegistry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return New-StableAmdEmptyModelRegistry
    }

    $registry = Get-Content -Path $Path -Raw | ConvertFrom-Json
    $modelsProperty = $registry.PSObject.Properties['models']
    if ($null -eq $modelsProperty -or $null -eq $modelsProperty.Value) {
        $registry | Add-Member -MemberType NoteProperty -Name models -Value @() -Force
    }
    return $registry
}

function Write-StableAmdModelRegistry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [psobject]$Registry
    )

    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $Registry | ConvertTo-Json -Depth 12 | Set-Content -Path $Path -Encoding UTF8
}

function Find-StableAmdCheckpoints {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Roots
    )

    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $results = New-Object System.Collections.Generic.List[object]

    foreach ($root in $Roots) {
        if ([string]::IsNullOrWhiteSpace($root) -or -not (Test-Path $root -PathType Container)) {
            continue
        }

        foreach ($file in @(Get-ChildItem -Path $root -Filter '*.safetensors' -File -Recurse -ErrorAction SilentlyContinue)) {
            $fullPath = [IO.Path]::GetFullPath($file.FullName)
            if (-not $seen.Add($fullPath)) {
                continue
            }

            $results.Add([pscustomobject]@{
                Id = Get-StableAmdModelId -Path $fullPath
                Name = $file.Name
                Path = $fullPath
                Family = Get-StableAmdModelFamily -Name $file.Name
                SizeBytes = [Int64]$file.Length
                LastWriteTimeUtc = $file.LastWriteTimeUtc.ToString('o')
                Validation = 'unknown'
                Source = 'discovered'
            })
        }
    }

    return @($results | Sort-Object Name, Path)
}

function Merge-StableAmdModelRegistry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$ExistingRegistry,

        [Parameter(Mandatory = $true)]
        [object[]]$DiscoveredModels
    )

    $existingByPath = @{}
    $existingModels = @(Get-StableAmdObjectPropertyValue -Object $ExistingRegistry -Name 'models' -Default @())
    foreach ($model in $existingModels) {
        $modelPath = [string](Get-StableAmdObjectPropertyValue -Object $model -Name 'path' -Default '')
        if (-not [string]::IsNullOrWhiteSpace($modelPath)) {
            $existingByPath[[IO.Path]::GetFullPath($modelPath).ToLowerInvariant()] = $model
        }
    }

    $merged = @()
    foreach ($model in @($DiscoveredModels)) {
        $newPath = [string](Get-StableAmdObjectPropertyValue -Object $model -Name 'Path' -Default '')
        if ([string]::IsNullOrWhiteSpace($newPath)) { continue }
        $key = [IO.Path]::GetFullPath($newPath).ToLowerInvariant()
        $old = $existingByPath[$key]

        $validation = [string](Get-StableAmdObjectPropertyValue -Object $old -Name 'validation' -Default (Get-StableAmdObjectPropertyValue -Object $model -Name 'Validation' -Default 'unknown'))
        $source = [string](Get-StableAmdObjectPropertyValue -Object $old -Name 'source' -Default (Get-StableAmdObjectPropertyValue -Object $model -Name 'Source' -Default 'discovered'))
        $sha256 = Get-StableAmdObjectPropertyValue -Object $old -Name 'sha256' -Default $null
        $sourceMetadata = Get-StableAmdObjectPropertyValue -Object $old -Name 'sourceMetadata' -Default $null

        $merged += [pscustomobject]@{
            id = [string](Get-StableAmdObjectPropertyValue -Object $model -Name 'Id' -Default (Get-StableAmdModelId -Path $newPath))
            name = [string](Get-StableAmdObjectPropertyValue -Object $model -Name 'Name' -Default ([IO.Path]::GetFileName($newPath)))
            path = $newPath
            family = [string](Get-StableAmdObjectPropertyValue -Object $model -Name 'Family' -Default 'unknown')
            sizeBytes = [Int64](Get-StableAmdObjectPropertyValue -Object $model -Name 'SizeBytes' -Default 0)
            lastWriteTimeUtc = [string](Get-StableAmdObjectPropertyValue -Object $model -Name 'LastWriteTimeUtc' -Default '')
            validation = $validation
            sha256 = $sha256
            source = $source
            sourceMetadata = $sourceMetadata
        }
    }

    return [pscustomobject]@{
        schemaVersion = 1
        updatedAtUtc = [DateTime]::UtcNow.ToString('o')
        models = @($merged)
    }
}

function Upsert-StableAmdModelRegistryEntry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Registry,

        [Parameter(Mandatory = $true)]
        [psobject]$Entry
    )

    $entryPath = [IO.Path]::GetFullPath([string]$Entry.path)
    $models = New-Object System.Collections.Generic.List[object]
    $replaced = $false
    foreach ($model in @(Get-StableAmdObjectPropertyValue -Object $Registry -Name 'models' -Default @())) {
        $modelPath = [string](Get-StableAmdObjectPropertyValue -Object $model -Name 'path' -Default '')
        if (-not [string]::IsNullOrWhiteSpace($modelPath) -and [IO.Path]::GetFullPath($modelPath).Equals($entryPath, [StringComparison]::OrdinalIgnoreCase)) {
            if (-not $replaced) {
                $models.Add($Entry)
                $replaced = $true
            }
        }
        else {
            $models.Add($model)
        }
    }
    if (-not $replaced) { $models.Add($Entry) }

    return [pscustomobject]@{
        schemaVersion = 1
        updatedAtUtc = [DateTime]::UtcNow.ToString('o')
        models = @($models)
    }
}

Export-ModuleMember -Function Get-StableAmdModelId, Get-StableAmdModelFamily, Resolve-StableAmdHuggingFaceUrl, Get-StableAmdModelDestinationPath, Test-StableAmdModelSha256, New-StableAmdEmptyModelRegistry, Read-StableAmdModelRegistry, Write-StableAmdModelRegistry, Find-StableAmdCheckpoints, Merge-StableAmdModelRegistry, Upsert-StableAmdModelRegistryEntry
