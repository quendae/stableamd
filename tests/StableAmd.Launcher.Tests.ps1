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
        $syncRequirementsPath = Join-Path $repoRoot 'scripts/Sync-StableAmdComfyRequirements.ps1'
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

    It 'uses DynamicVRAM and RAM-pressure caching by default while preserving explicit overrides' {
        $script = Get-Content $launcherPath -Raw

        $script | Should -Match 'hasExplicitMemoryProfile'
        $script | Should -Match 'PSBoundParameters\.ContainsKey'
        $script | Should -Match 'Using default RX 6950 XT / 16 GiB profile: DynamicVRAM \+ RAM-pressure cache \+ CPU VAE\.'
        $script | Should -Not -Match 'resolvedDisableDynamicVram\s*=\s*\$true'
        $script | Should -Not -Match 'resolvedLowVram\s*=\s*\$true'
        $script | Should -Not -Match 'resolvedCacheClassic\s*=\s*\$true'
        $script | Should -Match 'LowVram and HighVram cannot be enabled together'
        $script | Should -Match 'CacheClassic and CacheNone cannot be enabled together'
    }

    It 'syncs changed managed ComfyUI requirements before backend startup without replacing ROCm torch' {
        Test-Path $syncRequirementsPath | Should -BeTrue
        $start = Get-Content $startPath -Raw
        $sync = Get-Content $syncRequirementsPath -Raw

        $start | Should -Match 'Sync-StableAmdComfyRequirements\.ps1'
        $sync | Should -Match 'Get-FileHash'
        $sync | Should -Match 'comfy-requirements\.sha256'
        $sync | Should -Match "'torch\|torchvision\|torchaudio'"
        $sync | Should -Match "'-m',\s*'pip',\s*'install'"
        $sync | Should -Match 'Status\s*=\s*''current'''
        $sync | Should -Match 'Status\s*=\s*''updated'''
    }

    It 'runs the requirements hash check under Windows PowerShell without cmdlet autoloading' {
        $fixture = Join-Path ([IO.Path]::GetTempPath()) ("stableamd-requirements-sync-{0}" -f [guid]::NewGuid().ToString('N'))
        try {
            $pythonPath = Join-Path $fixture '.runtime/therock-gfx1030/python_embeded/python.exe'
            $requirementsPath = Join-Path $fixture '.runtime/therock-comfy/ComfyUI/requirements.txt'
            $markerPath = Join-Path $fixture '.runtime/stableamd/comfy-requirements.sha256'
            New-Item -ItemType Directory -Path (Split-Path -Parent $pythonPath) -Force | Out-Null
            New-Item -ItemType Directory -Path (Split-Path -Parent $requirementsPath) -Force | Out-Null
            New-Item -ItemType Directory -Path (Split-Path -Parent $markerPath) -Force | Out-Null
            New-Item -ItemType File -Path $pythonPath -Force | Out-Null
            Set-Content -LiteralPath $requirementsPath -Value "comfyui-frontend-package==1.51.10`n" -Encoding ASCII

            $sha = [Security.Cryptography.SHA256]::Create()
            try {
                $stream = [IO.File]::OpenRead($requirementsPath)
                try { $hashBytes = $sha.ComputeHash($stream) }
                finally { $stream.Dispose() }
            }
            finally { $sha.Dispose() }
            $hash = -join ($hashBytes | ForEach-Object { $_.ToString('x2') })
            Set-Content -LiteralPath $markerPath -Value $hash -Encoding ASCII

            $escapedScript = $syncRequirementsPath.Replace("'", "''")
            $escapedFixture = $fixture.Replace("'", "''")
            $command = "`$PSModuleAutoLoadingPreference='None'; `$result = & '$escapedScript' -RepoRoot '$escapedFixture'; if (`$result.Status -ne 'current') { exit 2 }"
            & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command $command
            $LASTEXITCODE | Should -Be 0
        }
        finally {
            Remove-Item -LiteralPath $fixture -Recurse -Force -ErrorAction SilentlyContinue
        }
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
