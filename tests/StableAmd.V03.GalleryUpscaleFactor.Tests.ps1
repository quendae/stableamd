BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $frontendPath = Join-Path $repoRoot 'app/frontend/app-upscale.js'
}

Describe 'StableAMD Gallery upscale factor selection' {
    It 'offers Auto model plus exact 2x 4x and 8x targets' {
        $frontend = Get-Content $frontendPath -Raw
        foreach ($token in @('upscale-factor', '2x', '4x', '8x', 'Auto')) {
            $frontend | Should -Match ([regex]::Escape($token))
        }
        $frontend | Should -Match '/api/upscale/plan'
    }

    It 'sends factor and optional preferred model to the upscale API' {
        $frontend = Get-Content $frontendPath -Raw
        $frontend | Should -Match 'factor'
        $frontend | Should -Match 'modelName'
        $frontend | Should -Match '/api/upscale'
    }
}
