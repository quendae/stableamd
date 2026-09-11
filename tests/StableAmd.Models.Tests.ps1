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

    It 'merges an empty discovery result into an empty registry' {
        $registry = New-StableAmdEmptyModelRegistry
        $merged = Merge-StableAmdModelRegistry -ExistingRegistry $registry -DiscoveredModels @()

        $merged.schemaVersion | Should -Be 1
        @($merged.models).Count | Should -Be 0
    }

    It 'upserts a model into an empty registry without generic-list conversion errors' {
        $registry = New-StableAmdEmptyModelRegistry
        $entry = [pscustomobject]@{
            id = 'mdl_deadbeefdeadbeef'
            name = 'model.safetensors'
            path = 'C:\AI\model.safetensors'
            family = 'sdxl'
        }

        $updated = Upsert-StableAmdModelRegistryEntry -Registry $registry -Entry $entry
        @($updated.models).Count | Should -Be 1
        $updated.models[0].id | Should -Be 'mdl_deadbeefdeadbeef'
    }

    It 'upserts successfully under Windows PowerShell 5.1' {
        $windowsPowerShell = Get-Command powershell.exe -ErrorAction SilentlyContinue
        if ($null -eq $windowsPowerShell) {
            Set-ItResult -Skipped -Because 'powershell.exe is unavailable'
            return
        }

        $tempScript = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-ps5-upsert-' + [guid]::NewGuid().ToString('N') + '.ps1')
        $escapedModule = $modulePath.Replace("'", "''")
        @"
`$ErrorActionPreference = 'Stop'
Import-Module '$escapedModule' -Force
`$registry = New-StableAmdEmptyModelRegistry
`$entry = [pscustomobject]@{ id='mdl_deadbeefdeadbeef'; name='model.safetensors'; path='C:\AI\model.safetensors'; family='sdxl' }
`$updated = Upsert-StableAmdModelRegistryEntry -Registry `$registry -Entry `$entry
if (@(`$updated.models).Count -ne 1) { throw 'upsert count mismatch' }
"@ | Set-Content -Path $tempScript -Encoding UTF8
        try {
            & $windowsPowerShell.Source -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $tempScript
            $LASTEXITCODE | Should -Be 0
        }
        finally {
            Remove-Item -Path $tempScript -Force -ErrorAction SilentlyContinue
        }
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

Describe 'StableAMD model folder commands' {
    It 'adds lists and removes an external model folder without copying model files' {
        $addScript = Join-Path $PSScriptRoot '../scripts/Add-ModelRoot.ps1'
        $getScript = Join-Path $PSScriptRoot '../scripts/Get-ModelRoots.ps1'
        $removeScript = Join-Path $PSScriptRoot '../scripts/Remove-ModelRoot.ps1'
        $browseScript = Join-Path $PSScriptRoot '../scripts/Browse-ModelRoot.ps1'
        foreach ($path in @($addScript, $getScript, $removeScript, $browseScript)) { Test-Path $path | Should -BeTrue }

        $tempRepo = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-model-roots-' + [guid]::NewGuid().ToString('N'))
        $externalRoot = Join-Path $tempRepo 'external-models'
        New-Item -ItemType Directory -Path $externalRoot -Force | Out-Null
        try {
            $added = & $addScript -RepoRoot $tempRepo -Path $externalRoot
            $added.added | Should -BeTrue
            $added.path | Should -Be ([IO.Path]::GetFullPath($externalRoot))

            $roots = @(& $getScript -RepoRoot $tempRepo)
            @($roots | Where-Object { $_.path -eq [IO.Path]::GetFullPath($externalRoot) }).Count | Should -Be 1

            $removed = & $removeScript -RepoRoot $tempRepo -Path $externalRoot
            $removed.removed | Should -BeTrue
            $rootsAfter = @(& $getScript -RepoRoot $tempRepo)
            @($rootsAfter | Where-Object { $_.path -eq [IO.Path]::GetFullPath($externalRoot) }).Count | Should -Be 0
        }
        finally {
            Remove-Item -Path $tempRepo -Recurse -Force -ErrorAction SilentlyContinue
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

    It 'starts ComfyUI with every configured model root as an external checkpoint path' {
        $script = Get-Content (Join-Path $PSScriptRoot '../scripts/Start-StableAMD.ps1') -Raw
        $script | Should -Match 'config\.models\.roots'
        $script | Should -Match 'checkpoints:\s*\.'
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
