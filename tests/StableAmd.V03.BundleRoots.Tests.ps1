Describe 'StableAMD v0.3 bundle asset roots' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $runtimeModulePath = Join-Path $repoRoot 'scripts/StableAmd.Runtime.psm1'
        $bundleRootsModulePath = Join-Path $repoRoot 'scripts/StableAmd.BundleRoots.psm1'
        $startPath = Join-Path $repoRoot 'scripts/Start-StableAMD.ps1'
        $defaultConfigPath = Join-Path $repoRoot 'config/stableamd.default.json'
    }

    It 'ships managed roots for diffusion models text encoders and VAE assets' {
        Import-Module $runtimeModulePath -Force
        $config = Get-Content -LiteralPath $defaultConfigPath -Raw | ConvertFrom-Json
        $paths = Get-StableAmdRuntimePaths -RepoRoot $repoRoot

        $config.bundleAssets.diffusionModels.roots | Should -Contain '.runtime/stableamd/models/diffusion_models'
        $config.bundleAssets.textEncoders.roots | Should -Contain '.runtime/stableamd/models/text_encoders'
        $config.bundleAssets.vae.roots | Should -Contain '.runtime/stableamd/models/vae'
        $paths.DiffusionModelsRoot | Should -Match 'models[\\/]diffusion_models$'
        $paths.TextEncodersRoot | Should -Match 'models[\\/]text_encoders$'
        $paths.VaeRoot | Should -Match 'models[\\/]vae$'
        $paths.BundlesRegistryPath | Should -Match 'bundles\.json$'
    }

    It 'migrates an existing v0.2 config with bundle asset defaults' {
        Import-Module $runtimeModulePath -Force
        $tempRepo = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-v03-bundle-config-' + [guid]::NewGuid().ToString('N'))
        try {
            $paths = Get-StableAmdRuntimePaths -RepoRoot $tempRepo
            New-Item -ItemType Directory -Path $paths.StableAmdRoot -Force | Out-Null
            @{
                schemaVersion = 1
                backend = @{ host = '127.0.0.1'; port = 8190; startupTimeoutSeconds = 240 }
                generation = @{ defaultWidth = 1024; defaultHeight = 1024; defaultSteps = 20; defaultCfg = 7; defaultSampler = 'euler'; defaultScheduler = 'normal' }
                models = @{ roots = @('.runtime/stableamd/models/checkpoints') }
                loras = @{ roots = @('.runtime/stableamd/models/loras') }
            } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $paths.ConfigPath -Encoding UTF8

            $config = Read-StableAmdConfig -RepoRoot $tempRepo
            $config.bundleAssets.diffusionModels.roots | Should -Contain '.runtime/stableamd/models/diffusion_models'
            $config.bundleAssets.textEncoders.roots | Should -Contain '.runtime/stableamd/models/text_encoders'
            $config.bundleAssets.vae.roots | Should -Contain '.runtime/stableamd/models/vae'
        }
        finally {
            Remove-Item -LiteralPath $tempRepo -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'writes bundle asset roles into the managed ComfyUI extra paths config' {
        $start = Get-Content -LiteralPath $startPath -Raw
        $start | Should -Match 'bundleAssets\.diffusionModels\.roots'
        $start | Should -Match 'bundleAssets\.textEncoders\.roots'
        $start | Should -Match 'bundleAssets\.vae\.roots'
        $start | Should -Match "FolderType\s+'diffusion_models'"
        $start | Should -Match "FolderType\s+'text_encoders'"
        $start | Should -Match "FolderType\s+'vae'"
        $start | Should -Match '\$yaml\.Add\("\s+\$\{FolderType\}: \."\)'
    }

    It 'adds lists and removes external roots while protecting managed roots' {
        Test-Path $bundleRootsModulePath | Should -BeTrue
        Import-Module $bundleRootsModulePath -Force
        $tempRepo = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-v03-bundle-roots-' + [guid]::NewGuid().ToString('N'))
        $external = Join-Path $tempRepo 'external-diffusion'
        try {
            New-Item -ItemType Directory -Path $external -Force | Out-Null
            $added = Add-StableAmdBundleAssetRoot -RepoRoot $tempRepo -Role 'diffusion_model' -Path $external
            $added.added | Should -BeTrue

            $records = @(Get-StableAmdBundleAssetRootRecords -RepoRoot $tempRepo -Role 'diffusion_model')
            @($records | Where-Object { $_.path -eq [IO.Path]::GetFullPath($external) }).Count | Should -Be 1

            $removed = Remove-StableAmdBundleAssetRoot -RepoRoot $tempRepo -Role 'diffusion_model' -Path $external
            $removed.removed | Should -BeTrue

            $managedRoot = [IO.Path]::GetFullPath((Join-Path $tempRepo '.runtime/stableamd/models/diffusion_models'))
            { Remove-StableAmdBundleAssetRoot -RepoRoot $tempRepo -Role 'diffusion_model' -Path $managedRoot } | Should -Throw '*managed*cannot be removed*'
        }
        finally {
            Remove-Item -LiteralPath $tempRepo -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
