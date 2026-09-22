BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $runtimePath = Join-Path $repoRoot 'scripts/StableAmd.Runtime.psm1'
    $startPath = Join-Path $repoRoot 'scripts/Start-StableAMD.ps1'
    $modulePath = Join-Path $repoRoot 'scripts/StableAmd.Upscale.psm1'
    $builderPath = Join-Path $repoRoot 'scripts/Build-StableAmdUpscaleWorkflow.ps1'
    $listPath = Join-Path $repoRoot 'scripts/List-UpscaleModels.ps1'
    $frontendPath = Join-Path $repoRoot 'app/frontend/app-upscale.js'
    $indexPath = Join-Path $repoRoot 'app/frontend/index.html'
    $catalogPath = Join-Path $repoRoot 'config/upscalers.v0.3.json'
}

Describe 'StableAMD v0.3 stock ComfyUI upscale provider' {
    It 'creates a managed upscale_models directory and exposes it to ComfyUI' {
        Import-Module $runtimePath -Force
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-upscale-root-' + [guid]::NewGuid().ToString('N'))
        try {
            $paths = Get-StableAmdRuntimePaths -RepoRoot $tempRoot
            $paths.PSObject.Properties.Name | Should -Contain 'UpscaleModelsRoot'
            Initialize-StableAmdRuntimeDirectories -Paths $paths
            Test-Path $paths.UpscaleModelsRoot -PathType Container | Should -BeTrue
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }

        $start = Get-Content $startPath -Raw
        $start | Should -Match "FolderType\s+'upscale_models'"
        $start | Should -Match 'UpscaleModelsRoot'
    }

    It 'builds the stock LoadImage UpscaleModelLoader ImageUpscaleWithModel SaveImage graph' {
        Test-Path $modulePath | Should -BeTrue
        Import-Module $modulePath -Force

        $workflow = New-StableAmdUpscaleWorkflow -InputImageName 'source.png' -ModelName '4x-UltraSharp.pth' -FilenamePrefix 'StableAMD_UPSCALE_TEST'
        $workflow['1'].class_type | Should -Be 'LoadImage'
        $workflow['2'].class_type | Should -Be 'UpscaleModelLoader'
        $workflow['3'].class_type | Should -Be 'ImageUpscaleWithModel'
        $workflow['9'].class_type | Should -Be 'SaveImage'
        $workflow['2'].inputs.model_name | Should -Be '4x-UltraSharp.pth'
        $workflow['3'].inputs.upscale_model | Should -Be @('2', 0)
        $workflow['3'].inputs.image | Should -Be @('1', 0)
        $workflow['9'].inputs.images | Should -Be @('3', 0)
    }

    It 'accepts the generic service RepoRoot parameter when building an upscale workflow' {
        Test-Path $builderPath | Should -BeTrue

        $workflow = & $builderPath -RepoRoot $repoRoot -InputImageName 'source.png' -ModelName 'RealESRGAN_x2plus.pth' -FilenamePrefix 'StableAMD_UPSCALE_TEST'

        $workflow['2'].inputs.model_name | Should -Be 'RealESRGAN_x2plus.pth'
        $workflow['9'].inputs.filename_prefix | Should -Be 'StableAMD_UPSCALE_TEST'
    }

    It 'discovers installed upscale models through the ComfyUI UpscaleModelLoader contract' {
        Test-Path $listPath | Should -BeTrue
        $script = Get-Content $listPath -Raw
        $script | Should -Match 'object_info/UpscaleModelLoader'
        $script | Should -Match 'model_name'
    }

    It 'ships an upscale UI launched from the gallery action and a curated model catalog' {
        Test-Path $frontendPath | Should -BeTrue
        Test-Path $catalogPath | Should -BeTrue
        $frontend = Get-Content $frontendPath -Raw
        $catalog = Get-Content $catalogPath -Raw
        $index = Get-Content $indexPath -Raw

        $index | Should -Match 'app-upscale\.js'
        $frontend | Should -Match '/api/upscale-models'
        $frontend | Should -Match '/api/upscale'
        $frontend | Should -Match 'openStableAmdUpscale'
        $frontend | Should -Match 'Upscale model'
        $catalog | Should -Match '4x-UltraSharp|RealESRGAN'
    }

    It 'distinguishes model files on disk from models registered by ComfyUI' {
        $frontend = Get-Content $frontendPath -Raw

        $frontend | Should -Match 'diskModels'
        $frontend | Should -Match 'restartRecommended'
        $frontend | Should -Match 'found on disk'
        $frontend | Should -Match 'upscale-refresh-models'
        $frontend | Should -Match 'Check again'
    }
}
