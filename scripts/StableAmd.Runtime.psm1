Set-StrictMode -Version 2.0

function New-StableAmdDefaultConfig {
    [CmdletBinding()]
    param()

    return [pscustomobject]@{
        schemaVersion = 1
        backend = [pscustomobject]@{
            host = '127.0.0.1'
            port = 8190
            startupTimeoutSeconds = 240
        }
        generation = [pscustomobject]@{
            outputDirectory = '.runtime/stableamd/output'
            defaultWidth = 1024
            defaultHeight = 1024
            defaultSteps = 20
            defaultCfg = 7.0
            defaultSampler = 'euler'
            defaultScheduler = 'normal'
        }
        models = [pscustomobject]@{
            roots = @(
                '.runtime/stableamd/models/checkpoints',
                '.runtime/SwarmUI/Models/Stable-Diffusion'
            )
        }
    }
}

function Resolve-StableAmdPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }

    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
}

function Get-StableAmdRuntimePaths {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot
    )

    $repo = [IO.Path]::GetFullPath($RepoRoot)
    $runtimeRoot = [IO.Path]::GetFullPath((Join-Path $repo '.runtime'))
    $stableAmdRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot 'stableamd'))

    return [pscustomobject]@{
        RepoRoot = $repo
        RuntimeRoot = $runtimeRoot
        StableAmdRoot = $stableAmdRoot
        ConfigPath = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'config.json'))
        BackendStatePath = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'backend-state.json'))
        ModelsRegistryPath = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'models.json'))
        ModelsRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'models'))
        CheckpointsRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'models/checkpoints'))
        OutputRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'output'))
        HistoryRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'history'))
        LogsRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'logs'))
        GeneratedConfigRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'generated'))
        TheRockPython = [IO.Path]::GetFullPath((Join-Path $runtimeRoot 'therock-gfx1030/python_embeded/python.exe'))
        ComfyRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot 'therock-comfy/ComfyUI'))
        ComfyRunner = [IO.Path]::GetFullPath((Join-Path $repo 'scripts/probes/run_comfy_isolated.py'))
        SwarmModelsRoot = [IO.Path]::GetFullPath((Join-Path $runtimeRoot 'SwarmUI/Models'))
        DefaultConfigPath = [IO.Path]::GetFullPath((Join-Path $repo 'config/stableamd.default.json'))
    }
}

function Initialize-StableAmdRuntimeDirectories {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Paths
    )

    foreach ($path in @(
        $Paths.StableAmdRoot,
        $Paths.ModelsRoot,
        $Paths.CheckpointsRoot,
        $Paths.OutputRoot,
        $Paths.HistoryRoot,
        $Paths.LogsRoot,
        $Paths.GeneratedConfigRoot
    )) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
}

function Read-StableAmdConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$RepoRoot,

        [string]$Path = ''
    )

    $paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
    $configPath = if ([string]::IsNullOrWhiteSpace($Path)) { $paths.ConfigPath } else { Resolve-StableAmdPath -Path $Path -RepoRoot $RepoRoot }

    if (Test-Path $configPath) {
        return Get-Content -Path $configPath -Raw | ConvertFrom-Json
    }

    if (Test-Path $paths.DefaultConfigPath) {
        return Get-Content -Path $paths.DefaultConfigPath -Raw | ConvertFrom-Json
    }

    return New-StableAmdDefaultConfig
}

function Write-StableAmdConfig {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [psobject]$Config
    )

    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $Config | ConvertTo-Json -Depth 12 | Set-Content -Path $Path -Encoding UTF8
}

function Write-StableAmdBackendState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [psobject]$State
    )

    $parent = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $State | ConvertTo-Json -Depth 12 | Set-Content -Path $Path -Encoding UTF8
}

function Read-StableAmdBackendState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    return Get-Content -Path $Path -Raw | ConvertFrom-Json
}

function Remove-StableAmdBackendState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if (Test-Path $Path) {
        Remove-Item -Path $Path -Force
    }
}

Export-ModuleMember -Function New-StableAmdDefaultConfig, Resolve-StableAmdPath, Get-StableAmdRuntimePaths, Initialize-StableAmdRuntimeDirectories, Read-StableAmdConfig, Write-StableAmdConfig, Write-StableAmdBackendState, Read-StableAmdBackendState, Remove-StableAmdBackendState
