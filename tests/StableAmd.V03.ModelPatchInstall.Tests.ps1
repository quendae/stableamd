Describe 'StableAMD v0.3 curated model patch installer' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    }

    It 'pins the accepted Union 2.1 Lite model patch metadata' {
        $catalog = Get-Content -LiteralPath (Join-Path $repoRoot 'config/model-patches.v0.3.json') -Raw

        $catalog | Should -Match 'Z-Image-Turbo-Fun-Controlnet-Union-2\.1-lite-2602-8steps\.safetensors'
        $catalog | Should -Match '2016627488'
        $catalog | Should -Match '3ea098db9bd145be525c7e2366920b6d76c5ffd46b3d7aa8169bbc943fdaee35'
        $catalog | Should -Match 'Apache-2\.0'
    }

    It 'exposes catalog and install routes through the final composed server layer' {
        $wrapperPath = Join-Path $repoRoot 'app/backend/stableamd_v03_edit_server.py'
        $productPath = Join-Path $repoRoot 'app/backend/stableamd_v03_product_server.py'
        $editBasePath = Join-Path $repoRoot 'app/backend/stableamd_v03_edit_server_base.py'

        Test-Path $wrapperPath | Should -BeTrue
        Test-Path $productPath | Should -BeTrue
        Test-Path $editBasePath | Should -BeTrue

        $server = (Get-Content -LiteralPath $wrapperPath -Raw) + "`n" + (Get-Content -LiteralPath $productPath -Raw)
        $server | Should -Match '/api/model-patches/catalog'
        $server | Should -Match '/api/model-patches/install'
        $server | Should -Match 'install_curated_model_patch'
        $server | Should -Match 'ModelPatchLoader'
        (Get-Content -LiteralPath $wrapperPath -Raw) | Should -Match 'stableamd_v03_product_server'
    }

    It 'adds Install and activate provider dependencies to the Models page' {
        $frontend = Get-Content -LiteralPath (Join-Path $repoRoot 'app/frontend/app-v03.js') -Raw

        $frontend | Should -Match 'Curated provider dependencies'
        $frontend | Should -Match '/api/model-patches/catalog'
        $frontend | Should -Match '/api/model-patches/install'
        $frontend | Should -Match 'Install & activate'
        $frontend | Should -Match '/api/backend/restart'
        $frontend | Should -Match 'Invalid file'
    }
}
