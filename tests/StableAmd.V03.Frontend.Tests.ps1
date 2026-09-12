Describe 'StableAMD v0.3 frontend contract' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $frontendPath = Join-Path $repoRoot 'app/frontend/app-v02.js'
    }

    It 'loads model support metadata and exposes capability state for the selected model' {
        $js = Get-Content -LiteralPath $frontendPath -Raw

        $js | Should -Match '/api/model-support'
        $js | Should -Match 'modelSupport'
        $js | Should -Match 'capabilities'
        $js | Should -Match 'loraPolicy'
    }

    It 'builds and submits an ordered multi-LoRA stack through the product API' {
        $js = Get-Content -LiteralPath $frontendPath -Raw

        $js | Should -Match 'loraStack'
        $js | Should -Match 'Add LoRA'
        $js | Should -Match 'data-lora-stack-row'
        $js | Should -Match 'modelStrength'
        $js | Should -Match 'clipStrength'
        $js | Should -Match 'enabled'
        $js | Should -Match 'path === "/api/generate"'
    }

    It 'restores multi-LoRA history while retaining legacy single-LoRA reuse' {
        $js = Get-Content -LiteralPath $frontendPath -Raw

        $js | Should -Match 'loraStack", "LoraStack"'
        $js | Should -Match 'loraName", "LoraName"'
        $js | Should -Match 'restoreLoraSettings'
    }
}
