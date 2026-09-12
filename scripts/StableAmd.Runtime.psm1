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
        loras = [pscustomobject]@{
            roots = @(
                '.runtime/stableamd/models/loras',
                '.runtime/SwarmUI/Models/Lora'
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
        AppStatePath = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'app-state.json'))
        ModelsRegistryPath = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'models.json'))
        ModelsRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'models'))
        CheckpointsRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'models/checkpoints'))
        LorasRoot = [IO.Path]::GetFullPath((Join-Path $stableAmdRoot 'models/loras'))
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
        $Paths.LorasRoot,
        $Paths.OutputRoot,
        $Paths.HistoryRoot,
        $Paths.LogsRoot,
        $Paths.GeneratedConfigRoot
    )) {
        New-Item -ItemType Directory -Path $path -Force | Out-Null
    }
}

function Add-StableAmdMissingConfigDefaults {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [psobject]$Config
    )

    if ($null -eq $Config.PSObject.Properties['loras'] -or $null -eq $Config.loras) {
        $Config | Add-Member -MemberType NoteProperty -Name loras -Value ([pscustomobject]@{
            roots = @(
                '.runtime/stableamd/models/loras',
                '.runtime/SwarmUI/Models/Lora'
            )
        }) -Force
    }
    elseif ($null -eq $Config.loras.PSObject.Properties['roots'] -or $null -eq $Config.loras.roots) {
        $Config.loras | Add-Member -MemberType NoteProperty -Name roots -Value @('.runtime/stableamd/models/loras') -Force
    }

    return $Config
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

    $config = $null
    if (Test-Path $configPath) {
        $config = Get-Content -Path $configPath -Raw | ConvertFrom-Json
    }
    elseif (Test-Path $paths.DefaultConfigPath) {
        $config = Get-Content -Path $paths.DefaultConfigPath -Raw | ConvertFrom-Json
    }
    else {
        $config = New-StableAmdDefaultConfig
    }

    return Add-StableAmdMissingConfigDefaults -Config $config
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
