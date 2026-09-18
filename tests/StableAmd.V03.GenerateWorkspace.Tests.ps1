BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $compactPath = Join-Path $repoRoot 'app/frontend/app-generate-compact.js'
    $workspacePath = Join-Path $repoRoot 'app/frontend/app-generate-workspace.js'
    $workspaceStylesPath = Join-Path $repoRoot 'app/frontend/generate-workspace.css'
    $designPath = Join-Path $repoRoot 'DESIGN.md'
}

Describe 'StableAMD v0.3 Generate studio workspace' {
    It 'loads a dedicated workspace layer after the compact Generate adapter' {
        Test-Path $workspacePath | Should -BeTrue
        Test-Path $workspaceStylesPath | Should -BeTrue
        $compact = Get-Content $compactPath -Raw
        $compact | Should -Match '/app-generate-workspace\.js'
    }

    It 'turns Generate modes into direct sidebar choices while preserving generation-mode as canonical state' {
        $workspace = Get-Content $workspacePath -Raw
        foreach ($token in @('generate-mode-choice', 'Text to image', 'Image to image', 'generation-mode', 'aria-current')) {
            $workspace | Should -Match ([regex]::Escape($token))
        }
        $workspace | Should -Match 'dispatchEvent\(new Event\(.change.'
    }

    It 'uses a desktop-first three-zone workspace with a result canvas and inspector' {
        $workspace = Get-Content $workspacePath -Raw
        $styles = Get-Content $workspaceStylesPath -Raw
        foreach ($token in @('studio-recipe', 'studio-canvas', 'studio-inspector', 'studio-workspace')) {
            $workspace | Should -Match ([regex]::Escape($token))
            $styles | Should -Match ([regex]::Escape($token))
        }
        $styles | Should -Match 'grid-template-columns'
        $styles | Should -Match 'minmax\(0, 1fr\)'
        $styles | Should -Match 'position:\s*sticky'
    }

    It 'keeps secondary generation tools progressively disclosed in the inspector' {
        $workspace = Get-Content $workspacePath -Raw
        foreach ($label in @('Output', 'LoRA', 'Control guidance', 'Upscale', 'Advanced')) {
            $workspace | Should -Match ([regex]::Escape($label))
        }
        $workspace | Should -Match 'details'
        $workspace | Should -Match 'controlnet-panel'
        $workspace | Should -Match 'lora-stack-panel'
    }

    It 'hides classic denoise for Krea Image Edit and refreshes contextual workspace state' {
        $workspace = Get-Content $workspacePath -Raw
        $workspace | Should -Match 'denoise'
        $workspace | Should -Match 'krea2'
        $workspace | Should -Match 'img2img'
        $workspace | Should -Match 'hidden'
        $workspace | Should -Match 'MutationObserver'
    }

    It 'provides restrained transitions with a reduced-motion path and responsive recomposition' {
        $styles = Get-Content $workspaceStylesPath -Raw
        $styles | Should -Match '@keyframes'
        $styles | Should -Match 'prefers-reduced-motion:\s*reduce'
        $styles | Should -Match '@media \(max-width: 1180px\)'
        $styles | Should -Match '@media \(max-width: 760px\)'
    }

    It 'records the durable Generate workspace direction in DESIGN.md' {
        Test-Path $designPath | Should -BeTrue
        $design = Get-Content $designPath -Raw
        $design | Should -Match 'StableAMD'
        $design | Should -Match 'desktop-first'
        $design | Should -Match 'Generate'
        $design | Should -Match 'recipe'
        $design | Should -Match 'canvas'
        $design | Should -Match 'inspector'
        $design | Should -Match 'orange'
    }
}
