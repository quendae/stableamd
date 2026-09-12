$repoRoot = Split-Path -Parent $PSScriptRoot

Describe 'StableAMD v0.3 SDXL inpainting' {
    It 'declares SDXL inpainting as supported' {
        $catalog = Get-Content -Path (Join-Path $repoRoot 'config/model-support.v0.3.json') -Raw | ConvertFrom-Json
        $catalog.families.sdxl.capabilities.inpaint | Should -Be 'supported'
    }

    It 'builds an SDXL inpaint graph with a resized mask and VAEEncodeForInpaint' {
        $modulePath = Join-Path $repoRoot 'scripts/StableAmd.Inpaint.psm1'
        Test-Path $modulePath -PathType Leaf | Should -BeTrue
        Import-Module $modulePath -Force

        $workflow = New-StableAmdSdxlInpaintWorkflow `
            -CheckpointName 'sd_xl_base_1.0.safetensors' `
            -Prompt 'replace the masked area with red fabric' `
            -InputImageName 'StableAMD_inpaint.png' `
            -Width 1024 `
            -Height 1024 `
            -Steps 20 `
            -Cfg 7 `
            -Seed 123 `
            -SamplerName 'euler' `
            -Scheduler 'normal' `
            -Denoise 0.8

        $workflow['5'].class_type | Should -Be 'LoadImage'
        $workflow['20'].class_type | Should -Be 'MaskToImage'
        $workflow['21'].class_type | Should -Be 'ImageScale'
        $workflow['22'].class_type | Should -Be 'ImageToMask'
        $workflow['19'].class_type | Should -Be 'VAEEncodeForInpaint'
        $workflow['19'].inputs.mask[0] | Should -Be '22'
        $workflow['3'].inputs.latent_image[0] | Should -Be '19'
        $workflow['3'].inputs.denoise | Should -Be 0.8
    }

    It 'routes SDXL inpaint through the workflow provider and keeps LoRA node ids separate' {
        Import-Module (Join-Path $repoRoot 'scripts/StableAmd.Workflows.psm1') -Force
        $stack = @(
            [pscustomobject]@{ name = 'detail.safetensors'; modelStrength = 0.8; clipStrength = 0.7; enabled = $true },
            [pscustomobject]@{ name = 'style.safetensors'; modelStrength = 0.6; clipStrength = 0.5; enabled = $true }
        )

        $workflow = New-StableAmdWorkflow `
            -Family 'sdxl' `
            -Mode 'inpaint' `
            -CheckpointName 'sd_xl_base_1.0.safetensors' `
            -Prompt 'paint only inside the mask' `
            -InputImageName 'StableAMD_inpaint.png' `
            -LoraStack $stack

        $workflow['10'].class_type | Should -Be 'LoraLoader'
        $workflow['11'].class_type | Should -Be 'LoraLoader'
        $workflow['19'].class_type | Should -Be 'VAEEncodeForInpaint'
        $workflow['20'].class_type | Should -Be 'MaskToImage'
    }

    It 'ships browser mask-editor controls and inpaint request handling' {
        $index = Get-Content -Path (Join-Path $repoRoot 'app/frontend/index.html') -Raw
        $script = Join-Path $repoRoot 'app/frontend/app-inpaint.js'
        $index | Should -Match 'app-inpaint\.js'
        Test-Path $script -PathType Leaf | Should -BeTrue

        $source = Get-Content -Path $script -Raw
        $source | Should -Match 'Inpainting'
        $source | Should -Match 'inpaint-mask-canvas'
        $source | Should -Match 'brush'
        $source | Should -Match 'eraser'
        $source | Should -Match 'mode\s*=\s*"inpaint"'
        $source | Should -Match 'inputImage'
    }
}
