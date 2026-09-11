BeforeAll {
    Import-Module "$PSScriptRoot/../scripts/StableAmd.Hardware.psm1" -Force
}

Describe 'Resolve-StableAmdGfxTarget' {
    It 'maps RX 6950 XT to gfx1030' {
        Resolve-StableAmdGfxTarget -Name 'AMD Radeon RX 6950 XT' | Should -Be 'gfx1030'
    }

    It 'matches the RX 6950 XT name case-insensitively' {
        Resolve-StableAmdGfxTarget -Name 'amd radeon rx 6950 xt' | Should -Be 'gfx1030'
    }

    It 'returns null for an unrelated GPU' {
        Resolve-StableAmdGfxTarget -Name 'NVIDIA GeForce RTX 3060' | Should -BeNullOrEmpty
    }
}

Describe 'Get-StableAmdSupportTier' {
    It 'classifies RX 6950 XT Windows ROCm as experimental' {
        $result = Get-StableAmdSupportTier -Name 'AMD Radeon RX 6950 XT'
        $result.GfxTarget | Should -Be 'gfx1030'
        $result.Tier | Should -Be 'experimental-windows'
        $result.OfficialWindowsHipSdkSupport | Should -BeFalse
    }

    It 'classifies unknown GPUs as unknown' {
        $result = Get-StableAmdSupportTier -Name 'Example GPU'
        $result.Tier | Should -Be 'unknown'
        $result.GfxTarget | Should -BeNullOrEmpty
    }
}

Describe 'New-StableAmdPreflightRecord' {
    It 'builds a deterministic preflight record from injected GPU data' {
        $controllers = @(
            [pscustomobject]@{
                Name = 'AMD Radeon RX 6950 XT'
                DriverVersion = '32.0.21001.9024'
                AdapterRAM = 17179869184
            }
        )

        $record = New-StableAmdPreflightRecord -VideoControllers $controllers -OsCaption 'Microsoft Windows 11 Pro' -OsVersion '10.0.26100' -OsBuild '26100' -CommandVersions @{ git = '2.51.0'; dotnet = '10.0.100' }

        $record.Gpus.Count | Should -Be 1
        $record.Gpus[0].GfxTarget | Should -Be 'gfx1030'
        $record.Gpus[0].SupportTier | Should -Be 'experimental-windows'
        $record.Os.Build | Should -Be '26100'
        $record.Tools.git | Should -Be '2.51.0'
    }
}

Describe 'Get-StableAmdSpikeEnvironment' {
    It 'does not inject an HSA override in baseline mode' {
        $envMap = Get-StableAmdSpikeEnvironment -Mode Baseline
        $envMap.ContainsKey('HSA_OVERRIDE_GFX_VERSION') | Should -BeFalse
    }

    It 'injects gfx1030 override only in GfxOverride mode' {
        $envMap = Get-StableAmdSpikeEnvironment -Mode GfxOverride
        $envMap['HSA_OVERRIDE_GFX_VERSION'] | Should -Be '10.3.0'
    }
}

Describe 'Test-StableAmdDotNet8Sdk' {
    It 'accepts an installed .NET 8 SDK' {
        Test-StableAmdDotNet8Sdk -SdkList @(
            '8.0.419 [C:\Program Files\dotnet\sdk]',
            '10.0.100 [C:\Program Files\dotnet\sdk]'
        ) | Should -BeTrue
    }

    It 'rejects a machine with only newer SDKs and no .NET 8 SDK' {
        Test-StableAmdDotNet8Sdk -SdkList @(
            '9.0.305 [C:\Program Files\dotnet\sdk]',
            '10.0.100 [C:\Program Files\dotnet\sdk]'
        ) | Should -BeFalse
    }

    It 'rejects an empty SDK list' {
        Test-StableAmdDotNet8Sdk -SdkList @() | Should -BeFalse
    }
}

Describe 'Resolve-StableAmdSwarmUrl' {
    It 'uses the actual port reported by SwarmUI instead of assuming 7801' {
        $url = Resolve-StableAmdSwarmUrl -LogLines @(
            '14:23:57.138 [Init] Launching server...',
            '14:23:57.153 [Init] Starting webserver on http://localhost:7802',
            '14:23:57.300 [Init] Swarm is up to date!'
        )
        $url | Should -Be 'http://127.0.0.1:7802/'
    }

    It 'supports the default 7801 port when Swarm reports it' {
        $url = Resolve-StableAmdSwarmUrl -LogLines @(
            '[Init] Starting webserver on http://localhost:7801'
        )
        $url | Should -Be 'http://127.0.0.1:7801/'
    }

    It 'returns null before the server URL appears in the log' {
        Resolve-StableAmdSwarmUrl -LogLines @(
            '[Init] Prepping webserver...',
            '[Init] Launching server...'
        ) | Should -BeNullOrEmpty
    }
}

Describe 'Backend probe launcher' {
    It 'uses a standalone Python probe file instead of python -c quoting' {
        $probePath = Join-Path $PSScriptRoot '../scripts/probes/amd_backend_probe.py'
        Test-Path $probePath | Should -BeTrue

        $launcher = Get-Content (Join-Path $PSScriptRoot '../scripts/Test-SwarmBackend.ps1') -Raw
        $launcher | Should -Match 'amd_backend_probe\.py'
        $launcher | Should -Not -Match '-c\s+\$pythonProbe'
    }
}

Describe 'Get-StableAmdTheRockInstallArgs' {
    It 'targets the official multi-arch nightly index and gfx1030 device extra' {
        $args = Get-StableAmdTheRockInstallArgs -GfxTarget 'gfx1030'
        $args.IndexUrl | Should -Be 'https://rocm.nightlies.amd.com/whl-multi-arch/'
        $args.Packages | Should -Contain 'torch[device-gfx1030]'
        $args.Packages | Should -Contain 'torchvision[device-gfx1030]'
        $args.Packages | Should -Contain 'torchaudio'
    }
}

Describe 'TheRock ComfyUI integration gate' {
    It 'uses isolated TheRock Python and a complete git checkout of ComfyUI' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/Test-TheRockComfy.ps1'
        Test-Path $scriptPath | Should -BeTrue

        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'therock-gfx1030'
        $script | Should -Match 'sourceComfyPackage'
        $script | Should -Match 'isolatedComfyPackage'
        $script | Should -Match 'comfy/options\.py'
        $script | Should -Match 'git\.exe'
        $script | Should -Match 'clone'
        $script | Should -Match '--no-hardlinks'
        $script | Should -Match 'system_stats'
        $script | Should -Match 'rocm-sdk-libraries-custom'
        $script | Should -Match 'pip list --format=json'
        $script | Should -Not -Match 'pip show \$legacyPackage'
        $script | Should -Not -Match 'robocopy\.exe'
        $script | Should -Not -Match 'Remove-Item.*SwarmUI[\\/]dlbackend[\\/]comfy'
    }

    It 'launches ComfyUI through a Python bootstrap that injects the isolated checkout into sys.path' {
        $runnerPath = Join-Path $PSScriptRoot '../scripts/probes/run_comfy_isolated.py'
        Test-Path $runnerPath | Should -BeTrue

        $runner = Get-Content $runnerPath -Raw
        $runner | Should -Match 'sys\.path\.insert\(0, comfy_root\)'
        $runner | Should -Match 'runpy\.run_path'

        $script = Get-Content (Join-Path $PSScriptRoot '../scripts/Test-TheRockComfy.ps1') -Raw
        $script | Should -Match 'run_comfy_isolated\.py'
    }
}
