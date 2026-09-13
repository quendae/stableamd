BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $serverPath = Join-Path $repoRoot 'app/backend/stableamd_v03_server.py'
    $frontendPath = Join-Path $repoRoot 'app/frontend/app-v02.js'
}

Describe 'StableAMD v0.3 LoRA compatibility contract' {
    It 'exposes a LoRA catalog route and validates known family mismatches server-side' {
        $server = Get-Content $serverPath -Raw

        $server | Should -Match '/api/lora-catalog'
        $server | Should -Match 'lora_catalog'
        $server | Should -Match 'lora_compatibility_error'
        $server | Should -Match 'families_compatible'
    }

    It 'shows compatibility metadata and keeps incompatible adapters hidden by default' {
        $frontend = Get-Content $frontendPath -Raw

        $frontend | Should -Match 'loraCatalog'
        $frontend | Should -Match '/api/lora-catalog'
        $frontend | Should -Match 'Show incompatible'
        $frontend | Should -Match 'showIncompatibleLoras'
        $frontend | Should -Match 'LoRA compatibility'
        $frontend | Should -Match 'incompatible'
        $frontend | Should -Match 'unknown'
    }

    It 'revalidates LoRA stack entries after the selected model changes' {
        $frontend = Get-Content $frontendPath -Raw

        $frontend | Should -Match 'refreshLoraStackCompatibility'
        $frontend | Should -Match 'model-select'
        $frontend | Should -Match 'populateLoraRowSelect'
    }
}
