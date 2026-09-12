Describe 'StableAMD v0.3 frontend contract' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $frontendPath = Join-Path $repoRoot 'app/frontend/app-v02.js'
        $frontendV03Path = Join-Path $repoRoot 'app/frontend/app-v03.js'
        $indexPath = Join-Path $repoRoot 'app/frontend/index.html'
    }

    It 'loads model support metadata and exposes capability state for the selected model' {
        $js = Get-Content -LiteralPath $frontendPath -Raw

        $js | Should -Match '/api/model-support'
        $js | Should -Match 'modelSupport'
        $js | Should -Match 'capabilities'
        $js | Should -Match 'loraPolicy'
    }

    It 'builds and submits an ordered multi-LoRA stack through the product API' {
        $js = Get-Content -LiteralPath $frontendPath -Raw

        $js | Should -Match 'loraStack'
        $js | Should -Match 'Add LoRA'
        $js | Should -Match 'data-lora-stack-row'
        $js | Should -Match 'modelStrength'
        $js | Should -Match 'clipStrength'
        $js | Should -Match 'enabled'
        $js | Should -Match 'path === "/api/generate"'
    }

    It 'restores multi-LoRA history while retaining legacy single-LoRA reuse' {
        $js = Get-Content -LiteralPath $frontendPath -Raw

        $js | Should -Match 'loraStack", "LoraStack"'
        $js | Should -Match 'loraName", "LoraName"'
        $js | Should -Match 'restoreLoraSettings'
    }

    It 'exposes SDXL img2img mode with local image upload and denoise strength' {
        $js = Get-Content -LiteralPath $frontendPath -Raw

        $js | Should -Match 'generation-mode'
        $js | Should -Match 'input-image'
        $js | Should -Match 'img2img-denoise'
        $js | Should -Match 'img2img'
        $js | Should -Match 'readAsDataURL'
        $js | Should -Match 'dataBase64'
        $js | Should -Match 'capabilities.*img2img|img2img.*capabilities'
    }

    It 'manages bundle asset folders for diffusion models text encoders and VAE files' {
        Test-Path $frontendV03Path | Should -BeTrue
        $js = Get-Content -LiteralPath $frontendV03Path -Raw
        $index = Get-Content -LiteralPath $indexPath -Raw

        $js | Should -Match '/api/bundle-roots'
        $js | Should -Match 'Bundle asset folders'
        $js | Should -Match 'diffusion_model'
        $js | Should -Match 'text_encoder'
        $js | Should -Match 'vae'
        $js | Should -Match 'Browse folder'
        $js | Should -Match 'restartBackendForBundleFolders'
        $index | Should -Match 'app-v03\.js'
    }
}
