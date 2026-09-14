Describe 'StableAMD v0.3 logical model packages' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    }

    It 'keeps a Z-Image package visible when only some required assets are present' {
        Import-Module (Join-Path $repoRoot 'scripts/StableAmd.TemplateBundles.psm1') -Force

        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-packages-' + [guid]::NewGuid().ToString('N'))
        $diffusionRoot = Join-Path $tempRoot 'diffusion_models'
        $textRoot = Join-Path $tempRoot 'text_encoders'
        $vaeRoot = Join-Path $tempRoot 'vae'
        New-Item -ItemType Directory -Path $diffusionRoot,$textRoot,$vaeRoot -Force | Out-Null
        try {
            Set-Content -LiteralPath (Join-Path $diffusionRoot 'z_image_turbo_bf16.safetensors') -Value 'x'

            $packages = @(Find-StableAmdTemplatePackages -DiffusionRoots @($diffusionRoot) -TextEncoderRoots @($textRoot) -VaeRoots @($vaeRoot))
            $package = @($packages | Where-Object family -eq 'z-image-turbo')[0]
            $package.name | Should -Be 'Z-Image Turbo'
            $package.ready | Should -BeFalse
            $package.status | Should -Be 'incomplete'
            @($package.components).Count | Should -Be 3
            (@($package.components | Where-Object role -eq 'diffusion_model'))[0].present | Should -BeTrue
            (@($package.components | Where-Object role -eq 'text_encoder'))[0].present | Should -BeFalse
            (@($package.components | Where-Object role -eq 'vae'))[0].present | Should -BeFalse
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'marks the Z-Image package ready only when all official template assets are present' {
        Import-Module (Join-Path $repoRoot 'scripts/StableAmd.TemplateBundles.psm1') -Force

        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-packages-ready-' + [guid]::NewGuid().ToString('N'))
        $diffusionRoot = Join-Path $tempRoot 'diffusion_models'
        $textRoot = Join-Path $tempRoot 'text_encoders'
        $vaeRoot = Join-Path $tempRoot 'vae'
        New-Item -ItemType Directory -Path $diffusionRoot,$textRoot,$vaeRoot -Force | Out-Null
        try {
            Set-Content -LiteralPath (Join-Path $diffusionRoot 'z_image_turbo_bf16.safetensors') -Value 'x'
            Set-Content -LiteralPath (Join-Path $textRoot 'qwen_3_4b.safetensors') -Value 'x'
            Set-Content -LiteralPath (Join-Path $vaeRoot 'ae.safetensors') -Value 'x'

            $packages = @(Find-StableAmdTemplatePackages -DiffusionRoots @($diffusionRoot) -TextEncoderRoots @($textRoot) -VaeRoots @($vaeRoot))
            $package = @($packages | Where-Object family -eq 'z-image-turbo')[0]
            $package.ready | Should -BeTrue
            $package.status | Should -Be 'ready'
            [IO.Path]::GetFileName([string]$package.assets.diffusion_model[0]) | Should -Be 'z_image_turbo_bf16.safetensors'
            [IO.Path]::GetFileName([string]$package.assets.text_encoder[0]) | Should -Be 'qwen_3_4b.safetensors'
            [IO.Path]::GetFileName([string]$package.assets.vae[0]) | Should -Be 'ae.safetensors'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'discovers Krea 2 Turbo FP8 as a three-asset logical package' {
        Import-Module (Join-Path $repoRoot 'scripts/StableAmd.TemplateBundles.psm1') -Force

        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-packages-krea-' + [guid]::NewGuid().ToString('N'))
        $diffusionRoot = Join-Path $tempRoot 'diffusion_models'
        $textRoot = Join-Path $tempRoot 'text_encoders'
        $vaeRoot = Join-Path $tempRoot 'vae'
        New-Item -ItemType Directory -Path $diffusionRoot,$textRoot,$vaeRoot -Force | Out-Null
        try {
            Set-Content -LiteralPath (Join-Path $diffusionRoot 'krea2_turbo_fp8_scaled.safetensors') -Value 'x'
            Set-Content -LiteralPath (Join-Path $textRoot 'qwen3vl_4b_fp8_scaled.safetensors') -Value 'x'
            Set-Content -LiteralPath (Join-Path $vaeRoot 'qwen_image_vae.safetensors') -Value 'x'

            $packages = @(Find-StableAmdTemplatePackages -DiffusionRoots @($diffusionRoot) -TextEncoderRoots @($textRoot) -VaeRoots @($vaeRoot))
            $package = @($packages | Where-Object family -eq 'krea2')[0]
            $package.name | Should -Be 'Krea 2 Turbo (FP8)'
            $package.provider | Should -Be 'krea2-bundle'
            $package.ready | Should -BeTrue
            [IO.Path]::GetFileName([string]$package.assets.diffusion_model[0]) | Should -Be 'krea2_turbo_fp8_scaled.safetensors'
            [IO.Path]::GetFileName([string]$package.assets.text_encoder[0]) | Should -Be 'qwen3vl_4b_fp8_scaled.safetensors'
            [IO.Path]::GetFileName([string]$package.assets.vae[0]) | Should -Be 'qwen_image_vae.safetensors'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'keeps package discovery on the existing product model API and persists only ready bundles for execution' {
        $bundleScript = Get-Content -LiteralPath (Join-Path $repoRoot 'scripts/List-BundleModels.ps1') -Raw
        $server = Get-Content -LiteralPath (Join-Path $repoRoot 'app/backend/stableamd_v03_server.py') -Raw

        $bundleScript | Should -Match 'Find-StableAmdTemplatePackages'
        $bundleScript | Should -Match '\.ready'
        $bundleScript | Should -Match 'readyBundles'
        $server | Should -Match 'List-BundleModels\.ps1'
        $server | Should -Not -Match '/api/model-packages'
    }

    It 'presents logical model packages first and moves raw asset folders under Advanced' {
        $frontend = Get-Content -LiteralPath (Join-Path $repoRoot 'app/frontend/app-v03.js') -Raw

        $frontend | Should -Match '/api/models'
        $frontend | Should -Match 'Model packages'
        $frontend | Should -Match 'Advanced model asset folders'
        $frontend | Should -Match 'model-package-list'
        $frontend | Should -Match 'package-component'
        $frontend | Should -Match 'window\.renderModels'
        $frontend | Should -Match 'capabilities.*txt2img'
    }
}
