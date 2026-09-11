BeforeAll {
    $modulePath = Join-Path $PSScriptRoot '../scripts/StableAmd.Models.psm1'
    Import-Module $modulePath -Force
}

Describe 'StableAMD model registry primitives' {
    It 'creates a deterministic model id from a normalized path' {
        $first = Get-StableAmdModelId -Path 'C:\AI\Models\Example.safetensors'
        $second = Get-StableAmdModelId -Path 'c:\ai\models\example.safetensors'

        $first | Should -Be $second
        $first | Should -Match '^mdl_[0-9a-f]{16}$'
    }

    It 'recognizes common SDXL checkpoint names conservatively' {
        Get-StableAmdModelFamily -Name 'sd_xl_base_1.0.safetensors' | Should -Be 'sdxl'
        Get-StableAmdModelFamily -Name 'juggernautXL_v9.safetensors' | Should -Be 'sdxl'
        Get-StableAmdModelFamily -Name 'mystery-model.safetensors' | Should -Be 'unknown'
    }

    It 'round-trips a model registry' {
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-model-registry-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        try {
            $registryPath = Join-Path $tempRoot 'models.json'
            $registry = [pscustomobject]@{
                schemaVersion = 1
                models = @(
                    [pscustomobject]@{
                        id = 'mdl_0123456789abcdef'
                        name = 'Example'
                        path = 'C:\AI\Example.safetensors'
                        family = 'unknown'
                    }
                )
            }

            Write-StableAmdModelRegistry -Path $registryPath -Registry $registry
            $read = Read-StableAmdModelRegistry -Path $registryPath

            $read.schemaVersion | Should -Be 1
            @($read.models).Count | Should -Be 1
            $read.models[0].id | Should -Be 'mdl_0123456789abcdef'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'returns an empty registry when the registry file is missing' {
        $missing = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-models-missing-' + [guid]::NewGuid().ToString('N') + '.json')
        $registry = Read-StableAmdModelRegistry -Path $missing

        $registry.schemaVersion | Should -Be 1
        @($registry.models).Count | Should -Be 0
    }
}

Describe 'StableAMD checkpoint discovery' {
    It 'finds safetensors recursively and de-duplicates overlapping roots' {
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-model-discovery-' + [guid]::NewGuid().ToString('N'))
        $nested = Join-Path $tempRoot 'nested'
        New-Item -ItemType Directory -Path $nested -Force | Out-Null
        try {
            $first = Join-Path $tempRoot 'sd_xl_base_1.0.safetensors'
            $second = Join-Path $nested 'other.safetensors'
            $ignored = Join-Path $nested 'notes.txt'
            Set-Content -Path $first -Value 'x'
            Set-Content -Path $second -Value 'y'
            Set-Content -Path $ignored -Value 'z'

            $found = @(Find-StableAmdCheckpoints -Roots @($tempRoot, $nested))

            $found.Count | Should -Be 2
            @($found | Where-Object { $_.Path -eq [IO.Path]::GetFullPath($first) }).Count | Should -Be 1
            @($found | Where-Object { $_.Path -eq [IO.Path]::GetFullPath($second) }).Count | Should -Be 1
            ($found | Where-Object { $_.Path -eq [IO.Path]::GetFullPath($first) }).Family | Should -Be 'sdxl'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'ignores missing roots instead of failing discovery' {
        $missing = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-root-missing-' + [guid]::NewGuid().ToString('N'))
        @(Find-StableAmdCheckpoints -Roots @($missing)).Count | Should -Be 0
    }
}

Describe 'StableAMD model command scripts' {
    It 'validates safetensors through the existing structural validator' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/Validate-Model.ps1'
        Test-Path $scriptPath | Should -BeTrue
        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'validate_safetensors\.py'
        $script | Should -Match 'TheRockPython'
    }

    It 'lists configured model roots and updates the generated registry' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/List-Models.ps1'
        Test-Path $scriptPath | Should -BeTrue
        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'Find-StableAmdCheckpoints'
        $script | Should -Match 'ModelsRegistryPath'
        $script | Should -Match 'Write-StableAmdModelRegistry'
    }
}
