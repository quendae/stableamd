BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $indexPath = Join-Path $repoRoot 'app/frontend/index.html'
    $contextPath = Join-Path $repoRoot 'app/frontend/app-outpaint-context.js'
    $progressPath = Join-Path $repoRoot 'app/frontend/app-progress.js'
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

    It 'automatically expands 256 px on every side and prepares the outpaint canvas' {
        $frontend = Get-Content $contextPath -Raw
        $frontend | Should -Match 'DEFAULT_OUTPAINT_MARGIN\s*=\s*256'
        $frontend | Should -Match '\["left",\s*"right",\s*"top",\s*"bottom"\]'
        $frontend | Should -Match 'autoPrepareOutpaint'
        $frontend | Should -Match 'stableamd-outpaint-original'
        $frontend | Should -Match 'window\.prepareOutpaintSource'
        $frontend | Should -Match 'Preparing 256 px outpaint expansion on every side'
    }

    It 'switches prepared outpaint dimensions to the real custom canvas size' {
        $frontend = Get-Content $contextPath -Raw
        $frontend | Should -Match 'syncPreparedDimensions'
        $frontend | Should -Match 'resolution-tier'
        $frontend | Should -Match 'option\.value\s*===\s*"custom"'
        $frontend | Should -Match 'width\.value\s*=\s*String\(source\.width\)'
        $frontend | Should -Match 'height\.value\s*=\s*String\(source\.height\)'
        $frontend | Should -Match 'stableamd:outpaint-prepared'
    }

    It 'keeps long outpaint preparation visible and prevents duplicate generation starts' {
        $progress = Get-Content $progressPath -Raw
        $progress | Should -Match 'Outpaint in progress'
        $progress | Should -Match 'Outpaint running'
        $progress | Should -Match 'encoding source / loading edit model'
        $progress | Should -Match 'generationBusy'
        $progress | Should -Match 'A generation is already running'
        $progress | Should -Match 'aria-busy'
    }
}
