Describe 'StableAMD v0.3 Z-Image host-memory profile' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $templatePath = Join-Path $repoRoot 'scripts/StableAmd.TemplateBundles.psm1'
    }

    It 'prefers official compact Qwen encoders before BF16 for the 16 GiB Windows profile' {
        $template = Get-Content -LiteralPath $templatePath -Raw

        $fp4 = $template.IndexOf("qwen_3_4b_fp4_mixed.safetensors")
        $fp8 = $template.IndexOf("qwen_3_4b_fp8_mixed.safetensors")
        $bf16 = $template.IndexOf("qwen_3_4b.safetensors")

        $fp4 | Should -BeGreaterThan -1
        $fp8 | Should -BeGreaterThan $fp4
        $bf16 | Should -BeGreaterThan $fp8
        $template | Should -Match 'low-memory preferred'
        $template | Should -Match 'candidateValid'
        $template | Should -Match 'if \(\$candidateValid\)'
    }

    It 'pins official compact encoder sizes and SHA-256 metadata' {
        $template = Get-Content -LiteralPath $templatePath -Raw

        $template | Should -Match '3479416193'
        $template | Should -Match '7ca32dcf07dfe7692945d80fff86e3a74cb83c6206b9b223ac6836b939bb85d6'
        $template | Should -Match '5631994051'
        $template | Should -Match '72450b19758172c5a7273cf7de729d1c17e7f434a104a00167624cba94f68f15'
        $template | Should -Match '8044982048'
        $template | Should -Match '6c671498573ac2f7a5501502ccce8d2b08ea6ca2f661c458e708f36b36edfc5a'
    }

    It 'falls through from a truncated higher-priority encoder to the next valid official variant' {
        $template = Get-Content -LiteralPath $templatePath -Raw

        $template | Should -Match 'if \(\$candidateValid\)\s*\{\s*\$zEncoderChoice = \$choice\s*break'
        $template | Should -Match 'if \(\$null -eq \$zEncoderInvalidChoice\)'
        $template | Should -Match 'if \(\$null -eq \$zEncoderChoice\)'
    }
}
