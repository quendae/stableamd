Describe 'StableAMD one-click launcher' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $cmdPath = Join-Path $repoRoot 'Start-StableAMD.cmd'
        $launcherPath = Join-Path $repoRoot 'scripts/Launch-StableAMD.ps1'
        $startPath = Join-Path $repoRoot 'scripts/Start-StableAMD.ps1'
        $stopPath = Join-Path $repoRoot 'scripts/Stop-StableAMD.ps1'
        $watchPath = Join-Path $repoRoot 'scripts/Watch-StableAMD.ps1'
        $runtimeModulePath = Join-Path $repoRoot 'scripts/StableAmd.Runtime.psm1'
    }

    It 'ships a double-clickable Windows entry point' {
        Test-Path $cmdPath | Should -BeTrue
        $cmd = Get-Content $cmdPath -Raw

        $cmd | Should -Match 'powershell\.exe'
        $cmd | Should -Match '-ExecutionPolicy\s+Bypass'
        $cmd | Should -Match 'scripts\\Launch-StableAMD\.ps1'
        $cmd | Should -Match '%\*'
    }

    It 'starts the managed compute backend before the application server' {
        Test-Path $launcherPath | Should -BeTrue
        $script = Get-Content $launcherPath -Raw

        $script | Should -Match 'Start-StableAMD\.ps1'
        $script | Should -Match 'stableamd_server\.py'
        $script | Should -Match 'TheRockPython'
        $script | Should -Match '--host\s+127\.0\.0\.1'
        $script | Should -Match '/api/health'
        $script | Should -Match 'service'
        $script | Should -Match 'StableAMD'
    }

    It 'reuses an existing healthy application server and optionally opens the browser' {
        $script = Get-Content $launcherPath -Raw

        $script | Should -Match 'Reused'
        $script | Should -Match 'NoBrowser'
        $script | Should -Match 'Start-Process\s+\$appUrl'
        $script | Should -Match '127\.0\.0\.1:\$resolvedAppPort'
    }

    It 'tracks both application and compute processes and hides child Python consoles' {
        $launcher = Get-Content $launcherPath -Raw
        $start = Get-Content $startPath -Raw
        $runtimeModule = Get-Content $runtimeModulePath -Raw

        $runtimeModule | Should -Match 'AppStatePath'
        $launcher | Should -Match 'AppStatePath'
        $launcher | Should -Match "role = 'application-server'"
        $launcher | Should -Match 'WindowStyle\s+Hidden'
        $start | Should -Match "role = 'compute-backend'"
        $start | Should -Match 'WindowStyle\s+Hidden'
    }

    It 'captures application stdout and stderr under the managed log directory' {
        $script = Get-Content $launcherPath -Raw

        $script | Should -Match 'LogsRoot'
        $script | Should -Match 'RedirectStandardOutput'
        $script | Should -Match 'RedirectStandardError'
        $script | Should -Match 'Get-Content.+-Tail'
    }

    It 'can stop the full StableAMD process tree while backend restarts stay backend-only' {
        Test-Path $stopPath | Should -BeTrue
        $stop = Get-Content $stopPath -Raw
        $start = Get-Content $startPath -Raw

        $stop | Should -Match 'AppStatePath'
        $stop | Should -Match 'Get-CimInstance\s+Win32_Process'
        $stop | Should -Match 'stableamd_server\\?\.py|stableamd_server\.py'
        $stop | Should -Match 'run_comfy_isolated\\?\.py|run_comfy_isolated\.py'
        $stop | Should -Match 'StoppedBackendPids'
        $stop | Should -Match 'StoppedAppPids'
        $start | Should -Match 'Stop-StableAMD\.ps1.*-BackendOnly'
    }

    It 'ships a live diagnostics watcher for backend and application logs' {
        Test-Path $watchPath | Should -BeTrue
        $watch = Get-Content $watchPath -Raw

        $watch | Should -Match 'Get-Content.*-Wait'
        $watch | Should -Match 'stdoutLog'
        $watch | Should -Match 'stderrLog'
        $watch | Should -Match 'Ctrl\+C'
    }
}
