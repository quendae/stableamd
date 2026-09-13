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
            $packages.Count | Should -Be 1
            $packages[0].name | Should -Be 'Z-Image Turbo'
            $packages[0].ready | Should -BeFalse
            $packages[0].status | Should -Be 'incomplete'
            @($packages[0].components).Count | Should -Be 3
            (@($packages[0].components | Where-Object role -eq 'diffusion_model'))[0].present | Should -BeTrue
            (@($packages[0].components | Where-Object role -eq 'text_encoder'))[0].present | Should -BeFalse
            (@($packages[0].components | Where-Object role -eq 'vae'))[0].present | Should -BeFalse
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
            $packages[0].ready | Should -BeTrue
            $packages[0].status | Should -Be 'ready'
            [IO.Path]::GetFileName([string]$packages[0].assets.diffusion_model[0]) | Should -Be 'z_image_turbo_bf16.safetensors'
            [IO.Path]::GetFileName([string]$packages[0].assets.text_encoder[0]) | Should -Be 'qwen_3_4b.safetensors'
            [IO.Path]::GetFileName([string]$packages[0].assets.vae[0]) | Should -Be 'ae.safetensors'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'ships a unified model-package product endpoint while generation receives ready bundle models only' {
        $packageScriptPath = Join-Path $repoRoot 'scripts/List-ModelPackages.ps1'
        Test-Path $packageScriptPath -PathType Leaf | Should -BeTrue
        $packageScript = Get-Content -LiteralPath $packageScriptPath -Raw
        $bundleScript = Get-Content -LiteralPath (Join-Path $repoRoot 'scripts/List-BundleModels.ps1') -Raw
        $server = Get-Content -LiteralPath (Join-Path $repoRoot 'app/backend/stableamd_v03_server.py') -Raw

        $packageScript | Should -Match 'Find-StableAmdTemplatePackages'
        $packageScript | Should -Match 'List-Models\.ps1'
        $bundleScript | Should -Match 'Find-StableAmdTemplatePackages'
        $bundleScript | Should -Match '\.ready'
        $server | Should -Match 'model_packages'
        $server | Should -Match '/api/model-packages'
    }

    It 'presents logical model packages first and moves raw asset folders under Advanced' {
        $frontend = Get-Content -LiteralPath (Join-Path $repoRoot 'app/frontend/app-v03.js') -Raw
        $baseFrontend = Get-Content -LiteralPath (Join-Path $repoRoot 'app/frontend/app.js') -Raw
        $index = Get-Content -LiteralPath (Join-Path $repoRoot 'app/frontend/index.html') -Raw

        $frontend | Should -Match '/api/model-packages'
        $frontend | Should -Match 'Model packages'
        $frontend | Should -Match 'Advanced model asset folders'
        $frontend | Should -Match 'package-component'
        $index | Should -Match 'model-package-list'
        $baseFrontend | Should -Not -Match 'const sdxl = models\.filter'
    }
}
