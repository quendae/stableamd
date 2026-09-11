BeforeAll {
    $modulePath = Join-Path $PSScriptRoot '../scripts/StableAmd.Runtime.psm1'
    Import-Module $modulePath -Force
}

Describe 'StableAMD runtime configuration' {
    It 'provides loopback backend defaults and SDXL generation defaults' {
        $config = New-StableAmdDefaultConfig

        $config.schemaVersion | Should -Be 1
        $config.backend.host | Should -Be '127.0.0.1'
        $config.backend.port | Should -Be 8190
        $config.backend.startupTimeoutSeconds | Should -Be 240
        $config.generation.defaultWidth | Should -Be 1024
        $config.generation.defaultHeight | Should -Be 1024
        $config.generation.defaultSteps | Should -Be 20
        $config.generation.defaultCfg | Should -Be 7.0
        $config.generation.defaultSampler | Should -Be 'euler'
        $config.generation.defaultScheduler | Should -Be 'normal'
    }

    It 'resolves repository-relative paths under the supplied repository root' {
        $repoRoot = 'C:\StableAMD'
        $resolved = Resolve-StableAmdPath -Path '.runtime/stableamd/output' -RepoRoot $repoRoot
        $resolved | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\stableamd\output'))
    }

    It 'leaves absolute paths absolute' {
        $repoRoot = 'C:\StableAMD'
        $resolved = Resolve-StableAmdPath -Path 'D:\AI\Models' -RepoRoot $repoRoot
        $resolved | Should -Be ([IO.Path]::GetFullPath('D:\AI\Models'))
    }

    It 'returns the canonical StableAMD runtime paths' {
        $repoRoot = 'C:\StableAMD'
        $paths = Get-StableAmdRuntimePaths -RepoRoot $repoRoot

        $paths.RuntimeRoot | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime'))
        $paths.StableAmdRoot | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\stableamd'))
        $paths.ConfigPath | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\stableamd\config.json'))
        $paths.BackendStatePath | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\stableamd\backend-state.json'))
        $paths.ModelsRegistryPath | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\stableamd\models.json'))
        $paths.OutputRoot | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\stableamd\output'))
        $paths.LogsRoot | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\stableamd\logs'))
        $paths.TheRockPython | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\therock-gfx1030\python_embeded\python.exe'))
        $paths.ComfyRoot | Should -Be ([IO.Path]::GetFullPath('C:\StableAMD\.runtime\therock-comfy\ComfyUI'))
    }

    It 'round-trips backend state as JSON' {
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-runtime-test-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        try {
            $statePath = Join-Path $tempRoot 'backend-state.json'
            $state = [pscustomobject]@{
                schemaVersion = 1
                pid = 12345
                url = 'http://127.0.0.1:8190/'
                startedAtUtc = '2026-09-11T16:00:00Z'
                device = [pscustomobject]@{
                    name = 'cuda:0 AMD Radeon RX 6950 XT : native'
                    type = 'cuda'
                    vramTotal = 17163091968
                }
            }

            Write-StableAmdBackendState -Path $statePath -State $state
            $read = Read-StableAmdBackendState -Path $statePath

            $read.pid | Should -Be 12345
            $read.url | Should -Be 'http://127.0.0.1:8190/'
            $read.device.name | Should -Match 'RX 6950 XT'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'returns null when backend state does not exist' {
        $missing = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-missing-' + [guid]::NewGuid().ToString('N') + '.json')
        Read-StableAmdBackendState -Path $missing | Should -BeNullOrEmpty
    }
}

Describe 'StableAMD default config file' {
    It 'ships a version-controlled default config matching runtime defaults' {
        $defaultPath = Join-Path $PSScriptRoot '../config/stableamd.default.json'
        Test-Path $defaultPath | Should -BeTrue

        $fileConfig = Get-Content $defaultPath -Raw | ConvertFrom-Json
        $runtimeConfig = New-StableAmdDefaultConfig

        $fileConfig.backend.host | Should -Be $runtimeConfig.backend.host
        $fileConfig.backend.port | Should -Be $runtimeConfig.backend.port
        $fileConfig.generation.defaultWidth | Should -Be $runtimeConfig.generation.defaultWidth
        $fileConfig.models.roots.Count | Should -Be 2
    }
}
