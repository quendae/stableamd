Set-StrictMode -Version 2.0

function Get-StableAmdBundleId {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Family,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $normalized = ($Family.Trim().ToLowerInvariant() + '|' + $Name.Trim().ToLowerInvariant())
    $bytes = [Text.Encoding]::UTF8.GetBytes($normalized)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { $hash = $sha.ComputeHash($bytes) }
    finally { $sha.Dispose() }
    $hex = -join ($hash | ForEach-Object { $_.ToString('x2') })
    return 'bnd_' + $hex.Substring(0, 16)
}

function New-StableAmdEmptyBundleRegistry {
    [CmdletBinding()]
    param()

    return [pscustomobject]@{
        schemaVersion = 1
        bundles = @()
    }
}

function Read-StableAmdBundleRegistry {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path -PathType Leaf)) {
        return New-StableAmdEmptyBundleRegistry
    }

    $registry = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($null -eq $registry.PSObject.Properties['bundles']) {
        $registry | Add-Member -MemberType NoteProperty -Name bundles -Value @() -Force
    }
    elseif ($null -eq $registry.bundles) {
        $registry.bundles = @()
    }
    return $registry
}

function Write-StableAmdBundleRegistry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][psobject]$Registry
    )

    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $Registry | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Find-StableAmdBundleAssets {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$Roots
    )

    $allowed = @('.safetensors', '.gguf', '.pt', '.pth', '.bin')
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $assets = @()

    foreach ($root in @($Roots)) {
        if ([string]::IsNullOrWhiteSpace($root) -or -not (Test-Path $root -PathType Container)) { continue }
        foreach ($file in @(Get-ChildItem -LiteralPath $root -File -Recurse -ErrorAction SilentlyContinue)) {
            if ($allowed -notcontains $file.Extension.ToLowerInvariant()) { continue }
            $full = [IO.Path]::GetFullPath($file.FullName)
            if (-not $seen.Add($full)) { continue }
            $assets += [pscustomobject]@{
                role = $Role
                name = $file.Name
                path = $full
                sizeBytes = [Int64]$file.Length
                lastWriteTimeUtc = $file.LastWriteTimeUtc.ToString('o')
            }
        }
    }

    return @($assets | Sort-Object name, path)
}

function New-StableAmdBundleEntry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Family,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][hashtable]$Assets,
        [string]$Provider = ''
    )

    if ([string]::IsNullOrWhiteSpace($Family)) { throw 'Bundle family cannot be empty.' }
    if ([string]::IsNullOrWhiteSpace($Name)) { throw 'Bundle name cannot be empty.' }

    $normalizedAssets = [ordered]@{}
    foreach ($role in @($Assets.Keys | Sort-Object)) {
        # Keep this as a real array. Windows PowerShell/strict mode unwraps a
        # one-item pipeline result into a scalar, which made `.Count` invalid.
        $paths = @(
            @($Assets[$role]) |
                ForEach-Object { [string]$_ } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        if (@($paths).Count -gt 0) {
            $normalizedAssets[[string]$role] = @($paths | ForEach-Object { [IO.Path]::GetFullPath($_) })
        }
    }

    return [pscustomobject]@{
        id = Get-StableAmdBundleId -Family $Family -Name $Name
        name = $Name.Trim()
        family = $Family.Trim().ToLowerInvariant()
        provider = $Provider.Trim()
        assetMode = 'bundle'
        assets = [pscustomobject]$normalizedAssets
        updatedAtUtc = [DateTime]::UtcNow.ToString('o')
    }
}

function Test-StableAmdBundleEntry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][psobject]$Entry,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][string[]]$RequiredRoles,
        [switch]$RequireFiles
    )

    $missingRoles = @()
    $missingFiles = @()
    $assetsProperty = $Entry.PSObject.Properties['assets']
    $assets = if ($null -ne $assetsProperty) { $assetsProperty.Value } else { $null }

    foreach ($role in @($RequiredRoles)) {
        $roleProperty = if ($null -ne $assets) { $assets.PSObject.Properties[$role] } else { $null }
        $paths = if ($null -ne $roleProperty -and $null -ne $roleProperty.Value) { @($roleProperty.Value) } else { @() }
        $paths = @(
            $paths |
                ForEach-Object { [string]$_ } |
                Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )
        if (@($paths).Count -eq 0) {
            $missingRoles += $role
            continue
        }
        if ($RequireFiles) {
            foreach ($path in $paths) {
                if (-not (Test-Path $path -PathType Leaf)) { $missingFiles += $path }
            }
        }
    }

    return [pscustomobject]@{
        complete = ($missingRoles.Count -eq 0 -and $missingFiles.Count -eq 0)
        missingRoles = @($missingRoles)
        missingFiles = @($missingFiles)
    }
}

function Upsert-StableAmdBundleRegistryEntry {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][psobject]$Registry,
        [Parameter(Mandatory = $true)][psobject]$Entry
    )

    $bundles = @()
    $replaced = $false
    foreach ($bundle in @($Registry.bundles)) {
        if ([string]$bundle.id -eq [string]$Entry.id) {
            if (-not $replaced) {
                $bundles += $Entry
                $replaced = $true
            }
        }
        else {
            $bundles += $bundle
        }
    }
    if (-not $replaced) { $bundles += $Entry }

    return [pscustomobject]@{
        schemaVersion = 1
        updatedAtUtc = [DateTime]::UtcNow.ToString('o')
        bundles = @($bundles)
    }
}

Export-ModuleMember -Function Get-StableAmdBundleId, New-StableAmdEmptyBundleRegistry, Read-StableAmdBundleRegistry, Write-StableAmdBundleRegistry, Find-StableAmdBundleAssets, New-StableAmdBundleEntry, Test-StableAmdBundleEntry, Upsert-StableAmdBundleRegistryEntry
