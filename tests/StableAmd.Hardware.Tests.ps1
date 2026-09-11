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
        Resolve-StableAmdSwarmUrl -LogLines @(
            '[Init] Starting webserver on http://localhost:7801'
        ) | Should -Be 'http://127.0.0.1:7801/'
    }

    It 'returns null before the server URL appears in the log' {
        Resolve-StableAmdSwarmUrl -LogLines @(
            '[Init] Prepping webserver...',
            '[Init] Launching server...'
        ) | Should -BeNullOrEmpty
    }
}
