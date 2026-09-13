BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $frontendPath = Join-Path $repoRoot 'app/frontend/app-post-actions.js'
    $indexPath = Join-Path $repoRoot 'app/frontend/index.html'
}

Describe 'StableAMD v0.3 post-generation gallery actions' {
    It 'ships a dedicated post-generation frontend module' {
        Test-Path $frontendPath | Should -BeTrue
        $index = Get-Content $indexPath -Raw
        $index | Should -Match 'app-post-actions\.js'
    }

    It 'adds Upscale Img2Img Inpaint and Outpaint actions to generated images' {
        $frontend = Get-Content $frontendPath -Raw

        foreach ($label in @('Upscale', 'Img2Img', 'Inpaint', 'Outpaint')) {
            $frontend | Should -Match [regex]::Escape($label)
        }
        $frontend | Should -Match 'data-post-action'
        $frontend | Should -Match 'history-card'
    }

    It 'loads a gallery image into existing img2img and inpaint inputs locally' {
        $frontend = Get-Content $frontendPath -Raw

        $frontend | Should -Match '/api/image'
        $frontend | Should -Match 'DataTransfer'
        $frontend | Should -Match 'input-image'
        $frontend | Should -Match 'inpaint-source-image'
        $frontend | Should -Match 'generation-mode'
        $frontend | Should -Match 'setPage\("generate"\)'
    }

    It 'provides an outpaint expansion shell using the existing inpaint editor' {
        $frontend = Get-Content $frontendPath -Raw

        $frontend | Should -Match 'outpaint-left'
        $frontend | Should -Match 'outpaint-right'
        $frontend | Should -Match 'outpaint-top'
        $frontend | Should -Match 'outpaint-bottom'
        $frontend | Should -Match 'prepareOutpaintSource'
        $frontend | Should -Match 'canvas'
    }

    It 'dispatches a generated-image handoff event for extension points' {
        $frontend = Get-Content $frontendPath -Raw
        $frontend | Should -Match 'stableamd:load-generated-image'
        $frontend | Should -Match 'CustomEvent'
    }
}
