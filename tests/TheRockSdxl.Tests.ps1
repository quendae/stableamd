Describe 'TheRock SDXL generation gate' {
    It 'has a real 1024x1024 SDXL API generation script' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/Test-TheRockSdxl.ps1'
        Test-Path $scriptPath | Should -BeTrue

        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'OfficialStableDiffusion[\\/]sd_xl_base_1\.0\.safetensors'
        $script | Should -Match '--extra-model-paths-config'
        $script | Should -Match 'CheckpointLoaderSimple'
        $script | Should -Match 'EmptyLatentImage'
        $script | Should -Match 'width\s*=\s*1024'
        $script | Should -Match 'height\s*=\s*1024'
        $script | Should -Match '/prompt'
        $script | Should -Match '/history/'
        $script | Should -Match 'SaveImage'
        $script | Should -Match 'vram_free'
        $script | Should -Not -Match 'Copy-Item.*sd_xl_base_1\.0\.safetensors'
    }
}
