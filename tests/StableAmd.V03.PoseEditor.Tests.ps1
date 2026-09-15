BeforeAll {
    $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    $loaderPath = Join-Path $repoRoot 'app/frontend/app-generate-upscale.js'
    $controlPath = Join-Path $repoRoot 'app/frontend/app-controlnet.js'
    $posePath = Join-Path $repoRoot 'app/frontend/app-pose-editor.js'
    $safeFramePath = Join-Path $repoRoot 'app/frontend/app-pose-safe-frame.js'
    $wrapperPath = Join-Path $repoRoot 'app/backend/stableamd_v03_edit_server.py'
    $poseBackendPath = Join-Path $repoRoot 'app/backend/stableamd_v03_pose_control.py'
}

Describe 'StableAMD v0.3 pose library and interactive editor' {
    It 'loads pose safe-frame preprocessing before ControlNet and the editor after it' {
        Test-Path $posePath | Should -BeTrue
        Test-Path $safeFramePath | Should -BeTrue
        $loader = Get-Content -LiteralPath $loaderPath -Raw
        $loader | Should -Match 'app-pose-safe-frame\.js'
        $loader | Should -Match 'app-controlnet\.js'
        $loader | Should -Match 'app-pose-editor\.js'
        $loader.IndexOf('app-pose-safe-frame.js') | Should -BeLessThan $loader.IndexOf('app-controlnet.js')
        $loader.IndexOf('app-controlnet.js') | Should -BeLessThan $loader.IndexOf('app-pose-editor.js')
    }

    It 'pins Pose Depot image templates and OpenPose Studio editable presets' {
        $pose = Get-Content -LiteralPath $posePath -Raw
        $pose | Should -Match '10471a9df9a5f25fba422e542475e6a72b5f23b8'
        $pose | Should -Match '4071e2c1259956f219cca617ca8b73c6608e50d5'
        $pose | Should -Match 'Pose Depot'
        $pose | Should -Match 'Apache-2\.0'
        $pose | Should -Match 'ComfyUI OpenPose Studio'
        $pose | Should -Match 'MIT'
        $pose | Should -Match 'OpenPoseFull\.png'
        $pose | Should -Match 'Interactive pose editor'
        $pose | Should -Match 'Optional reference photo'
        $pose | Should -Match 'Use edited pose'
    }

    It 'allows generated or templated pose maps instead of requiring an upload' {
        $control = Get-Content -LiteralPath $controlPath -Raw
        $control | Should -Match 'StableAmdPose\.getControlImagePayload'
        $control | Should -Match 'Choose a pose template'
        $control | Should -Match 'optional upload'
    }

    It 'auto-fits every OpenPose source into the requested aspect ratio with a safe border' {
        $safeFrame = Get-Content -LiteralPath $safeFramePath -Raw
        $safeFrame | Should -Match 'POSE_SAFE_FRAME_FRACTION'
        $safeFrame | Should -Match '0\.82'
        $safeFrame | Should -Match 'findPoseContentBounds'
        $safeFrame | Should -Match 'fitOpenPosePayloadToFrame'
        $safeFrame | Should -Match "control\.type === 'openpose'"
        $safeFrame | Should -Match 'request\.width'
        $safeFrame | Should -Match 'request\.height'
        $safeFrame | Should -Match 'imageSmoothingEnabled = false'
        $safeFrame | Should -Match 'safe-frame fitted'
    }

    It 'composes direct Z-Image OpenPose-map support over Union 2.1' {
        Test-Path $poseBackendPath | Should -BeTrue
        $wrapper = Get-Content -LiteralPath $wrapperPath -Raw
        $backend = Get-Content -LiteralPath $poseBackendPath -Raw
        $wrapper | Should -Match 'PoseControlBridgeMixin'
        $backend | Should -Match '_inject_zimage_openpose'
        $backend | Should -Match 'ZImageFunControlnet'
        $backend | Should -Match 'precomputed-or-editor'
        $backend | Should -Match 'nearest-exact'
    }
}
