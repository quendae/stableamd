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

Describe 'StableAMD model installation helpers' {
    It 'builds the canonical Hugging Face resolve URL' {
        $url = Resolve-StableAmdHuggingFaceUrl -RepositoryId 'stabilityai/stable-diffusion-xl-base-1.0' -Filename 'sd_xl_base_1.0.safetensors' -Revision 'main'
        $url | Should -Be 'https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors?download=true'
    }

    It 'chooses a collision-safe destination name' {
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-model-destination-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        try {
            $first = Join-Path $tempRoot 'model.safetensors'
            Set-Content -Path $first -Value 'existing'

            $destination = Get-StableAmdModelDestinationPath -DestinationRoot $tempRoot -FileName 'model.safetensors'
            $destination | Should -Be (Join-Path $tempRoot 'model-1.safetensors')
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'verifies SHA256 case-insensitively' {
        $tempFile = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-hash-' + [guid]::NewGuid().ToString('N') + '.bin')
        try {
            [IO.File]::WriteAllText($tempFile, 'stableamd')
            $actual = (Get-FileHash -Path $tempFile -Algorithm SHA256).Hash
            Test-StableAmdModelSha256 -Path $tempFile -ExpectedSha256 $actual.ToLowerInvariant() | Should -BeTrue
            Test-StableAmdModelSha256 -Path $tempFile -ExpectedSha256 ('0' * 64) | Should -BeFalse
        }
        finally {
            Remove-Item -Path $tempFile -Force -ErrorAction SilentlyContinue
        }
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

    It 'accepts a .safetensors.partial staging file for validation before atomic install' {
        $script = Get-Content (Join-Path $PSScriptRoot '../scripts/Validate-Model.ps1') -Raw
        $script | Should -Match 'safetensors.*partial'
    }

    It 'lists configured model roots and updates the generated registry' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/List-Models.ps1'
        Test-Path $scriptPath | Should -BeTrue
        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'Find-StableAmdCheckpoints'
        $script | Should -Match 'ModelsRegistryPath'
        $script | Should -Match 'Write-StableAmdModelRegistry'
    }

    It 'installs local or Hugging Face models with resume validation and source metadata' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/Install-Model.ps1'
        Test-Path $scriptPath | Should -BeTrue
        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'HuggingFace'
        $script | Should -Match 'LocalPath'
        $script | Should -Match '\.partial'
        $script | Should -Match 'Range'
        $script | Should -Match 'Validate-Model\.ps1'
        $script | Should -Match "'huggingface'|'local'"
        $script | Should -Match 'Write-StableAmdModelRegistry'
    }
}
