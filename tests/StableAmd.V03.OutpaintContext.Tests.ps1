BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $indexPath = Join-Path $repoRoot 'app/frontend/index.html'
    $contextPath = Join-Path $repoRoot 'app/frontend/app-outpaint-context.js'
}

Describe 'StableAMD v0.3 outpaint source context' {
    It 'loads the outpaint context bridge after gallery post actions' {
        Test-Path $contextPath | Should -BeTrue
        $index = Get-Content $indexPath -Raw
        $index | Should -Match 'app-post-actions\.js[\s\S]*app-outpaint-context\.js[\s\S]*app-generate-upscale\.js'
    }

    It 'submits source prompt image asymmetric margins and blend overlap with prepared outpaint generation' {
        $frontend = Get-Content $contextPath -Raw
        $frontend | Should -Match 'stableamd:load-generated-image'
        $frontend | Should -Match 'editContext'
        $frontend | Should -Match 'sourcePromptId'
        $frontend | Should -Match 'sourceImagePath'
        $frontend | Should -Match 'blendOverlap'
        $frontend | Should -Match 'outpaint-blend'
        foreach ($side in @('left', 'right', 'top', 'bottom')) {
            $frontend | Should -Match ([regex]::Escape("outpaint-$side"))
        }
        $frontend | Should -Match 'stableamd-outpaint\\\.png'
    }

    It 'uses full outpaint denoise and a blurred source-derived latent seed instead of a blank neutral canvas' {
        $frontend = Get-Content $contextPath -Raw
        $frontend | Should -Match 'inpaint-denoise'
        $frontend | Should -Match 'denoise\.value\s*=\s*"1"'
        $frontend | Should -Match 'outpaintLatentSeed'
        $frontend | Should -Match 'blurred-edge'
        $frontend | Should -Match 'ctx\.filter\s*=\s*`blur\('
        $frontend | Should -Match 'ctx\.drawImage\(source, left, top\)'
    }
}
