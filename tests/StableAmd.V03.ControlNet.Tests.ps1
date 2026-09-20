BeforeAll {
    $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $wrapperPath = Join-Path $repoRoot 'app/backend/stableamd_v03_edit_server.py'
    $controlBackendPath = Join-Path $repoRoot 'app/backend/stableamd_v03_controlnet.py'
    $loaderPath = Join-Path $repoRoot 'app/frontend/app-generate-upscale.js'
    $controlFrontendPath = Join-Path $repoRoot 'app/frontend/app-controlnet.js'
    $planPath = Join-Path $repoRoot 'docs/v0.3-forward-plan.md'
}

Describe 'StableAMD v0.3 provider-aware ControlNet' {
    It 'composes ControlNet over the accepted final product server' {
        Test-Path $wrapperPath | Should -BeTrue
        Test-Path $controlBackendPath | Should -BeTrue
        $wrapper = Get-Content -LiteralPath $wrapperPath -Raw
        $wrapper | Should -Match 'stableamd_v03_product_server'
        $wrapper | Should -Match 'ControlNetBridgeMixin'
        $wrapper | Should -Match 'ControlNetApiMixin'
    }

    It 'ships Z-Image Canny and Krea 2 OpenPose routes without SDXL-first control work' {
        $backend = Get-Content -LiteralPath $controlBackendPath -Raw
        $backend | Should -Match 'ZImageFunControlnet'
        $backend | Should -Match 'class_type.: .Canny'
        $backend | Should -Match 'Krea2OstrisEditModelPatch'
        $backend | Should -Match 'TextEncodeKrea2OstrisEdit'
        $backend | Should -Match 'krea2_turbo_openpose_controlnet\.safetensors'
        $backend | Should -Match '/api/controlnet/dependencies'
        $backend | Should -Match '/api/controlnet/install'
    }

    It 'pins the Krea OpenPose integration and model dependency' {
        $backend = Get-Content -LiteralPath $controlBackendPath -Raw
        $backend | Should -Match '7756566160c4a1b24bb1bd9f0ff3ced1a83d7547'
        $backend | Should -Match '228_587_504'
        $backend | Should -Match '0ddc3aafce4abdf7af3309b2f00c1bacdf15df1f2b4fb7adc9ff71795da90ecf'
    }

    It 'loads provider-aware Control guidance after the accepted upscale extension' {
        Test-Path $loaderPath | Should -BeTrue
        Test-Path $controlFrontendPath | Should -BeTrue
        $loader = Get-Content -LiteralPath $loaderPath -Raw
        $frontend = Get-Content -LiteralPath $controlFrontendPath -Raw
        $loader | Should -Match 'app-generate-upscale-base\.js'
        $loader | Should -Match 'app-controlnet\.js'
        $frontend | Should -Match 'Control guidance'
        $frontend | Should -Match '/api/controlnet/dependencies'
        $frontend | Should -Match '/api/controlnet/install'
        $frontend | Should -Match 'controlnet-canny-low'
        $frontend | Should -Match 'OpenPose / DWPose map'
    }

    It 'records the agreed Z-Image and Krea-first execution order' {
        $plan = Get-Content -LiteralPath $planPath -Raw
        $plan | Should -Match 'Z-Image Turbo and Krea 2 Turbo'
        $plan | Should -Match 'SDXL is deferred'
        $plan | Should -Match 'Canny'
        $plan | Should -Match 'OpenPose map'
        $plan | Should -Match 'Character Sheet.*active quality gate'
        $plan | Should -Match 'Text-to-SVG'
        $plan | Should -Match 'infographic-oriented'
        $plan | Should -Match 'MiniMax H3'
    }
}
