Set-StrictMode -Version 2.0

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force

function Get-StableAmdRootConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][psobject]$Config,
        [Parameter(Mandatory = $true)][ValidateSet('models', 'loras')][string]$Kind
    )

    $property = $Config.PSObject.Properties[$Kind]
    if ($null -eq $property -or $null -eq $property.Value) {
        $value = [pscustomobject]@{ roots = @() }
        $Config | Add-Member -MemberType NoteProperty -Name $Kind -Value $value -Force
        return $value
    }

    $value = $property.Value
    $rootsProperty = $value.PSObject.Properties['roots']
    if ($null -eq $rootsProperty -or $null -eq $rootsProperty.Value) {
        $value | Add-Member -MemberType NoteProperty -Name roots -Value @() -Force
    }
    return $value
}

function Get-StableAmdResolvedRoots {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][psobject]$Config,
        [Parameter(Mandatory = $true)][ValidateSet('models', 'loras')][string]$Kind
    )

    $paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
    $configSection = Get-StableAmdRootConfig -Config $Config -Kind $Kind
    $managedRoot = if ($Kind -eq 'models') { $paths.CheckpointsRoot } else { $paths.LorasRoot }
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $result = @()

    foreach ($rawRoot in @($configSection.roots)) {
        $raw = [string]$rawRoot
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        $resolved = Resolve-StableAmdPath -Path $raw -RepoRoot $RepoRoot
        if (-not $seen.Add($resolved)) { continue }
        $result += [pscustomobject]@{
            raw = $raw
            path = $resolved
            exists = [bool](Test-Path $resolved -PathType Container)
            managed = $resolved.Equals($managedRoot, [StringComparison]::OrdinalIgnoreCase)
            kind = $Kind
        }
    }

    return @($result)
}

function Get-StableAmdModelRootRecords {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $config = Read-StableAmdConfig -RepoRoot $repo
    return @(Get-StableAmdResolvedRoots -RepoRoot $repo -Config $config -Kind 'models')
}

function Get-StableAmdLoraRootRecords {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $config = Read-StableAmdConfig -RepoRoot $repo
    return @(Get-StableAmdResolvedRoots -RepoRoot $repo -Config $config -Kind 'loras')
}

function Add-StableAmdRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet('models', 'loras')][string]$Kind
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $label = if ($Kind -eq 'models') { 'Model' } else { 'LoRA' }
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$label folder path cannot be empty."
    }
    $resolved = Resolve-StableAmdPath -Path $Path -RepoRoot $repo
    if (-not (Test-Path $resolved -PathType Container)) {
        throw "$label folder was not found: '$resolved'."
    }

    $runtimePaths = Get-StableAmdRuntimePaths -RepoRoot $repo
    Initialize-StableAmdRuntimeDirectories -Paths $runtimePaths
    $config = Read-StableAmdConfig -RepoRoot $repo
    $section = Get-StableAmdRootConfig -Config $config -Kind $Kind
    $existing = @(Get-StableAmdResolvedRoots -RepoRoot $repo -Config $config -Kind $Kind)
    if (@($existing | Where-Object { $_.path.Equals($resolved, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0) {
        return [pscustomobject]@{ added = $false; path = $resolved; reason = 'already-configured'; kind = $Kind }
    }

    $roots = @($section.roots)
    $roots += $resolved
    $section.roots = @($roots)
    Write-StableAmdConfig -Path $runtimePaths.ConfigPath -Config $config
    return [pscustomobject]@{ added = $true; path = $resolved; reason = 'added'; kind = $Kind }
}

function Remove-StableAmdRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][ValidateSet('models', 'loras')][string]$Kind
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $label = if ($Kind -eq 'models') { 'Model' } else { 'LoRA' }
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw "$label folder path cannot be empty."
    }
    $resolved = Resolve-StableAmdPath -Path $Path -RepoRoot $repo
    $runtimePaths = Get-StableAmdRuntimePaths -RepoRoot $repo
    $managedRoot = if ($Kind -eq 'models') { $runtimePaths.CheckpointsRoot } else { $runtimePaths.LorasRoot }
    if ($resolved.Equals($managedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The StableAMD managed $($label.ToLowerInvariant()) folder cannot be removed."
    }

    $config = Read-StableAmdConfig -RepoRoot $repo
    $section = Get-StableAmdRootConfig -Config $config -Kind $Kind
    $kept = @()
    $removed = $false
    foreach ($rawRoot in @($section.roots)) {
        $raw = [string]$rawRoot
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        $candidate = Resolve-StableAmdPath -Path $raw -RepoRoot $repo
        if ($candidate.Equals($resolved, [StringComparison]::OrdinalIgnoreCase)) {
            $removed = $true
            continue
        }
        $kept += $raw
    }

    if ($removed) {
        $section.roots = @($kept)
        Initialize-StableAmdRuntimeDirectories -Paths $runtimePaths
        Write-StableAmdConfig -Path $runtimePaths.ConfigPath -Config $config
    }
    return [pscustomobject]@{ removed = $removed; path = $resolved; reason = if ($removed) { 'removed' } else { 'not-configured' }; kind = $Kind }
}

function Add-StableAmdModelRoot {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [Parameter(Mandatory = $true)][string]$Path)
    return Add-StableAmdRoot -RepoRoot $RepoRoot -Path $Path -Kind 'models'
}

function Remove-StableAmdModelRoot {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [Parameter(Mandatory = $true)][string]$Path)
    return Remove-StableAmdRoot -RepoRoot $RepoRoot -Path $Path -Kind 'models'
}

function Add-StableAmdLoraRoot {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [Parameter(Mandatory = $true)][string]$Path)
    return Add-StableAmdRoot -RepoRoot $RepoRoot -Path $Path -Kind 'loras'
}

function Remove-StableAmdLoraRoot {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [Parameter(Mandatory = $true)][string]$Path)
    return Remove-StableAmdRoot -RepoRoot $RepoRoot -Path $Path -Kind 'loras'
}

Export-ModuleMember -Function Get-StableAmdModelRootRecords, Add-StableAmdModelRoot, Remove-StableAmdModelRoot, Get-StableAmdLoraRootRecords, Add-StableAmdLoraRoot, Remove-StableAmdLoraRoot
