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

    It 'normalizes single Windows path separators before writing YAML' {
        $script = Get-Content (Join-Path $PSScriptRoot '../scripts/Test-TheRockSdxl.ps1') -Raw
        $script | Should -Match ([regex]::Escape(".Replace('\', '/')"))
        $script | Should -Not -Match ([regex]::Escape(".Replace('\\', '/')"))
    }

    It 'validates safetensors bounds before starting ComfyUI' {
        $validatorPath = Join-Path $PSScriptRoot '../scripts/probes/validate_safetensors.py'
        Test-Path $validatorPath | Should -BeTrue

        $validator = Get-Content $validatorPath -Raw
        $validator | Should -Match 'data_offsets'
        $validator | Should -Match 'file_size'
        $validator | Should -Match 'valid'

        $script = Get-Content (Join-Path $PSScriptRoot '../scripts/Test-TheRockSdxl.ps1') -Raw
        $script | Should -Match 'validate_safetensors\.py'
        $script | Should -Match 'Checkpoint safetensors is incomplete or corrupt'
    }

    It 'stops polling immediately when ComfyUI records an execution error' {
        $script = Get-Content (Join-Path $PSScriptRoot '../scripts/Test-TheRockSdxl.ps1') -Raw
        $script | Should -Match "status_str"
        $script | Should -Match "-eq 'error'"
        $script | Should -Match 'ComfyUI reported an SDXL execution error'
    }

    It 'provides an explicit verified checkpoint repair command' {
        $repairPath = Join-Path $PSScriptRoot '../scripts/Repair-SdxlCheckpoint.ps1'
        Test-Path $repairPath | Should -BeTrue

        $repair = Get-Content $repairPath -Raw
        $repair | Should -Match '31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b'
        $repair | Should -Match 'curl\.exe'
        $repair | Should -Match '\.partial'
        $repair | Should -Match 'Get-FileHash'
        $repair | Should -Match 'SHA256'
        $repair | Should -Match 'Move-Item'
    }
}
