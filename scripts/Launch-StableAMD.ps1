[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$AppPort = 8188,
    [int]$AppStartupTimeoutSeconds = 30,
    [switch]$NoBrowser,
    [switch]$SkipRuntimeInstall,
    [switch]$Detached
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'StableAMD v0.1 launcher is Windows-only.'
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

if ($AppPort -lt 1 -or $AppPort -gt 65535) {
    throw "Application port '$AppPort' is outside the valid range 1-65535."
}
if ($AppStartupTimeoutSeconds -lt 5) {
    throw 'Application startup timeout must be at least 5 seconds.'
}

$runtimeModule = Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1'
if (-not (Test-Path $runtimeModule -PathType Leaf)) {
    throw "StableAMD runtime module is missing: '$runtimeModule'."
}
Import-Module $runtimeModule -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths

$appServer = Join-Path $RepoRoot 'app/backend/stableamd_server.py'
if (-not (Test-Path $appServer -PathType Leaf)) {
    throw "StableAMD application server is missing: '$appServer'."
}

$comfyMain = Join-Path $paths.ComfyRoot 'main.py'
$comfyApiInput = Join-Path $paths.ComfyRoot 'comfy_api/input/__init__.py'
$runtimeMissing = (-not (Test-Path $paths.TheRockPython -PathType Leaf)) -or (-not (Test-Path $comfyMain -PathType Leaf)) -or (-not (Test-Path $comfyApiInput -PathType Leaf))
if ($runtimeMissing) {
    if ($SkipRuntimeInstall) {
        throw "StableAMD runtime is missing or incomplete. Expected Python '$($paths.TheRockPython)' and ComfyUI '$($paths.ComfyRoot)'."
    }

    $runtimeInstaller = Join-Path $PSScriptRoot 'Install-StableAMDRuntime.ps1'
    if (-not (Test-Path $runtimeInstaller -PathType Leaf)) {
        throw "StableAMD runtime is missing and the bootstrap installer was not found at '$runtimeInstaller'."
    }

    Write-Host ''
    Write-Host 'StableAMD runtime is missing or incomplete. Preparing the pinned Radeon runtime...' -ForegroundColor Yellow
    Write-Host 'The first launch downloads Python, the locked TheRock ROCm/PyTorch stack and ComfyUI. This can download more than 1 GB.' -ForegroundColor DarkGray
    $runtimeInstall = & $runtimeInstaller -RepoRoot $RepoRoot
    if ($null -eq $runtimeInstall -or -not (Test-Path $paths.TheRockPython -PathType Leaf) -or -not (Test-Path $comfyMain -PathType Leaf)) {
        throw 'StableAMD runtime bootstrap returned without creating the required managed runtime.'
    }
}

$resolvedAppPort = $AppPort
$appUrl = "http://127.0.0.1:$resolvedAppPort/"
$healthUrl = "http://127.0.0.1:$resolvedAppPort/api/health"

function Get-StableAmdAppHealth {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 3
        if ($null -ne $response -and [string]$response.service -eq 'StableAMD' -and [string]$response.status -eq 'ok') {
            return $response
        }
    }
    catch { }
    return $null
}

