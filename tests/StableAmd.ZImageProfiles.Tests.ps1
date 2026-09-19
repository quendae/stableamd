BeforeAll {
    $repoRoot = Join-Path $PSScriptRoot '..'
    $profilePath = Join-Path $repoRoot 'config/generation-profiles.v0.2.json'
    $frontendPath = Join-Path $repoRoot 'app/frontend/app-v02.js'
    $runtimeModulePath = Join-Path $repoRoot 'scripts/StableAmd.Runtime.psm1'
}

Describe 'Z-Image Turbo generation profile' {
    It 'ships small plus official 1024 1280 and 1536 resolution tiers' {
        $catalog = Get-Content $profilePath -Raw | ConvertFrom-Json
        $profile = @($catalog.profiles | Where-Object { $_.id -eq 'z-image-turbo' })[0]

        $profile | Should -Not -BeNullOrEmpty
        @($profile.resolutionTiers).Count | Should -Be 4
        @($profile.resolutionTiers.id) | Should -Be @('small', '1024', '1280', '1536')
        @($profile.resolutionTiers | Where-Object { $_.recommended }).id | Should -Be '1024'
    }

    It 'maps every Z-Image tier to the supported aspect-ratio buckets' {
        $catalog = Get-Content $profilePath -Raw | ConvertFrom-Json
        $profile = @($catalog.profiles | Where-Object { $_.id -eq 'z-image-turbo' })[0]
        $ratios = @('1:1', '9:7', '7:9', '4:3', '3:4', '3:2', '2:3', '16:9', '9:16', '21:9', '9:21')

        foreach ($tier in @($profile.resolutionTiers)) {
            @($tier.sizes.ratio) | Should -Be $ratios
            foreach ($size in @($tier.sizes)) {
                ([int]$size.width % 16) | Should -Be 0
                ([int]$size.height % 16) | Should -Be 0
            }
        }

        $small = @($profile.resolutionTiers | Where-Object { $_.id -eq 'small' })[0]
        (@($small.sizes | Where-Object { $_.ratio -eq '1:1' })[0].width) | Should -Be 768
        (@($small.sizes | Where-Object { $_.ratio -eq '16:9' })[0].width) | Should -Be 1024

        $official = @($profile.resolutionTiers | Where-Object { $_.id -eq '1024' })[0]
        $wide = @($official.sizes | Where-Object { $_.ratio -eq '21:9' })[0]
        $wide.width | Should -Be 1344
        $wide.height | Should -Be 576
    }

    It 'keeps the proven official sampler path and exposes fast recommended and quality presets' {
        $catalog = Get-Content $profilePath -Raw | ConvertFrom-Json
        $profile = @($catalog.profiles | Where-Object { $_.id -eq 'z-image-turbo' })[0]
        $combinations = @($profile.combinations)

        @($combinations.id) | Should -Be @('fast-6-step', 'recommended-8-step', 'quality-12-step')
        @($combinations.sampler | Select-Object -Unique) | Should -Be @('res_multistep')
        @($combinations.scheduler | Select-Object -Unique) | Should -Be @('simple')
        @($combinations.cfg | Select-Object -Unique) | Should -Be @(1.0)
        @($combinations.steps) | Should -Be @(6, 8, 12)
    }
}

Describe 'Model-aware resolution and LoRA UI' {
    It 'provides model-profile resolution tier and aspect-ratio controls while preserving custom dimensions' {
        $script = Get-Content $frontendPath -Raw

        $script | Should -Match 'resolution-tier'
        $script | Should -Match 'aspect-ratio'
        $script | Should -Match 'resolutionTiers'
        $script | Should -Match 'Custom size'
        $script | Should -Match 'applyResolutionPreset'
    }

    It 'filters LoRA choices by model family while retaining shared LoRAs' {
        $script = Get-Content $frontendPath -Raw

        $script | Should -Match 'loraFamilyGroupsForCurrentModel'
        $script | Should -Match "'shared'"
        $script | Should -Match "'sdxl'"
        $script | Should -Match "'z-image'"
        $script | Should -Match "'flux'"
        $script | Should -Match "'krea'"
        $script | Should -Match 'filterLoraChoicesForCurrentModel'
    }
}

Describe 'Managed LoRA library layout' {
    It 'creates family folders under the managed LoRA root' {
        Import-Module $runtimeModulePath -Force
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-lora-family-test-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        try {
            $paths = Get-StableAmdRuntimePaths -RepoRoot $tempRoot
            Initialize-StableAmdRuntimeDirectories -Paths $paths
            foreach ($family in @('shared', 'sd15', 'sdxl', 'sd3', 'z-image', 'flux', 'krea')) {
                Test-Path (Join-Path $paths.LorasRoot $family) -PathType Container | Should -BeTrue
            }
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
