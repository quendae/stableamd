BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $modulePath = Join-Path $repoRoot 'scripts/StableAmd.Krea2.psm1'
    $workflowModule = Join-Path $repoRoot 'scripts/StableAmd.Workflows.psm1'
    $profilesPath = Join-Path $repoRoot 'config/generation-profiles.v0.2.json'
}

Describe 'StableAMD v0.3 Krea 2 Turbo provider' {
    It 'builds the official-style flat Turbo txt2img graph' {
        Import-Module $modulePath -Force

        $workflow = New-StableAmdKrea2Workflow `
            -DiffusionModelName 'krea2_turbo_fp8_scaled.safetensors' `
            -TextEncoderName 'qwen3vl_4b_fp8_scaled.safetensors' `
            -VaeName 'qwen_image_vae.safetensors' `
            -Prompt 'editorial portrait' `
            -Width 1024 -Height 1024 -Seed 123

        $workflow['10'].class_type | Should -Be 'UNETLoader'
        $workflow['10'].inputs.unet_name | Should -Be 'krea2_turbo_fp8_scaled.safetensors'
        $workflow['11'].class_type | Should -Be 'CLIPLoader'
        $workflow['11'].inputs.type | Should -Be 'krea2'
        $workflow['11'].inputs.device | Should -Be 'default'
        $workflow['12'].class_type | Should -Be 'VAELoader'
        $workflow['5'].class_type | Should -Be 'EmptyLatentImage'
        $workflow['3'].class_type | Should -Be 'KSampler'
        $workflow['3'].inputs.steps | Should -Be 8
        $workflow['3'].inputs.cfg | Should -Be 1
        $workflow['3'].inputs.sampler_name | Should -Be 'euler'
        $workflow['3'].inputs.scheduler | Should -Be 'simple'
        $workflow['3'].inputs.model | Should -Be @('10', 0)
        $workflow['3'].inputs.positive | Should -Be @('6', 0)
        $workflow['3'].inputs.negative | Should -Be @('13', 0)
        $workflow['8'].class_type | Should -Be 'VAEDecode'
        $workflow['9'].class_type | Should -Be 'SaveImage'
    }

    It 'keeps an explicit CPU text encoder fallback for constrained hosts' {
        Import-Module $modulePath -Force

        $workflow = New-StableAmdKrea2Workflow `
            -DiffusionModelName 'krea2_turbo_fp8_scaled.safetensors' `
            -TextEncoderName 'qwen3vl_4b_fp8_scaled.safetensors' `
            -VaeName 'qwen_image_vae.safetensors' `
            -Prompt 'fallback test' `
            -TextEncoderDevice 'cpu'

        $workflow['11'].inputs.device | Should -Be 'cpu'
    }

    It 'routes krea2 through the shared workflow service and rejects LoRA until enabled' {
        Import-Module $workflowModule -Force

        $workflow = New-StableAmdWorkflow `
            -Family 'krea2' -Mode 'txt2img' `
            -DiffusionModelName 'krea2_turbo_fp8_scaled.safetensors' `
            -TextEncoderName 'qwen3vl_4b_fp8_scaled.safetensors' `
            -VaeName 'qwen_image_vae.safetensors' `
            -Prompt 'test' -Width 1024 -Height 1024 -Steps 8 -Cfg 1 -Seed 1 -SamplerName 'euler' -Scheduler 'simple'

        $workflow['11'].inputs.type | Should -Be 'krea2'

        {
            New-StableAmdWorkflow `
                -Family 'krea2' -Mode 'txt2img' `
                -DiffusionModelName 'krea2_turbo_fp8_scaled.safetensors' `
                -TextEncoderName 'qwen3vl_4b_fp8_scaled.safetensors' `
                -VaeName 'qwen_image_vae.safetensors' `
                -Prompt 'test' `
                -LoraStack @([pscustomobject]@{ name = 'krea2_style.safetensors'; modelStrength = 1.0; enabled = $true })
        } | Should -Throw '*LoRA execution is not enabled*'
    }

    It 'publishes an official Turbo 8-step product preset for the first target test' {
        $catalog = Get-Content -LiteralPath $profilesPath -Raw | ConvertFrom-Json
        $profile = @($catalog.profiles | Where-Object family -eq 'krea2')[0]

        $profile.id | Should -Be 'krea2-turbo'
        $profile.workflowSupport | Should -Be 'supported'
        $profile.defaults.width | Should -Be 1024
        $profile.defaults.height | Should -Be 1024
        $profile.defaults.steps | Should -Be 8
        $profile.defaults.cfg | Should -Be 1
        $profile.defaults.sampler | Should -Be 'euler'
        $profile.defaults.scheduler | Should -Be 'simple'
        @($profile.resolutionTiers).Count | Should -Be 1
        $profile.resolutionTiers[0].recommended | Should -BeTrue
    }

    It 'requires dimensions divisible by 16' {
        Import-Module $modulePath -Force
        {
            New-StableAmdKrea2Workflow `
                -DiffusionModelName 'krea2_turbo_fp8_scaled.safetensors' `
                -TextEncoderName 'qwen3vl_4b_fp8_scaled.safetensors' `
                -VaeName 'qwen_image_vae.safetensors' `
                -Prompt 'test' -Width 1000 -Height 1024
        } | Should -Throw '*divisible by 16*'
    }
}
