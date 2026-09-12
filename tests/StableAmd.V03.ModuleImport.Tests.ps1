Describe 'StableAMD v0.3 module import composition' {
    It 'keeps generation helper commands available after workflow modules load' {
        $generationModule = Join-Path $PSScriptRoot '../scripts/StableAmd.Generation.psm1'
        $workflowsModule = Join-Path $PSScriptRoot '../scripts/StableAmd.Workflows.psm1'

        Remove-Module StableAmd.Workflows, StableAmd.Img2Img, StableAmd.Generation -Force -ErrorAction SilentlyContinue
        try {
            Import-Module $generationModule -Force
            Import-Module $workflowsModule -Force

            Get-Command New-StableAmdRandomSeed -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
            Get-Command Resolve-StableAmdComfyCheckpointName -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
            Get-Command Resolve-StableAmdGeneratedImagePath -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
        }
        finally {
            Remove-Module StableAmd.Workflows, StableAmd.Img2Img, StableAmd.Generation -Force -ErrorAction SilentlyContinue
        }
    }
}
