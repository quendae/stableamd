Set-StrictMode -Version 2.0

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
    if ($null -eq $registry.models) {
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
    foreach ($model in @($ExistingRegistry.models)) {
        if ($null -ne $model.path -and -not [string]::IsNullOrWhiteSpace([string]$model.path)) {
            $existingByPath[[IO.Path]::GetFullPath([string]$model.path).ToLowerInvariant()] = $model
        }
    }

    $merged = @()
    foreach ($model in @($DiscoveredModels)) {
        $key = [IO.Path]::GetFullPath([string]$model.Path).ToLowerInvariant()
        $old = $existingByPath[$key]
        if ($null -ne $old) {
            $validation = if ($null -ne $old.validation) { [string]$old.validation } else { 'unknown' }
            $source = if ($null -ne $old.source) { [string]$old.source } else { 'discovered' }
            $sha256 = if ($null -ne $old.sha256) { [string]$old.sha256 } else { $null }
            $sourceMetadata = if ($null -ne $old.sourceMetadata) { $old.sourceMetadata } else { $null }
        }
        else {
            $validation = [string]$model.Validation
            $source = [string]$model.Source
            $sha256 = $null
            $sourceMetadata = $null
        }

        $merged += [pscustomobject]@{
            id = [string]$model.Id
            name = [string]$model.Name
            path = [string]$model.Path
            family = [string]$model.Family
            sizeBytes = [Int64]$model.SizeBytes
            lastWriteTimeUtc = [string]$model.LastWriteTimeUtc
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

Export-ModuleMember -Function Get-StableAmdModelId, Get-StableAmdModelFamily, New-StableAmdEmptyModelRegistry, Read-StableAmdModelRegistry, Write-StableAmdModelRegistry, Find-StableAmdCheckpoints, Merge-StableAmdModelRegistry
