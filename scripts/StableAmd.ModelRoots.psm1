Set-StrictMode -Version 2.0

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force

function Get-StableAmdModelsConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][psobject]$Config
    )

    $modelsProperty = $Config.PSObject.Properties['models']
    if ($null -eq $modelsProperty -or $null -eq $modelsProperty.Value) {
        $models = [pscustomobject]@{ roots = @() }
        $Config | Add-Member -MemberType NoteProperty -Name models -Value $models -Force
        return $models
    }

    $models = $modelsProperty.Value
    $rootsProperty = $models.PSObject.Properties['roots']
    if ($null -eq $rootsProperty -or $null -eq $rootsProperty.Value) {
        $models | Add-Member -MemberType NoteProperty -Name roots -Value @() -Force
    }
    return $models
}

function Get-StableAmdResolvedModelRoots {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][psobject]$Config
    )

    $paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
    $models = Get-StableAmdModelsConfig -Config $Config
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $result = @()

    foreach ($rawRoot in @($models.roots)) {
        $raw = [string]$rawRoot
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        $resolved = Resolve-StableAmdPath -Path $raw -RepoRoot $RepoRoot
        if (-not $seen.Add($resolved)) { continue }
        $result += [pscustomobject]@{
            raw = $raw
            path = $resolved
            exists = [bool](Test-Path $resolved -PathType Container)
            managed = $resolved.Equals($paths.CheckpointsRoot, [StringComparison]::OrdinalIgnoreCase)
        }
    }

    return @($result)
}

function Get-StableAmdModelRootRecords {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $config = Read-StableAmdConfig -RepoRoot $repo
    return @(Get-StableAmdResolvedModelRoots -RepoRoot $repo -Config $config)
}

function Add-StableAmdModelRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'Model folder path cannot be empty.'
    }
    $resolved = Resolve-StableAmdPath -Path $Path -RepoRoot $repo
    if (-not (Test-Path $resolved -PathType Container)) {
        throw "Model folder was not found: '$resolved'."
    }

    $runtimePaths = Get-StableAmdRuntimePaths -RepoRoot $repo
    Initialize-StableAmdRuntimeDirectories -Paths $runtimePaths
    $config = Read-StableAmdConfig -RepoRoot $repo
    $models = Get-StableAmdModelsConfig -Config $config
    $existing = @(Get-StableAmdResolvedModelRoots -RepoRoot $repo -Config $config)
    if (@($existing | Where-Object { $_.path.Equals($resolved, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0) {
        return [pscustomobject]@{ added = $false; path = $resolved; reason = 'already-configured' }
    }

    $roots = @($models.roots)
    $roots += $resolved
    $models.roots = @($roots)
    Write-StableAmdConfig -Path $runtimePaths.ConfigPath -Config $config
    return [pscustomobject]@{ added = $true; path = $resolved; reason = 'added' }
}

function Remove-StableAmdModelRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    if ([string]::IsNullOrWhiteSpace($Path)) {
        throw 'Model folder path cannot be empty.'
    }
    $resolved = Resolve-StableAmdPath -Path $Path -RepoRoot $repo
    $runtimePaths = Get-StableAmdRuntimePaths -RepoRoot $repo
    if ($resolved.Equals($runtimePaths.CheckpointsRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The StableAMD managed checkpoint folder cannot be removed.'
    }

    $config = Read-StableAmdConfig -RepoRoot $repo
    $models = Get-StableAmdModelsConfig -Config $config
    $kept = @()
    $removed = $false
    foreach ($rawRoot in @($models.roots)) {
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
        $models.roots = @($kept)
        Initialize-StableAmdRuntimeDirectories -Paths $runtimePaths
        Write-StableAmdConfig -Path $runtimePaths.ConfigPath -Config $config
    }
    return [pscustomobject]@{ removed = $removed; path = $resolved; reason = if ($removed) { 'removed' } else { 'not-configured' } }
}

Export-ModuleMember -Function Get-StableAmdModelRootRecords, Add-StableAmdModelRoot, Remove-StableAmdModelRoot
