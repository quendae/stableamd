BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $frontendPath = Join-Path $repoRoot 'app/frontend/app-generate-upscale.js'
    $indexPath = Join-Path $repoRoot 'app/frontend/index.html'
}

Describe 'StableAMD v0.3 upscale after generation' {
    It 'ships the shared post-process module on every Generate mode' {
        Test-Path $frontendPath | Should -BeTrue
        (Get-Content $indexPath -Raw) | Should -Match 'app-generate-upscale\.js'
    }

    It 'offers Off 2x 4x 8x and Auto or explicit installed model selection' {
        $frontend = Get-Content $frontendPath -Raw
        foreach ($token in @('upscale-after-generation', 'upscale-after-factor', 'upscale-after-model', '2x', '4x', '8x', 'Auto')) {
            $frontend | Should -Match ([regex]::Escape($token))
        }
        $frontend | Should -Match '/api/upscale-models'
        $frontend | Should -Match '/api/upscale/plan'
    }

    It 'runs the selected upscale after a successful generation and renders the final result' {
        $frontend = Get-Content $frontendPath -Raw
        $frontend | Should -Match 'stableamd:generation-complete'
        $frontend | Should -Match '/api/upscale'
        $frontend | Should -Match 'renderGenerationResult'
        $frontend | Should -Match 'refreshHistory'
    }

    It 'shows the target output dimensions and warns for very large outputs' {
        $frontend = Get-Content $frontendPath -Raw
        $frontend | Should -Match 'upscale-output-hint'
        $frontend | Should -Match 'targetWidth'
        $frontend | Should -Match 'targetHeight'
        $frontend | Should -Match 'large-output'
    }
}
