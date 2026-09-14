BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $compactPath = Join-Path $repoRoot 'app/frontend/app-generate-compact.js'
    $compactStylesPath = Join-Path $repoRoot 'app/frontend/compact-generate.css'
    $postPath = Join-Path $repoRoot 'app/frontend/app-post-actions.js'
    $progressPath = Join-Path $repoRoot 'app/frontend/app-progress.js'
}

Describe 'StableAMD v0.3 compact Generate workspace' {
    It 'loads the dedicated compact Generate layout module from the existing frontend bootstrap' {
        Test-Path $compactPath | Should -BeTrue
        Test-Path $compactStylesPath | Should -BeTrue
        (Get-Content $postPath -Raw) | Should -Match '/app-generate-compact\.js'
    }

    It 'keeps model preset size and dense generation parameters compact while moving mode under Generate in the sidebar' {
        $compact = Get-Content $compactPath -Raw
        $styles = Get-Content $compactStylesPath -Raw

        foreach ($token in @('generate-context-row', 'generate-size-row', 'generate-parameter-row', 'custom-size-fields')) {
            $compact | Should -Match ([regex]::Escape($token))
        }
        foreach ($token in @('generation-mode', 'generate-nav-submenu', 'nav-generate-mode-field', 'aria-expanded')) {
            $compact | Should -Match ([regex]::Escape($token))
        }
        $compact | Should -Match 'model-select'
        $compact | Should -Match 'generation-profile'
        $compact | Should -Match 'resolution-preset-panel'
        $compact | Should -Match 'resolution-tier'
        $compact | Should -Match 'aspect-ratio'
        foreach ($id in @('seed', 'sampler', 'scheduler', 'steps', 'cfg')) {
            $compact | Should -Match ('#' + [regex]::Escape($id))
        }
        $styles | Should -Match '\.nav-generate-submenu'
        $styles | Should -Match '\.generate-parameter-row'
        $styles | Should -Match 'grid-template-columns'
    }

    It 'does not advertise theoretical generation modes before model capabilities are known' {
        $compact = Get-Content $compactPath -Raw
        $compact | Should -Match '/api/model-support'
        $compact | Should -Match 'data-stableamd-mode-placeholder'
        $compact | Should -Match 'Select a model first'
        $compact | Should -Match 'Loading model capabilities'
        $compact | Should -Match "capabilities\[option\.value\] === 'supported'"
        $compact | Should -Match 'option\.hidden = !supported'
        $compact | Should -Match 'select\.disabled = true'
    }

    It 'keeps Size and Ratio side by side and hides the model capability description in Generate' {
        $compact = Get-Content $compactPath -Raw
        $styles = Get-Content $compactStylesPath -Raw

        $compact | Should -Match 'model-support-hint'
        $styles | Should -Match '#model-support-hint\[hidden\]'
        $styles | Should -Match '\.compact-resolution-panel \.field-grid'
        $styles | Should -Match 'repeat\(2, minmax\(0, 1fr\)\)'
    }

    It 'uses one visible LoRA strength with an optional CLIP override while preserving the stack contract' {
        $compact = Get-Content $compactPath -Raw
        $compact | Should -Match 'data-lora-model-strength'
        $compact | Should -Match 'data-lora-clip-strength'
        $compact | Should -Match 'data-lora-clip-override'
        $compact | Should -Match "'Strength'"
        $compact | Should -Match 'CLIP override'
        $compact | Should -Match 'Z-Image LoRAs patch the diffusion model only'
    }

    It 'makes the negative prompt capability-aware and actually hides it outside SDXL' {
        $compact = Get-Content $compactPath -Raw
        $styles = Get-Content $compactStylesPath -Raw
        $compact | Should -Match 'negative-prompt'
        $compact | Should -Match 'negativePrompt'
        $compact | Should -Match 'uiHints'
        $styles | Should -Match '\.negative-prompt-field\[hidden\]'
    }

    It 'uses model-neutral progress copy while generation is running' {
        $progress = Get-Content $progressPath -Raw
        $progress | Should -Match 'Generation in progress'
        $progress | Should -Match 'resultCopy\.hidden = true'
        $progress | Should -Not -Match 'running the SDXL workflow'
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
