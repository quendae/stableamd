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

    It 'uses conservative Windows ROCm host-memory guards for gfx1030' {
        $runner = Get-Content (Join-Path $PSScriptRoot '../scripts/probes/run_comfy_isolated.py') -Raw

        $runner | Should -Match '--cpu-vae'
        $runner | Should -Match '--disable-mmap'
        $runner | Should -Match '--disable-pinned-memory'
        $runner | Should -Match '--disable-async-offload'
        $runner | Should -Match '0xC0000005'
    }
}
