Describe 'StableAMD local web UI' {
    BeforeAll {
        $frontendRoot = Join-Path $PSScriptRoot '../app/frontend'
        $indexPath = Join-Path $frontendRoot 'index.html'
        $appPath = Join-Path $frontendRoot 'app.js'
        $progressScriptPath = Join-Path $frontendRoot 'app-progress.js'
        $stylesPath = Join-Path $frontendRoot 'styles.css'
        $progressStylesPath = Join-Path $frontendRoot 'progress.css'
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

    It 'makes model folders the primary local model workflow' {
        $html = Get-Content $indexPath -Raw
        $html | Should -Match 'id="model-root-form"'
        $html | Should -Match 'id="model-root-path"'
        $html | Should -Match 'id="model-root-browse"'
        $html | Should -Match 'id="model-root-list"'
        $html | Should -Match 'id="models-refresh"'
        $html | Should -Match 'Scan models'
    }

    It 'keeps local file and Hugging Face install controls available as secondary options' {
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
        $script | Should -Match '/api/models/scan'
        $script | Should -Match '/api/model-roots'
        $script | Should -Match '/api/model-roots/browse'
        $script | Should -Match '/api/model-roots/remove'
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

    It 'shows an estimated progress bar and ETA based on recent matching generations' {
        Test-Path $progressScriptPath | Should -BeTrue
        Test-Path $progressStylesPath | Should -BeTrue
        $html = Get-Content $indexPath -Raw
        $progress = Get-Content $progressScriptPath -Raw
        $styles = Get-Content $progressStylesPath -Raw

        $html | Should -Match '/progress\.css'
        $html | Should -Match '/app-progress\.js'
        $progress | Should -Match 'generationSeconds'
        $progress | Should -Match 'ETA ~'
        $progress | Should -Match '/api/history\?limit=20'
        $progress | Should -Match '/api/generate'
        $styles | Should -Match 'generation-progress'
        $styles | Should -Match 'is-indeterminate'
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
