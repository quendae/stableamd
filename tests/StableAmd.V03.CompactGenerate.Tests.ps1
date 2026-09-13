BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $compactPath = Join-Path $repoRoot 'app/frontend/app-generate-compact.js'
    $compactStylesPath = Join-Path $repoRoot 'app/frontend/compact-generate.css'
    $postPath = Join-Path $repoRoot 'app/frontend/app-post-actions.js'
}

Describe 'StableAMD v0.3 compact Generate workspace' {
    It 'loads the dedicated compact Generate layout module from the existing frontend bootstrap' {
        Test-Path $compactPath | Should -BeTrue
        Test-Path $compactStylesPath | Should -BeTrue
        (Get-Content $postPath -Raw) | Should -Match '/app-generate-compact\.js'
    }

    It 'groups mode model preset size and dense generation parameters without full-width numeric fields' {
        $compact = Get-Content $compactPath -Raw
        $styles = Get-Content $compactStylesPath -Raw

        foreach ($token in @('generate-context-row', 'generate-size-row', 'generate-parameter-row', 'custom-size-fields')) {
            $compact | Should -Match ([regex]::Escape($token))
        }
        $compact | Should -Match 'generation-mode'
        $compact | Should -Match 'model-select'
        $compact | Should -Match 'generation-profile'
        $compact | Should -Match 'resolution-preset-panel'
        $compact | Should -Match 'resolution-tier'
        $compact | Should -Match 'aspect-ratio'
        foreach ($id in @('seed', 'sampler', 'scheduler', 'steps', 'cfg')) {
            $compact | Should -Match ('#' + [regex]::Escape($id))
        }
        $styles | Should -Match '\.generate-parameter-row'
        $styles | Should -Match 'grid-template-columns'
    }

    It 'uses one visible LoRA strength with an optional CLIP override while preserving the stack contract' {
        $compact = Get-Content $compactPath -Raw
        $compact | Should -Match 'data-lora-model-strength'
        $compact | Should -Match 'data-lora-clip-strength'
        $compact | Should -Match 'data-lora-clip-override'
        $compact | Should -Match "'Strength'"
        $compact | Should -Match 'CLIP override'
    }

    It 'makes the negative prompt capability-aware instead of always visible' {
        $compact = Get-Content $compactPath -Raw
        $compact | Should -Match 'negative-prompt'
        $compact | Should -Match 'negativePrompt'
        $compact | Should -Match 'uiHints'
    }

    It 'adds icon-led compact gallery actions including delete' {
        $post = Get-Content $postPath -Raw
        $post | Should -Match 'data-post-action'
        $post | Should -Match 'deleteGalleryRecord'
        $post | Should -Match '/api/history/delete'
        $post | Should -Match 'aria-label'
        $post | Should -Match '<svg'
    }
}
