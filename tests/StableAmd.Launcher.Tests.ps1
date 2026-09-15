Describe 'StableAMD one-click launcher' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $cmdPath = Join-Path $repoRoot 'Start-StableAMD.cmd'
        $stopCmdPath = Join-Path $repoRoot 'Stop-StableAMD.cmd'
        $launcherPath = Join-Path $repoRoot 'scripts/Launch-StableAMD.ps1'
        $startPath = Join-Path $repoRoot 'scripts/Start-StableAMD.ps1'
        $stopPath = Join-Path $repoRoot 'scripts/Stop-StableAMD.ps1'
        $watchPath = Join-Path $repoRoot 'scripts/Watch-StableAMD.ps1'
        $runtimeModulePath = Join-Path $repoRoot 'scripts/StableAmd.Runtime.psm1'
        $acceptancePath = Join-Path $repoRoot 'scripts/Test-StableAMDPackage.ps1'
    }

    It 'ships double-clickable Windows start and stop entry points' {
        Test-Path $cmdPath | Should -BeTrue
        Test-Path $stopCmdPath | Should -BeTrue
        $cmd = Get-Content $cmdPath -Raw
        $stopCmd = Get-Content $stopCmdPath -Raw

        $cmd | Should -Match 'powershell\.exe'
        $cmd | Should -Match '-ExecutionPolicy\s+Bypass'
        $cmd | Should -Match 'scripts\\Launch-StableAMD\.ps1'
        $cmd | Should -Match '%\*'
        $stopCmd | Should -Match 'scripts\\Stop-StableAMD\.ps1'
        $stopCmd | Should -Match '%\*'
    }

    It 'uses the accepted RX 6950 XT memory profile by default while preserving explicit overrides' {
        $script = Get-Content $launcherPath -Raw

        $script | Should -Match 'hasExplicitMemoryProfile'
        $script | Should -Match 'PSBoundParameters\.ContainsKey'
        $script | Should -Match 'resolvedDisableDynamicVram\s*=\s*\$true'
        $script | Should -Match 'resolvedLowVram\s*=\s*\$true'
        $script | Should -Match 'resolvedCacheClassic\s*=\s*\$true'
        $script | Should -Match 'RX 6950 XT / 16 GiB profile'
        $script | Should -Match 'LowVram and HighVram cannot be enabled together'
        $script | Should -Match 'CacheClassic and CacheNone cannot be enabled together'
    }

    It 'starts the managed compute backend before the application server' {
        Test-Path $launcherPath | Should -BeTrue
        $script = Get-Content $launcherPath -Raw

        $script | Should -Match 'Start-StableAMD\.ps1'
        $script | Should -Match 'stableamd_v03_edit_server\.py'
        $script | Should -Match 'TheRockPython'
        $script | Should -Match '--host\s+127\.0\.0\.1'
        $script | Should -Match '/api/health'
        $script | Should -Match 'service'
        $script | Should -Match 'StableAMD'
    }

    It 'cleans the backend and application if application startup fails' {
        $script = Get-Content $launcherPath -Raw

        $script | Should -Match 'Startup failed; cleaning up only StableAMD-managed processes'
        $script | Should -Match 'Stop-StableAMD\.ps1'
        $script | Should -Match '-RepoRoot\s+\$RepoRoot'
        $script | Should -Match 'failed-start cleanup'
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
        $launcher | Should -Match '"-u -s'
        $launcher | Should -Match 'BackendPid'
        $launcher | Should -Match 'AppPid'
        $launcher | Should -Match 'Managed PIDs:'
        $start | Should -Match "role = 'compute-backend'"
        $start | Should -Match 'WindowStyle\s+Hidden'
        $start | Should -Match '"-u -s'
    }

    It 'keeps interactive desktop launches attached to a kill-on-close supervisor' {
        $launcher = Get-Content $launcherPath -Raw
        $acceptance = Get-Content $acceptancePath -Raw

        $launcher | Should -Match '\[switch\]\$Detached'
        $launcher | Should -Match 'JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE'
        $launcher | Should -Match 'AssignProcessToJobObject'
        $launcher | Should -Match 'Watch-StableAMD\.ps1'
        $launcher | Should -Match 'Ctrl\+C.*releases VRAM'
        $launcher | Should -Match 'Stop-StableAMD\.cmd'
        $acceptance | Should -Match 'Launch-StableAMD\.ps1'
        $acceptance | Should -Match '-Detached'
    }

    It 'captures application stdout and stderr under the managed log directory' {
        $launcher = Get-Content $launcherPath -Raw
        $watch = Get-Content $watchPath -Raw

        $launcher | Should -Match 'LogsRoot'
        $launcher | Should -Match 'RedirectStandardOutput'
        $launcher | Should -Match 'RedirectStandardError'
        $watch | Should -Match 'Get-Content.*-Tail'
    }

    It 'hard-kills the full StableAMD process tree and verifies no repo-scoped orphan remains' {
        Test-Path $stopPath | Should -BeTrue
        $stop = Get-Content $stopPath -Raw
        $start = Get-Content $startPath -Raw

        $stop | Should -Match 'AppStatePath'
        $stop | Should -Match 'Get-CimInstance\s+Win32_Process'
        $stop | Should -Match 'stableamd_server'
        $stop | Should -Match 'stableamd_v03_lora_server'
        $stop | Should -Match 'stableamd_v03_edit_server'
        $stop | Should -Match 'run_comfy_isolated'
        $stop | Should -Match 'taskkill\.exe'
        $stop | Should -Match '/T /F'
        $stop | Should -Match 'RemainingManagedProcesses'
        $stop | Should -Match 'teardown is incomplete'
        $start | Should -Match 'Stop-StableAMD\.ps1.*-BackendOnly'
    }

    It 'normalizes orphan process identities without colliding with PowerShell automatic Matches' {
        $stop = Get-Content $stopPath -Raw

        $stop | Should -Match 'Get-SnapshotProcessId'
        $stop | Should -Match "'ProcessId', 'Id'"
        $stop | Should -Match 'Get-SnapshotParentProcessId'
        $stop | Should -Match '\$managedProcesses\s*=\s*@\(\)'
        $stop | Should -Match 'return\s+\$managedProcesses'
        $stop | Should -Not -Match '(?im)^\s*\$matches\s*='
        $stop | Should -Not -Match 'New-Object\s+System\.Collections\.Generic\.List\[object\]'
    }

    It 'reports useful leftover process diagnostics instead of an empty PID' {
        $stop = Get-Content $stopPath -Raw

        $stop | Should -Match 'Format-StableAmdProcessDiagnostics'
        $stop | Should -Match 'PID\s+PPID\s+Role\s+Name'
        $stop | Should -Match 'CommandLine:'
        $stop | Should -Match 'ParentProcessId'
        $stop | Should -Match 'Returned object type\(s\)'
        $stop | Should -Match 'State was preserved for diagnostics'
    }

    It 'streams backend and application logs concurrently including CR progress updates' {
        Test-Path $watchPath | Should -BeTrue
        $watch = Get-Content $watchPath -Raw

        $watch | Should -Match 'backend stdout'
        $watch | Should -Match 'backend stderr'
        $watch | Should -Match 'app stdout'
        $watch | Should -Match 'app stderr'
        $watch | Should -Match 'FileShare\]::ReadWrite'
        $watch | Should -Match 'Seek\('
        $watch | Should -Match '\[regex\]::Split'
        $watch | Should -Match 'Start-Sleep\s+-Milliseconds\s+\$PollMilliseconds'
        $watch | Should -Not -Match 'Get-Content\s+-Path\s+@\(\$logs\).*?-Wait'
        $watch | Should -Match 'Ctrl\+C'
    }

    It 'discovers replacement backend log files after an in-app backend refresh' {
        $watch = Get-Content $watchPath -Raw

        $watch | Should -Match 'Sync-StableAmdTrackedLogs'
        $watch | Should -Match 'Read-StableAmdBackendState\s+-Path\s+\$paths\.BackendStatePath'
        $watch | Should -Match 'Read-StableAmdBackendState\s+-Path\s+\$paths\.AppStatePath'
        $watch | Should -Match 'Backend restarted / refreshed'
        $watch | Should -Match 'New log source'
    }
}