function New-StableAmdKillOnCloseJob {
    # In normal desktop mode the launcher is the StableAMD supervisor. A Windows
    # Job Object provides the hard guarantee we want: if this PowerShell host is
    # closed or crashes, Windows terminates the assigned app/backend processes,
    # which also releases ROCm VRAM. Detached acceptance/service runs skip this.
    if (-not ('StableAmd.NativeJob' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

namespace StableAmd {
    public static class NativeJob {
        [StructLayout(LayoutKind.Sequential)]
        struct IO_COUNTERS {
            public UInt64 ReadOperationCount;
            public UInt64 WriteOperationCount;
            public UInt64 OtherOperationCount;
            public UInt64 ReadTransferCount;
            public UInt64 WriteTransferCount;
            public UInt64 OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
            public Int64 PerProcessUserTimeLimit;
            public Int64 PerJobUserTimeLimit;
            public UInt32 LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public UInt32 ActiveProcessLimit;
            public Int64 Affinity;
            public UInt32 PriorityClass;
            public UInt32 SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        const int JobObjectExtendedLimitInformation = 9;
        const UInt32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        static extern IntPtr CreateJobObject(IntPtr lpJobAttributes, string lpName);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool SetInformationJobObject(IntPtr hJob, int infoType, IntPtr lpJobObjectInfo, UInt32 cbJobObjectInfoLength);

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll")]
        static extern bool CloseHandle(IntPtr hObject);

        public static IntPtr CreateKillOnClose() {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            IntPtr ptr = Marshal.AllocHGlobal(length);
            try {
                Marshal.StructureToPtr(info, ptr, false);
                if (!SetInformationJobObject(job, JobObjectExtendedLimitInformation, ptr, (UInt32)length))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            catch {
                CloseHandle(job);
                throw;
            }
            finally {
                Marshal.FreeHGlobal(ptr);
            }
            return job;
        }

        public static void Assign(IntPtr job, int pid) {
            using (Process process = Process.GetProcessById(pid)) {
                if (!AssignProcessToJobObject(job, process.Handle))
                    throw new Win32Exception(Marshal.GetLastWin32Error());
            }
        }

        public static void Close(IntPtr job) {
            if (job != IntPtr.Zero) CloseHandle(job);
        }
    }
}
'@
    }
    return [StableAmd.NativeJob]::CreateKillOnClose()
}

Write-Host ''
Write-Host 'StableAMD v0.1' -ForegroundColor Cyan
Write-Host 'Starting managed compute backend...' -ForegroundColor Cyan
$backendStatus = & (Join-Path $PSScriptRoot 'Start-StableAMD.ps1') -RepoRoot $RepoRoot
if ($null -eq $backendStatus -or -not [bool]$backendStatus.Healthy) {
    throw 'StableAMD managed compute backend did not become healthy.'
}
Write-Host "Compute backend ready: $($backendStatus.Url) (PID $($backendStatus.Pid))" -ForegroundColor Green
if (-not [string]::IsNullOrWhiteSpace([string]$backendStatus.StdoutLog)) {
    Write-Host "Backend stdout: $($backendStatus.StdoutLog)" -ForegroundColor DarkGray
}
if (-not [string]::IsNullOrWhiteSpace([string]$backendStatus.StderrLog)) {
    Write-Host "Backend stderr: $($backendStatus.StderrLog)" -ForegroundColor DarkGray
}

$existingHealth = Get-StableAmdAppHealth
$Reused = $null -ne $existingHealth
$appProcess = $null
$stdoutPath = $null
$stderrPath = $null
$appState = Read-StableAmdBackendState -Path $paths.AppStatePath

if ($Reused) {
    $knownPid = $null
    try { if ($null -ne $appState) { $knownPid = [int]$appState.pid } } catch { $knownPid = $null }
    $pidText = if ($null -ne $knownPid -and $knownPid -gt 0) { " (PID $knownPid)" } else { '' }
    Write-Host "StableAMD application is already reachable at $appUrl$pidText" -ForegroundColor Green
}
else {
    if ($null -ne $appState) {
        Remove-StableAmdBackendState -Path $paths.AppStatePath
    }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdoutPath = Join-Path $paths.LogsRoot "app-$stamp.stdout.log"
    $stderrPath = Join-Path $paths.LogsRoot "app-$stamp.stderr.log"

    Write-Host "Starting StableAMD application on $appUrl ..." -ForegroundColor Cyan
    # -u makes application-side PowerShell/progress forwarding immediately
    # visible in the managed log rather than waiting for Python's file buffer.
    $arguments = "-u -s `"$appServer`" --repo-root `"$RepoRoot`" --host 127.0.0.1 --port $resolvedAppPort"
    $appProcess = Start-Process `
        -FilePath $paths.TheRockPython `
        -ArgumentList $arguments `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -WindowStyle Hidden `
        -PassThru

    $deadline = (Get-Date).AddSeconds($AppStartupTimeoutSeconds)
    $health = $null
    while ((Get-Date) -lt $deadline) {
        if ($appProcess.HasExited) { break }
        $health = Get-StableAmdAppHealth
        if ($null -ne $health) { break }
        Start-Sleep -Milliseconds 500
    }

    if ($null -eq $health) {
        Write-Host ''
        Write-Host '===== StableAMD application stderr tail =====' -ForegroundColor DarkCyan
        if (Test-Path $stderrPath) {
            Get-Content -Path $stderrPath -Tail 80 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        }
        Write-Host ''
        Write-Host '===== StableAMD application stdout tail =====' -ForegroundColor DarkCyan
        if (Test-Path $stdoutPath) {
            Get-Content -Path $stdoutPath -Tail 40 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        }

        if ($null -ne $appProcess -and -not $appProcess.HasExited) {
            Stop-Process -Id $appProcess.Id -Force -ErrorAction SilentlyContinue
        }
        throw "StableAMD application did not become healthy at '$healthUrl' within $AppStartupTimeoutSeconds seconds."
    }

    $appState = [pscustomobject]@{
        schemaVersion = 1
        role = 'application-server'
        pid = $appProcess.Id
        url = $appUrl
        healthUrl = $healthUrl
        startedAtUtc = [DateTime]::UtcNow.ToString('o')
        pythonPath = $paths.TheRockPython
        serverPath = $appServer
        stdoutLog = $stdoutPath
        stderrLog = $stderrPath
    }
    Write-StableAmdBackendState -Path $paths.AppStatePath -State $appState

    Write-Host "StableAMD application ready: $appUrl (PID $($appProcess.Id))" -ForegroundColor Green
    Write-Host "Application stdout: $stdoutPath" -ForegroundColor DarkGray
    Write-Host "Application stderr: $stderrPath" -ForegroundColor DarkGray
}

$result = [pscustomobject]@{
    Status = 'running'
    Healthy = $true
    Reused = $Reused
    Url = $appUrl
    HealthUrl = $healthUrl
    ProcessId = if ($null -ne $appProcess) { $appProcess.Id } elseif ($null -ne $appState) { $appState.pid } else { $null }
    AppStatePath = $paths.AppStatePath
    StdoutLog = if ($null -ne $appProcess) { $stdoutPath } elseif ($null -ne $appState) { $appState.stdoutLog } else { $null }
    StderrLog = if ($null -ne $appProcess) { $stderrPath } elseif ($null -ne $appState) { $appState.stderrLog } else { $null }
    Backend = $backendStatus
}

if (-not $NoBrowser) {
    Start-Process $appUrl
}

if ($Detached) {
    Write-Host 'StableAMD is running detached. Use Stop-StableAMD.ps1 for full teardown.' -ForegroundColor DarkCyan
    return $result
}

$supervisorJob = [IntPtr]::Zero
try {
    $supervisorJob = New-StableAmdKillOnCloseJob
    [StableAmd.NativeJob]::Assign($supervisorJob, [int]$backendStatus.Pid)
    [StableAmd.NativeJob]::Assign($supervisorJob, [int]$result.ProcessId)
    Write-Host ''
    Write-Host 'StableAMD supervisor is active.' -ForegroundColor Green
    Write-Host 'This terminal now owns the StableAMD processes. Ctrl+C or closing this terminal stops StableAMD and releases VRAM.' -ForegroundColor Cyan
    Write-Host 'Live backend/application logs follow below:' -ForegroundColor DarkCyan
    Write-Host ''

    & (Join-Path $PSScriptRoot 'Watch-StableAMD.ps1') -RepoRoot $RepoRoot -Tail 20
}
finally {
    # Closing the job handle first guarantees process termination even if the
    # normal script-level cleanup path is interrupted. Stop-StableAMD then
    # verifies the repo-scoped process state and removes runtime state files.
    if ($supervisorJob -ne [IntPtr]::Zero) {
        [StableAmd.NativeJob]::Close($supervisorJob)
        $supervisorJob = [IntPtr]::Zero
        Start-Sleep -Milliseconds 300
    }
    try {
        & (Join-Path $PSScriptRoot 'Stop-StableAMD.ps1') -RepoRoot $RepoRoot | Out-Null
    }
    catch {
        Write-Warning "StableAMD supervisor cleanup reported: $($_.Exception.Message)"
    }
}

return $result
