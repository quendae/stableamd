Describe 'StableAMD v0.3 workflow provider foundation' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $familiesModulePath = Join-Path $repoRoot 'scripts/StableAmd.ModelFamilies.psm1'
        $workflowsModulePath = Join-Path $repoRoot 'scripts/StableAmd.Workflows.psm1'
    }

    It 'recognizes current Stable Diffusion, FLUX and Krea-family checkpoint names conservatively' {
        Import-Module $familiesModulePath -Force

        Get-StableAmdModelFamily -Name 'v1-5-pruned.safetensors' | Should -Be 'sd15'
        Get-StableAmdModelFamily -Name 'stable-diffusion-2-1.safetensors' | Should -Be 'sd21'
        Get-StableAmdModelFamily -Name 'sd_xl_base_1.0.safetensors' | Should -Be 'sdxl'
        Get-StableAmdModelFamily -Name 'sdxl_turbo_1.0.safetensors' | Should -Be 'sdxl-turbo'
        Get-StableAmdModelFamily -Name 'sd3_medium.safetensors' | Should -Be 'sd3'
        Get-StableAmdModelFamily -Name 'sd3.5_large.safetensors' | Should -Be 'sd35-large'
        Get-StableAmdModelFamily -Name 'flux1-dev.safetensors' | Should -Be 'flux'
        Get-StableAmdModelFamily -Name 'krea2-dev.safetensors' | Should -Be 'krea2'
        Get-StableAmdModelFamily -Name 'mystery-model.safetensors' | Should -Be 'unknown'
    }

    It 'routes the proven SDXL txt2img graph through a provider dispatcher' {
        Test-Path $workflowsModulePath | Should -BeTrue
        Import-Module $workflowsModulePath -Force

        $workflow = New-StableAmdWorkflow `
            -Family 'sdxl' `
            -Mode 'txt2img' `
            -CheckpointName 'sd_xl_base_1.0.safetensors' `
            -Prompt 'a red biplane' `
            -Seed 123

        $workflow.'4'.class_type | Should -Be 'CheckpointLoaderSimple'
        $workflow.'3'.class_type | Should -Be 'KSampler'
        $workflow.'9'.class_type | Should -Be 'SaveImage'
    }

    It 'fails explicitly for planned families or generation modes instead of guessing a graph' {
        Import-Module $workflowsModulePath -Force

        { New-StableAmdWorkflow -Family 'flux' -Mode 'txt2img' -CheckpointName 'flux.safetensors' -Prompt 'cat' } | Should -Throw '*not implemented*'
        { New-StableAmdWorkflow -Family 'sdxl' -Mode 'controlnet' -CheckpointName 'sdxl.safetensors' -Prompt 'cat' } | Should -Throw '*not implemented*'
    }
}
