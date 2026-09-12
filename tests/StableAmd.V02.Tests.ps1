Describe 'StableAMD v0.2 generation controls' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $generationModulePath = Join-Path $repoRoot 'scripts/StableAmd.Generation.psm1'
        $startPath = Join-Path $repoRoot 'scripts/Start-StableAMD.ps1'
        $invokePath = Join-Path $repoRoot 'scripts/Invoke-Txt2Img.ps1'
        $frontendPath = Join-Path $repoRoot 'app/frontend/index.html'
        $frontendV02JsPath = Join-Path $repoRoot 'app/frontend/app-v02.js'
        $serverPath = Join-Path $repoRoot 'app/backend/stableamd_server.py'
        $configPath = Join-Path $repoRoot 'config/stableamd.default.json'
    }

    It 'builds an SDXL workflow with an optional LoraLoader node' {
        Import-Module $generationModulePath -Force

        $without = New-StableAmdSdxlWorkflow -CheckpointName 'base.safetensors' -Prompt 'cat' -Seed 1
        $without.Keys | Should -Not -Contain '10'
        $without['3'].inputs.model | Should -Be @('4', 0)
        $without['6'].inputs.clip | Should -Be @('4', 1)

        $with = New-StableAmdSdxlWorkflow -CheckpointName 'base.safetensors' -Prompt 'cat' -Seed 1 -LoraName 'style.safetensors' -LoraModelStrength 0.8 -LoraClipStrength 0.65
        $with['10'].class_type | Should -Be 'LoraLoader'
        $with['10'].inputs.lora_name | Should -Be 'style.safetensors'
        $with['10'].inputs.strength_model | Should -Be 0.8
        $with['10'].inputs.strength_clip | Should -Be 0.65
        $with['3'].inputs.model | Should -Be @('10', 0)
        $with['6'].inputs.clip | Should -Be @('10', 1)
        $with['7'].inputs.clip | Should -Be @('10', 1)
    }

    It 'exposes real ComfyUI generation options and LoRA selection through the product API' {
        $server = Get-Content $serverPath -Raw
        $server | Should -Match '/api/generation-options'
        $server | Should -Match 'object_info/KSampler'
        $server | Should -Match 'object_info/LoraLoader'
        $server | Should -Match 'loraName'
        $server | Should -Match 'loraModelStrength'
        $server | Should -Match 'loraClipStrength'
    }

    It 'configures separate LoRA model roots for ComfyUI' {
        $start = Get-Content $startPath -Raw
        $config = Get-Content $configPath -Raw

        $config | Should -Match '"loras"'
        $start | Should -Match 'loras:'
        $start | Should -Match 'config\.loras\.roots'
    }

    It 'ships select controls for sampler scheduler and one LoRA with separate strengths' {
        $html = Get-Content $frontendPath -Raw
        Test-Path $frontendV02JsPath | Should -BeTrue
        $js = Get-Content $frontendV02JsPath -Raw

        $html | Should -Match '<select[^>]+id="sampler"'
        $html | Should -Match '<select[^>]+id="scheduler"'
        $html | Should -Match '<select[^>]+id="lora-select"'
        $html | Should -Match 'id="lora-model-strength"'
        $html | Should -Match 'id="lora-clip-strength"'
        $html | Should -Match 'app-v02\.js'
        $js | Should -Match '/api/generation-options'
        $js | Should -Match 'loraName'
        $js | Should -Match 'loraModelStrength'
        $js | Should -Match 'loraClipStrength'
    }

    It 'persists LoRA metadata in generation history for reuse' {
        $invoke = Get-Content $invokePath -Raw
        $invoke | Should -Match 'loraName'
        $invoke | Should -Match 'loraModelStrength'
        $invoke | Should -Match 'loraClipStrength'
    }
}
