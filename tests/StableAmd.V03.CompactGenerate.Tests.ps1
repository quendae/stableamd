BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $indexPath = Join-Path $repoRoot 'app/frontend/index.html'
    $compactPath = Join-Path $repoRoot 'app/frontend/app-generate-compact.js'
    $v02Path = Join-Path $repoRoot 'app/frontend/app-v02.js'
    $postPath = Join-Path $repoRoot 'app/frontend/app-post-actions.js'
    $stylesPath = Join-Path $repoRoot 'app/frontend/styles.css'
}

Describe 'StableAMD v0.3 compact Generate workspace' {
    It 'loads the dedicated compact Generate layout module' {
        Test-Path $compactPath | Should -BeTrue
        (Get-Content $indexPath -Raw) | Should -Match 'app-generate-compact\.js'
    }

    It 'groups mode model preset size and dense generation parameters without full-width numeric fields' {
        $compact = Get-Content $compactPath -Raw
        $styles = Get-Content $stylesPath -Raw

        foreach ($token in @('generate-context-row', 'generate-size-row', 'generate-parameter-row', 'custom-size-fields')) {
            $compact | Should -Match ([regex]::Escape($token))
        }
        $compact | Should -Match 'generation-mode'
        $compact | Should -Match 'model-select'
        $compact | Should -Match 'generation-profile'
        $compact | Should -Match 'resolution-tier'
        $compact | Should -Match 'aspect-ratio'
        foreach ($id in @('seed', 'sampler', 'scheduler', 'steps', 'cfg')) {
            $compact | Should -Match ('#' + [regex]::Escape($id))
        }
        $styles | Should -Match '\.generate-parameter-row'
        $styles | Should -Match 'grid-template-columns'
    }

    It 'uses one visible LoRA strength with an optional CLIP override while preserving the stack contract' {
        $v02 = Get-Content $v02Path -Raw
        $v02 | Should -Match 'data-lora-model-strength'
        $v02 | Should -Match 'data-lora-clip-strength'
        $v02 | Should -Match 'data-lora-clip-override'
        $v02 | Should -Match '>Strength<'
        $v02 | Should -Match 'CLIP override'
    }

    It 'makes the negative prompt capability-aware instead of always visible' {
        $compact = Get-Content $compactPath -Raw
        $compact | Should -Match 'negative-prompt'
        $compact | Should -Match 'negativePrompt'
        $compact | Should -Match 'uiHints'
    }

    It 'adds icon-led compact gallery actions including delete' {
        $post = Get-Content $postPath -Raw
        $post | Should -Match 'data-post-action="delete"'
        $post | Should -Match 'history/delete'
        $post | Should -Match 'aria-label'
    }
}
