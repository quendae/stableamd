Describe 'StableAMD one-click launcher' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $cmdPath = Join-Path $repoRoot 'Start-StableAMD.cmd'
        $launcherPath = Join-Path $repoRoot 'scripts/Launch-StableAMD.ps1'
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

    It 'captures application stdout and stderr under the managed log directory' {
        $script = Get-Content $launcherPath -Raw

        $script | Should -Match 'LogsRoot'
        $script | Should -Match 'RedirectStandardOutput'
        $script | Should -Match 'RedirectStandardError'
        $script | Should -Match 'Get-Content.+-Tail'
    }
}
