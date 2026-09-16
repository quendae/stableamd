Describe 'StableAMD memory diagnostics' {
    It 'supports disabling the ComfyUI RAM pressure cache independently from VRAM mode' {
        $backendScript = Get-Content (Join-Path $PSScriptRoot '../scripts/Start-StableAMD.ps1') -Raw
        $launcherScript = Get-Content (Join-Path $PSScriptRoot '../scripts/Launch-StableAMD.ps1') -Raw

        $backendScript | Should -Match '\[switch\]\$CacheNone'
        $backendScript | Should -Match '--cache-none'
        $backendScript | Should -Match 'cacheNone = \[bool\]\$CacheNone'
        $launcherScript | Should -Match '\[switch\]\$CacheNone'
        $launcherScript | Should -Match '\$backendParams\.CacheNone = \$true'
        $launcherScript | Should -Match 'RAM pressure cache disabled'
    }

    It 'supports keeping models resident in GPU memory with ComfyUI highvram' {
        $backendScript = Get-Content (Join-Path $PSScriptRoot '../scripts/Start-StableAMD.ps1') -Raw
        $launcherScript = Get-Content (Join-Path $PSScriptRoot '../scripts/Launch-StableAMD.ps1') -Raw

        $backendScript | Should -Match '\[switch\]\$HighVram'
        $backendScript | Should -Match '--highvram'
        $backendScript | Should -Match 'highVram = \[bool\]\$HighVram'
        $launcherScript | Should -Match '\[switch\]\$HighVram'
        $launcherScript | Should -Match '\$backendParams\.HighVram = \$true'
        $launcherScript | Should -Match 'highvram enabled'
    }

    It 'supports classic node caching without RAM pressure eviction' {
        $backendScript = Get-Content (Join-Path $PSScriptRoot '../scripts/Start-StableAMD.ps1') -Raw
        $launcherScript = Get-Content (Join-Path $PSScriptRoot '../scripts/Launch-StableAMD.ps1') -Raw

        $backendScript | Should -Match '\[switch\]\$CacheClassic'
        $backendScript | Should -Match '--cache-classic'
        $backendScript | Should -Match 'cacheClassic = \[bool\]\$CacheClassic'
        $launcherScript | Should -Match '\[switch\]\$CacheClassic'
        $launcherScript | Should -Match '\$backendParams\.CacheClassic = \$true'
        $launcherScript | Should -Match 'classic cache enabled'
    }

    It 'defaults the 16 GiB desktop profile to DynamicVRAM and RAM-pressure caching' {
        $launcherScript = Get-Content (Join-Path $PSScriptRoot '../scripts/Launch-StableAMD.ps1') -Raw

        $launcherScript | Should -Match 'Using default RX 6950 XT / 16 GiB profile: DynamicVRAM \+ RAM-pressure cache \+ CPU VAE\.'
        $launcherScript | Should -Not -Match 'resolvedDisableDynamicVram\s*=\s*\$true'
        $launcherScript | Should -Not -Match 'resolvedLowVram\s*=\s*\$true'
        $launcherScript | Should -Not -Match 'resolvedCacheClassic\s*=\s*\$true'
    }

    It 'keeps CPU VAE without regressing large safetensors model loading' {
        $runner = Get-Content (Join-Path $PSScriptRoot '../scripts/probes/run_comfy_isolated.py') -Raw

        $runner | Should -Match '--cpu-vae'
        $runner | Should -Not -Match '"--disable-mmap"'
        $runner | Should -Not -Match '"--disable-pinned-memory"'
        $runner | Should -Not -Match '"--disable-async-offload"'
        $runner | Should -Match 'StableAMD bootstrap'
    }
}
