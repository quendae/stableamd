Describe 'StableAMD local web UI' {
    BeforeAll {
        $frontendRoot = Join-Path $PSScriptRoot '../app/frontend'
        $indexPath = Join-Path $frontendRoot 'index.html'
        $appPath = Join-Path $frontendRoot 'app.js'
        $stylesPath = Join-Path $frontendRoot 'styles.css'
    }

    It 'ships the Generate Models Gallery Settings and Diagnostics surfaces' {
        Test-Path $indexPath | Should -BeTrue
        $html = Get-Content $indexPath -Raw

        $html | Should -Match 'data-page="generate"'
        $html | Should -Match 'data-page="models"'
        $html | Should -Match 'data-page="gallery"'
        $html | Should -Match 'data-page="settings"'
        $html | Should -Match 'data-page="diagnostics"'
        $html | Should -Match 'id="runtime-status"'
        $html | Should -Match 'id="generate-form"'
        $html | Should -Match 'id="prompt"'
        $html | Should -Match 'id="model-select"'
    }

    It 'provides local and Hugging Face model install controls' {
        $html = Get-Content $indexPath -Raw
        $html | Should -Match 'id="local-model-form"'
        $html | Should -Match 'id="local-model-path"'
        $html | Should -Match 'id="hf-model-form"'
        $html | Should -Match 'id="hf-repository"'
        $html | Should -Match 'id="hf-filename"'
    }

    It 'uses only StableAMD product API routes from the normal UI' {
        Test-Path $appPath | Should -BeTrue
        $script = Get-Content $appPath -Raw

        $script | Should -Match '/api/status'
        $script | Should -Match '/api/models'
        $script | Should -Match '/api/models/install'
        $script | Should -Match '/api/history'
        $script | Should -Match '/api/image\?path='
        $script | Should -Match 'encodeURIComponent'
        $script | Should -Match '/api/generate'
        $script | Should -Match '/api/diagnostics'
        $script | Should -Match '/api/backend/\$\{action\}'
        $script | Should -Match 'backendAction\("start"\)'
        $script | Should -Match 'backendAction\("stop"\)'
        $script | Should -Not -Match 'object_info|/prompt|8190'
    }

    It 'has a responsive layout and visible keyboard focus treatment' {
        Test-Path $stylesPath | Should -BeTrue
        $styles = Get-Content $stylesPath -Raw

        $styles | Should -Match '@media\s*\(max-width:\s*760px\)'
        $styles | Should -Match ':focus-visible'
        $styles | Should -Match 'prefers-reduced-motion'
    }
}

Describe 'StableAMD application server frontend integration' {
    It 'serves the frontend from the same loopback application server' {
        $serverPath = Join-Path $PSScriptRoot '../app/backend/stableamd_server.py'
        $server = Get-Content $serverPath -Raw

        $server | Should -Match 'app.*frontend'
        $server | Should -Match 'index\.html'
        $server | Should -Match 'Content-Type'
    }
}
