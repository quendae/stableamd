Set-StrictMode -Version 2.0

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force

function Get-StableAmdBundleRoleMetadata {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('diffusion_model', 'text_encoder', 'vae')]
        [string]$Role,
        [Parameter(Mandatory = $true)]
        [psobject]$Paths
    )

    switch ($Role) {
        'diffusion_model' {
            return [pscustomobject]@{ role = $Role; configName = 'diffusionModels'; managedRoot = $Paths.DiffusionModelsRoot; label = 'Diffusion model' }
        }
        'text_encoder' {
            return [pscustomobject]@{ role = $Role; configName = 'textEncoders'; managedRoot = $Paths.TextEncodersRoot; label = 'Text encoder' }
        }
        'vae' {
            return [pscustomobject]@{ role = $Role; configName = 'vae'; managedRoot = $Paths.VaeRoot; label = 'VAE' }
        }
    }
}

function Get-StableAmdBundleRoleSection {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][psobject]$Config,
        [Parameter(Mandatory = $true)][string]$ConfigName
    )

    if ($null -eq $Config.PSObject.Properties['bundleAssets'] -or $null -eq $Config.bundleAssets) {
        $Config | Add-Member -MemberType NoteProperty -Name bundleAssets -Value ([pscustomobject]@{}) -Force
    }
    $property = $Config.bundleAssets.PSObject.Properties[$ConfigName]
    if ($null -eq $property -or $null -eq $property.Value) {
        $section = [pscustomobject]@{ roots = @() }
        $Config.bundleAssets | Add-Member -MemberType NoteProperty -Name $ConfigName -Value $section -Force
        return $section
    }
    $section = $property.Value
    if ($null -eq $section.PSObject.Properties['roots'] -or $null -eq $section.roots) {
        $section | Add-Member -MemberType NoteProperty -Name roots -Value @() -Force
    }
    return $section
}

function Get-StableAmdBundleAssetRootRecords {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][ValidateSet('diffusion_model', 'text_encoder', 'vae')][string]$Role
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $paths = Get-StableAmdRuntimePaths -RepoRoot $repo
    $config = Read-StableAmdConfig -RepoRoot $repo
    $metadata = Get-StableAmdBundleRoleMetadata -Role $Role -Paths $paths
    $section = Get-StableAmdBundleRoleSection -Config $config -ConfigName $metadata.configName
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $records = @()

    foreach ($rawRoot in @($section.roots)) {
        $raw = [string]$rawRoot
        if ([string]::IsNullOrWhiteSpace($raw)) { continue }
        $resolved = Resolve-StableAmdPath -Path $raw -RepoRoot $repo
        if (-not $seen.Add($resolved)) { continue }
        $records += [pscustomobject]@{
            role = $Role
            raw = $raw
            path = $resolved
            exists = [bool](Test-Path $resolved -PathType Container)
            managed = $resolved.Equals([string]$metadata.managedRoot, [StringComparison]::OrdinalIgnoreCase)
        }
    }
    return @($records)
}

function Add-StableAmdBundleAssetRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][ValidateSet('diffusion_model', 'text_encoder', 'vae')][string]$Role,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $runtimePaths = Get-StableAmdRuntimePaths -RepoRoot $repo
    Initialize-StableAmdRuntimeDirectories -Paths $runtimePaths
    $metadata = Get-StableAmdBundleRoleMetadata -Role $Role -Paths $runtimePaths
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "$($metadata.label) folder path cannot be empty." }
    $resolved = Resolve-StableAmdPath -Path $Path -RepoRoot $repo
    if (-not (Test-Path $resolved -PathType Container)) { throw "$($metadata.label) folder was not found: '$resolved'." }

    $config = Read-StableAmdConfig -RepoRoot $repo
    $section = Get-StableAmdBundleRoleSection -Config $config -ConfigName $metadata.configName
    $existing = @(Get-StableAmdBundleAssetRootRecords -RepoRoot $repo -Role $Role)
    if (@($existing | Where-Object { $_.path.Equals($resolved, [StringComparison]::OrdinalIgnoreCase) }).Count -gt 0) {
        return [pscustomobject]@{ added = $false; role = $Role; path = $resolved; reason = 'already-configured' }
    }

    $roots = @($section.roots)
    $roots += $resolved
    $section.roots = @($roots)
    Write-StableAmdConfig -Path $runtimePaths.ConfigPath -Config $config
    return [pscustomobject]@{ added = $true; role = $Role; path = $resolved; reason = 'added' }
}

function Remove-StableAmdBundleAssetRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RepoRoot,
        [Parameter(Mandatory = $true)][ValidateSet('diffusion_model', 'text_encoder', 'vae')][string]$Role,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $runtimePaths = Get-StableAmdRuntimePaths -RepoRoot $repo
    $metadata = Get-StableAmdBundleRoleMetadata -Role $Role -Paths $runtimePaths
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "$($metadata.label) folder path cannot be empty." }
    $resolved = Resolve-StableAmdPath -Path $Path -RepoRoot $repo
    if ($resolved.Equals([string]$metadata.managedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The StableAMD managed $($metadata.label.ToLowerInvariant()) folder cannot be removed."
    }

    $config = Read-StableAmdConfig -RepoRoot $repo
    $section = Get-StableAmdBundleRoleSection -Config $config -ConfigName $metadata.configName
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
    return [pscustomobject]@{ removed = $removed; role = $Role; path = $resolved; reason = if ($removed) { 'removed' } else { 'not-configured' } }
}

Export-ModuleMember -Function Get-StableAmdBundleAssetRootRecords, Add-StableAmdBundleAssetRoot, Remove-StableAmdBundleAssetRoot
