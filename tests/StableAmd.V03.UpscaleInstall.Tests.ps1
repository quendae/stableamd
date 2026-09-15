BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $frontendPath = Join-Path $repoRoot 'app/frontend/app-upscale.js'
    $catalogPath = Join-Path $repoRoot 'config/upscalers.v0.3.json'
}

Describe 'StableAMD v0.3 curated upscaler installation' {
    It 'ships a pinned curated x2 x4 and UltraSharp catalog' {
        Test-Path $catalogPath | Should -BeTrue
        $catalog = Get-Content $catalogPath -Raw | ConvertFrom-Json
        $catalog.schemaVersion | Should -Be 1
        @($catalog.models).Count | Should -Be 3
        @($catalog.models.id) | Should -Contain 'realesrgan-x2plus'
        @($catalog.models.id) | Should -Contain 'realesrgan-x4plus'
        @($catalog.models.id) | Should -Contain 'ultrasharp-x4'
        ($catalog.models | Where-Object id -eq 'ultrasharp-x4').nonCommercial | Should -BeTrue
        foreach ($model in @($catalog.models)) {
            [string]$model.sha256 | Should -Match '^[0-9a-f]{64}$'
            [int64]$model.sizeBytes | Should -BeGreaterThan 0
        }
    }

    It 'offers install and activate controls without accepting arbitrary model urls' {
        $frontend = Get-Content $frontendPath -Raw
        $frontend | Should -Match '/api/upscale-models/catalog'
        $frontend | Should -Match '/api/upscale-models/install'
        $frontend | Should -Match 'Install & activate'
        $frontend | Should -Match '/api/backend/restart'
        $frontend | Should -Match 'Non-commercial license'
        $frontend | Should -Not -Match 'sourceUrl'
    }
}
