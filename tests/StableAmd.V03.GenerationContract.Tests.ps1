Describe 'StableAMD v0.3 generation contract' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $invokePath = Join-Path $repoRoot 'scripts/Invoke-Txt2Img.ps1'
    }

    It 'routes txt2img through the workflow provider dispatcher' {
        $invoke = Get-Content -LiteralPath $invokePath -Raw

        $invoke | Should -Match 'StableAmd\.Workflows\.psm1'
        $invoke | Should -Match 'New-StableAmdWorkflow'
        $invoke | Should -Not -Match '(?m)^\$workflow\s*=\s*New-StableAmdSdxlWorkflow'
    }

    It 'accepts a serialized ordered LoRA stack while keeping legacy single-LoRA fields' {
        $invoke = Get-Content -LiteralPath $invokePath -Raw

        $invoke | Should -Match '\[string\]\$LoraStackJson'
        $invoke | Should -Match 'ConvertFrom-Json'
        $invoke | Should -Match 'resolvedLoraStack'
        $invoke | Should -Match 'LoraStack'
        $invoke | Should -Match 'LoraName'
    }

    It 'persists the ordered LoRA stack in generation history and results' {
        $invoke = Get-Content -LiteralPath $invokePath -Raw

        $invoke | Should -Match 'schemaVersion\s*=\s*3'
        $invoke | Should -Match 'loraStack\s*=\s*@\(\$resolvedLoraStack\)'
        $invoke | Should -Match 'LoraStack\s*=\s*@\(\$resolvedLoraStack\)'
    }
}
