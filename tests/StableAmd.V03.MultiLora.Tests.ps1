Describe 'StableAMD v0.3 multi-LoRA workflow stacking' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $workflowsModulePath = Join-Path $repoRoot 'scripts/StableAmd.Workflows.psm1'
        Import-Module $workflowsModulePath -Force
    }

    It 'chains multiple LoRA loaders in user-defined order' {
        $stack = @(
            [pscustomobject]@{ name = 'style-a.safetensors'; modelStrength = 0.8; clipStrength = 0.7; enabled = $true },
            [pscustomobject]@{ name = 'detail-b.safetensors'; modelStrength = 0.45; clipStrength = 0.3; enabled = $true },
            [pscustomobject]@{ name = 'pose-c.safetensors'; modelStrength = 0.25; clipStrength = 0.2; enabled = $true }
        )

        $workflow = New-StableAmdWorkflow `
            -Family 'sdxl' `
            -Mode 'txt2img' `
            -CheckpointName 'sd_xl_base_1.0.safetensors' `
            -Prompt 'cat' `
            -Seed 123 `
            -LoraStack $stack

        $workflow['10'].class_type | Should -Be 'LoraLoader'
        $workflow['10'].inputs.lora_name | Should -Be 'style-a.safetensors'
        $workflow['10'].inputs.model | Should -Be @('4', 0)
        $workflow['10'].inputs.clip | Should -Be @('4', 1)

        $workflow['11'].inputs.lora_name | Should -Be 'detail-b.safetensors'
        $workflow['11'].inputs.model | Should -Be @('10', 0)
        $workflow['11'].inputs.clip | Should -Be @('10', 1)

        $workflow['12'].inputs.lora_name | Should -Be 'pose-c.safetensors'
        $workflow['12'].inputs.model | Should -Be @('11', 0)
        $workflow['12'].inputs.clip | Should -Be @('11', 1)

        $workflow['3'].inputs.model | Should -Be @('12', 0)
        $workflow['6'].inputs.clip | Should -Be @('12', 1)
        $workflow['7'].inputs.clip | Should -Be @('12', 1)
    }

    It 'keeps legacy single-LoRA calls compatible' {
        $workflow = New-StableAmdWorkflow `
            -Family 'sdxl' `
            -Mode 'txt2img' `
            -CheckpointName 'base.safetensors' `
            -Prompt 'cat' `
            -LoraName 'legacy.safetensors' `
            -LoraModelStrength 0.9 `
            -LoraClipStrength 0.6

        $workflow['10'].inputs.lora_name | Should -Be 'legacy.safetensors'
        $workflow['10'].inputs.strength_model | Should -Be 0.9
        $workflow['10'].inputs.strength_clip | Should -Be 0.6
        $workflow['3'].inputs.model | Should -Be @('10', 0)
    }

    It 'skips disabled entries while preserving deterministic node ids and order' {
        $stack = @(
            [pscustomobject]@{ name = 'one.safetensors'; modelStrength = 1.0; clipStrength = 1.0; enabled = $true },
            [pscustomobject]@{ name = 'disabled.safetensors'; modelStrength = 1.0; clipStrength = 1.0; enabled = $false },
            [pscustomobject]@{ name = 'three.safetensors'; modelStrength = 0.5; clipStrength = 0.5; enabled = $true }
        )

        $workflow = New-StableAmdWorkflow -Family 'sdxl' -Mode 'txt2img' -CheckpointName 'base.safetensors' -Prompt 'cat' -LoraStack $stack

        $workflow.Keys | Should -Contain '10'
        $workflow.Keys | Should -Not -Contain '11'
        $workflow.Keys | Should -Contain '12'
        $workflow['12'].inputs.model | Should -Be @('10', 0)
        $workflow['3'].inputs.model | Should -Be @('12', 0)
    }

    It 'rejects ambiguous legacy plus stack input and excessive stack sizes' {
        $one = @([pscustomobject]@{ name = 'one.safetensors'; modelStrength = 1.0; clipStrength = 1.0 })
        { New-StableAmdWorkflow -Family 'sdxl' -Mode 'txt2img' -CheckpointName 'base.safetensors' -Prompt 'cat' -LoraStack $one -LoraName 'legacy.safetensors' } | Should -Throw '*not both*'

        $tooMany = @(1..9 | ForEach-Object { [pscustomobject]@{ name = "lora-$_.safetensors"; modelStrength = 1.0; clipStrength = 1.0 } })
        { New-StableAmdWorkflow -Family 'sdxl' -Mode 'txt2img' -CheckpointName 'base.safetensors' -Prompt 'cat' -LoraStack $tooMany } | Should -Throw '*at most 8*'
    }
}
