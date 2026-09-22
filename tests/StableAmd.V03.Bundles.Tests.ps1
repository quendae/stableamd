Describe 'StableAMD v0.3 bundle registry primitives' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $modulePath = Join-Path $repoRoot 'scripts/StableAmd.Bundles.psm1'
        Import-Module $modulePath -Force
    }

    It 'creates deterministic logical bundle ids' {
        $first = Get-StableAmdBundleId -Family 'flux' -Name 'FLUX.1 Dev'
        $second = Get-StableAmdBundleId -Family 'FLUX' -Name 'flux.1 dev'

        $first | Should -Be $second
        $first | Should -Match '^bnd_[0-9a-f]{16}$'
    }

    It 'represents a modern model as one logical bundle with multiple asset roles' {
        $entry = New-StableAmdBundleEntry -Family 'flux' -Name 'FLUX.1 Dev' -Provider 'flux-bundle' -Assets @{
            diffusion_model = @('C:\AI\diffusion_models\flux1-dev.safetensors')
            text_encoder = @('C:\AI\text_encoders\clip_l.safetensors', 'C:\AI\text_encoders\t5xxl.safetensors')
            vae = @('C:\AI\vae\ae.safetensors')
        }

        $entry.family | Should -Be 'flux'
        $entry.assetMode | Should -Be 'bundle'
        @($entry.assets.diffusion_model).Count | Should -Be 1
        @($entry.assets.text_encoder).Count | Should -Be 2
        @($entry.assets.vae).Count | Should -Be 1

        $validation = Test-StableAmdBundleEntry -Entry $entry -RequiredRoles @('diffusion_model', 'text_encoder', 'vae')
        $validation.complete | Should -BeTrue
        @($validation.missingRoles).Count | Should -Be 0
    }

    It 'reports incomplete bundles instead of guessing missing assets' {
        $entry = New-StableAmdBundleEntry -Family 'krea2' -Name 'Krea 2' -Provider 'krea2-bundle' -Assets @{
            diffusion_model = @('C:\AI\diffusion_models\krea2.safetensors')
        }

        $validation = Test-StableAmdBundleEntry -Entry $entry -RequiredRoles @('diffusion_model', 'text_encoder', 'vae')
        $validation.complete | Should -BeFalse
        @($validation.missingRoles) | Should -Contain 'text_encoder'
        @($validation.missingRoles) | Should -Contain 'vae'
    }

    It 'round-trips and upserts the bundle registry' {
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-bundles-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        try {
            $path = Join-Path $tempRoot 'bundles.json'
            $registry = New-StableAmdEmptyBundleRegistry
            $entry = New-StableAmdBundleEntry -Family 'flux' -Name 'FLUX.1 Dev' -Assets @{
                diffusion_model = @('C:\AI\flux.safetensors')
                text_encoder = @('C:\AI\clip.safetensors')
                vae = @('C:\AI\ae.safetensors')
            }
            $updated = Upsert-StableAmdBundleRegistryEntry -Registry $registry -Entry $entry
            Write-StableAmdBundleRegistry -Path $path -Registry $updated
            $read = Read-StableAmdBundleRegistry -Path $path

            @($read.bundles).Count | Should -Be 1
            $read.bundles[0].id | Should -Be $entry.id
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'discovers bundle assets by role without mixing the logical model layer' {
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-assets-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        try {
            Set-Content -LiteralPath (Join-Path $tempRoot 'encoder.safetensors') -Value 'x' -Encoding UTF8
            Set-Content -LiteralPath (Join-Path $tempRoot 'ignore.txt') -Value 'x' -Encoding UTF8

            $assets = @(Find-StableAmdBundleAssets -Role 'text_encoder' -Roots @($tempRoot))
            $assets.Count | Should -Be 1
            $assets[0].role | Should -Be 'text_encoder'
            $assets[0].name | Should -Be 'encoder.safetensors'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
