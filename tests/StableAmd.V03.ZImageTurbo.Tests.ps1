Describe 'StableAMD v0.3 Z-Image Turbo provider' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    }

    It 'declares Z-Image Turbo txt2img and model-only LoRA as supported' {
        $catalog = Get-Content -Path (Join-Path $repoRoot 'config/model-support.v0.3.json') -Raw | ConvertFrom-Json
        $family = $catalog.families.'z-image-turbo'

        $family | Should -Not -BeNullOrEmpty
        $family.assetMode | Should -Be 'bundle'
        @($family.requiredAssetRoles) | Should -Be @('diffusion_model', 'text_encoder', 'vae')
        $family.capabilities.txt2img | Should -Be 'supported'
        $family.capabilities.img2img | Should -Be 'planned'
        $family.capabilities.lora | Should -Be 'supported'
        $family.loraPolicy.orderedStack | Should -BeTrue
        $family.loraPolicy.maxStack | Should -Be 8
        $family.loraPolicy.perEntryModelStrength | Should -BeTrue
        $family.loraPolicy.perEntryClipStrength | Should -BeFalse
    }

    It 'builds the official ComfyUI Z-Image Turbo txt2img graph with bounded VAE decode' {
        $modulePath = Join-Path $repoRoot 'scripts/StableAmd.ZImageTurbo.psm1'
        Test-Path $modulePath -PathType Leaf | Should -BeTrue
        Import-Module $modulePath -Force

        $workflow = New-StableAmdZImageTurboWorkflow `
            -DiffusionModelName 'z_image_turbo_bf16.safetensors' `
            -TextEncoderName 'qwen_3_4b.safetensors' `
            -VaeName 'ae.safetensors' `
            -Prompt 'a red biplane' `
            -Width 1024 `
            -Height 1024 `
            -Seed 123

        $workflow['28'].class_type | Should -Be 'UNETLoader'
        $workflow['28'].inputs.unet_name | Should -Be 'z_image_turbo_bf16.safetensors'
        $workflow['28'].inputs.weight_dtype | Should -Be 'default'
        $workflow['30'].class_type | Should -Be 'CLIPLoader'
        $workflow['30'].inputs.clip_name | Should -Be 'qwen_3_4b.safetensors'
        $workflow['30'].inputs.type | Should -Be 'lumina2'
        $workflow['30'].inputs.device | Should -Be 'cpu'
        $workflow['29'].class_type | Should -Be 'VAELoader'
        $workflow['27'].class_type | Should -Be 'CLIPTextEncode'
        $workflow['33'].class_type | Should -Be 'ConditioningZeroOut'
        $workflow['13'].class_type | Should -Be 'EmptySD3LatentImage'
        $workflow['11'].class_type | Should -Be 'ModelSamplingAuraFlow'
        $workflow['11'].inputs.shift | Should -Be 3
        $workflow['3'].class_type | Should -Be 'KSampler'
        $workflow['3'].inputs.steps | Should -Be 8
        $workflow['3'].inputs.cfg | Should -Be 1
        $workflow['3'].inputs.sampler_name | Should -Be 'res_multistep'
        $workflow['3'].inputs.scheduler | Should -Be 'simple'
        $workflow['8'].class_type | Should -Be 'VAEDecodeTiled'
        $workflow['8'].inputs.tile_size | Should -Be 512
        $workflow['8'].inputs.overlap | Should -Be 64
        $workflow['8'].inputs.temporal_size | Should -Be 64
        $workflow['8'].inputs.temporal_overlap | Should -Be 8
        $workflow['9'].class_type | Should -Be 'SaveImage'
    }

    It 'chains Z-Image LoRAs through the diffusion model only' {
        Import-Module (Join-Path $repoRoot 'scripts/StableAmd.Workflows.psm1') -Force

        $stack = @(
            [pscustomobject]@{ name = 'z-image/style-a.safetensors'; modelStrength = 0.8; clipStrength = 0.3; enabled = $true },
            [pscustomobject]@{ name = 'z-image/style-b.safetensors'; modelStrength = 1.1; clipStrength = 0.7; enabled = $true }
        )
        $workflow = New-StableAmdWorkflow `
            -Family 'z-image-turbo' `
            -Mode 'txt2img' `
            -Prompt 'a lighthouse at sunset' `
            -DiffusionModelName 'z_image_turbo_bf16.safetensors' `
            -TextEncoderName 'qwen_3_4b.safetensors' `
            -VaeName 'ae.safetensors' `
            -LoraStack $stack `
            -Seed 42

        $workflow['40'].class_type | Should -Be 'LoraLoaderModelOnly'
        $workflow['40'].inputs.lora_name | Should -Be 'z-image/style-a.safetensors'
        $workflow['40'].inputs.strength_model | Should -Be 0.8
        @($workflow['40'].inputs.model) | Should -Be @('28', 0)
        $workflow['41'].class_type | Should -Be 'LoraLoaderModelOnly'
        @($workflow['41'].inputs.model) | Should -Be @('40', 0)
        @($workflow['11'].inputs.model) | Should -Be @('41', 0)
        @($workflow['27'].inputs.clip) | Should -Be @('30', 0)
        $workflow['40'].inputs.PSObject.Properties.Name | Should -Not -Contain 'strength_clip'
        $workflow['41'].inputs.PSObject.Properties.Name | Should -Not -Contain 'clip'
    }

    It 'discovers the exact official template asset trio as one logical model' {
        Import-Module (Join-Path $repoRoot 'scripts/StableAmd.TemplateBundles.psm1') -Force

        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-zimage-' + [guid]::NewGuid().ToString('N'))
        $diffusionRoot = Join-Path $tempRoot 'diffusion_models'
        $textRoot = Join-Path $tempRoot 'text_encoders'
        $vaeRoot = Join-Path $tempRoot 'vae'
        New-Item -ItemType Directory -Path $diffusionRoot,$textRoot,$vaeRoot -Force | Out-Null
        try {
            Set-Content -LiteralPath (Join-Path $diffusionRoot 'z_image_turbo_bf16.safetensors') -Value 'x'
            Set-Content -LiteralPath (Join-Path $textRoot 'qwen_3_4b.safetensors') -Value 'x'
            Set-Content -LiteralPath (Join-Path $vaeRoot 'ae.safetensors') -Value 'x'

            $bundles = @(Find-StableAmdTemplateBundles -DiffusionRoots @($diffusionRoot) -TextEncoderRoots @($textRoot) -VaeRoots @($vaeRoot))
            $bundles.Count | Should -Be 1
            $bundles[0].family | Should -Be 'z-image-turbo'
            $bundles[0].provider | Should -Be 'z-image-turbo-bundle'
            $bundles[0].assetMode | Should -Be 'bundle'
            [IO.Path]::GetFileName([string]$bundles[0].assets.diffusion_model[0]) | Should -Be 'z_image_turbo_bf16.safetensors'
            [IO.Path]::GetFileName([string]$bundles[0].assets.text_encoder[0]) | Should -Be 'qwen_3_4b.safetensors'
            [IO.Path]::GetFileName([string]$bundles[0].assets.vae[0]) | Should -Be 'ae.safetensors'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'ships a command that scans configured bundle roots and persists logical models' {
        $script = Get-Content -Path (Join-Path $repoRoot 'scripts/List-BundleModels.ps1') -Raw
        $script | Should -Match 'Get-StableAmdBundleAssetRootRecords'
        $script | Should -Match 'Find-StableAmdTemplateBundles'
        $script | Should -Match 'Test-StableAmdBundleEntry'
        $script | Should -Match 'Write-StableAmdBundleRegistry'
        $script | Should -Match 'BundlesRegistryPath'
    }

    It 'routes Z-Image Turbo through the workflow dispatcher' {
        Import-Module (Join-Path $repoRoot 'scripts/StableAmd.Workflows.psm1') -Force

        $workflow = New-StableAmdWorkflow `
            -Family 'z-image-turbo' `
            -Mode 'txt2img' `
            -Prompt 'a lighthouse at sunset' `
            -DiffusionModelName 'z_image_turbo_bf16.safetensors' `
            -TextEncoderName 'qwen_3_4b.safetensors' `
            -VaeName 'ae.safetensors' `
            -Seed 42

        $workflow['28'].class_type | Should -Be 'UNETLoader'
        $workflow['30'].class_type | Should -Be 'CLIPLoader'
        $workflow['30'].inputs.device | Should -Be 'cpu'
        $workflow['3'].inputs.steps | Should -Be 8
        $workflow['8'].class_type | Should -Be 'VAEDecodeTiled'
    }

    It 'ships a generation profile matching the official 8-step template' {
        $profiles = Get-Content -Path (Join-Path $repoRoot 'config/generation-profiles.v0.2.json') -Raw | ConvertFrom-Json
        $profile = @($profiles.profiles | Where-Object { $_.family -eq 'z-image-turbo' }) | Select-Object -First 1

        $profile | Should -Not -BeNullOrEmpty
        $profile.workflowSupport | Should -Be 'supported'
        $profile.defaults.width | Should -Be 1024
        $profile.defaults.height | Should -Be 1024
        $profile.defaults.steps | Should -Be 8
        $profile.defaults.cfg | Should -Be 1
        $profile.defaults.sampler | Should -Be 'res_multistep'
        $profile.defaults.scheduler | Should -Be 'simple'
    }
}
