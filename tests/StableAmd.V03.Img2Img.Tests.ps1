Describe 'StableAMD v0.3 SDXL img2img' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $workflowsModulePath = Join-Path $repoRoot 'scripts/StableAmd.Workflows.psm1'
        $startPath = Join-Path $repoRoot 'scripts/Start-StableAMD.ps1'
        $invokePath = Join-Path $repoRoot 'scripts/Invoke-Txt2Img.ps1'
        Import-Module $workflowsModulePath -Force
    }

    It 'builds an SDXL img2img graph from a managed input image' {
        $workflow = New-StableAmdWorkflow `
            -Family 'sdxl' `
            -Mode 'img2img' `
            -CheckpointName 'sd_xl_base_1.0.safetensors' `
            -Prompt 'turn this into a watercolor illustration' `
            -InputImageName 'StableAMD_input.png' `
            -Denoise 0.55 `
            -Width 1024 `
            -Height 1024 `
            -Seed 123

        $workflow.'5'.class_type | Should -Be 'LoadImage'
        $workflow.'5'.inputs.image | Should -Be 'StableAMD_input.png'
        $workflow.'18'.class_type | Should -Be 'ImageScale'
        $workflow.'18'.inputs.image | Should -Be @('5', 0)
        $workflow.'18'.inputs.width | Should -Be 1024
        $workflow.'18'.inputs.height | Should -Be 1024
        $workflow.'19'.class_type | Should -Be 'VAEEncode'
        $workflow.'19'.inputs.pixels | Should -Be @('18', 0)
        $workflow.'19'.inputs.vae | Should -Be @('4', 2)
        $workflow.'3'.inputs.latent_image | Should -Be @('19', 0)
        $workflow.'3'.inputs.denoise | Should -Be 0.55
        $workflow.'9'.class_type | Should -Be 'SaveImage'
    }

    It 'keeps ordered multi-LoRA node ids separate from img2img image nodes' {
        $workflow = New-StableAmdWorkflow `
            -Family 'sdxl' `
            -Mode 'img2img' `
            -CheckpointName 'sd_xl_base_1.0.safetensors' `
            -Prompt 'painted cat' `
            -InputImageName 'StableAMD_input.png' `
            -Denoise 0.4 `
            -LoraStack @(
                [pscustomobject]@{ name = 'style.safetensors'; modelStrength = 0.8; clipStrength = 0.7; enabled = $true },
                [pscustomobject]@{ name = 'detail.safetensors'; modelStrength = 0.4; clipStrength = 0.25; enabled = $true }
            )

        $workflow.'10'.class_type | Should -Be 'LoraLoader'
        $workflow.'11'.class_type | Should -Be 'LoraLoader'
        $workflow.'18'.class_type | Should -Be 'ImageScale'
        $workflow.'19'.class_type | Should -Be 'VAEEncode'
        $workflow.'3'.inputs.model | Should -Be @('11', 0)
        $workflow.'6'.inputs.clip | Should -Be @('11', 1)
    }

    It 'rejects img2img without an input image or with invalid denoise' {
        { New-StableAmdWorkflow -Family 'sdxl' -Mode 'img2img' -CheckpointName 'sdxl.safetensors' -Prompt 'cat' -Denoise 0.5 } | Should -Throw '*input image*'
        { New-StableAmdWorkflow -Family 'sdxl' -Mode 'img2img' -CheckpointName 'sdxl.safetensors' -Prompt 'cat' -InputImageName 'x.png' -Denoise 1.1 } | Should -Throw '*Denoise*0*1*'
    }

    It 'runs managed ComfyUI with the StableAMD input directory and accepts img2img command parameters' {
        $start = Get-Content -LiteralPath $startPath -Raw
        $invoke = Get-Content -LiteralPath $invokePath -Raw

        $start | Should -Match '--input-directory'
        $start | Should -Match 'InputRoot'
        $invoke | Should -Match "Mode.*img2img"
        $invoke | Should -Match 'InputImagePath'
        $invoke | Should -Match 'Denoise'
    }
}
