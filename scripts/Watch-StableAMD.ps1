[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$Tail = 30,
    [int]$PollMilliseconds = 120
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$PollMilliseconds = [Math]::Max(50, $PollMilliseconds)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$backend = Read-StableAmdBackendState -Path $paths.BackendStatePath
$app = Read-StableAmdBackendState -Path $paths.AppStatePath

Write-Host ''
Write-Host 'StableAMD live diagnostics' -ForegroundColor Cyan
if ($null -ne $backend) {
    Write-Host "Compute backend PID: $($backend.pid)" -ForegroundColor Green
    Write-Host "Compute backend URL: $($backend.url)" -ForegroundColor DarkGray
}
else {
    Write-Host 'Compute backend state: not running / not tracked' -ForegroundColor Yellow
}
if ($null -ne $app) {
    Write-Host "Application PID: $($app.pid)" -ForegroundColor Green
    Write-Host "Application URL: $($app.url)" -ForegroundColor DarkGray
}
else {
    Write-Host 'Application state: not running / not tracked' -ForegroundColor Yellow
}

$logEntries = @()
function Add-StableAmdLogEntry {
    param(
        [psobject]$State,
        [string]$PropertyName,
        [string]$Label
    )

    if ($null -eq $State) { return }
    $property = $State.PSObject.Properties[$PropertyName]
    if ($null -eq $property) { return }
    $path = [string]$property.Value
    if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path $path -PathType Leaf)) { return }
    if (@($script:logEntries | Where-Object { $_.Path -eq $path }).Count -gt 0) { return }

    $script:logEntries += [pscustomobject]@{
        Path = $path
        Label = $Label
        Position = [long]0
        Pending = ''
    }
}

Add-StableAmdLogEntry -State $backend -PropertyName 'stdoutLog' -Label 'backend stdout'
Add-StableAmdLogEntry -State $backend -PropertyName 'stderrLog' -Label 'backend stderr'
Add-StableAmdLogEntry -State $app -PropertyName 'stdoutLog' -Label 'app stdout'
Add-StableAmdLogEntry -State $app -PropertyName 'stderrLog' -Label 'app stderr'

if ($logEntries.Count -eq 0) {
    throw 'No active StableAMD log files were found. Start StableAMD first.'
}

Write-Host ''
Write-Host 'Watching all logs concurrently (Ctrl+C stops the supervisor and releases VRAM):' -ForegroundColor Cyan
foreach ($entry in $logEntries) {
    Write-Host ("  [{0}] {1}" -f $entry.Label, $entry.Path) -ForegroundColor DarkGray
}
Write-Host ''

# Show a small initial tail from every log instead of blocking forever on the
# first path. The old Get-Content -Path file1,file2 -Wait form waits on file1
# and never advances to quiet/active siblings, which hid ComfyUI progress.
foreach ($entry in $logEntries) {
    $tailLines = @(Get-Content -LiteralPath $entry.Path -Tail ([Math]::Max(0, $Tail)) -ErrorAction SilentlyContinue)
    foreach ($line in $tailLines) {
        if (-not [string]::IsNullOrWhiteSpace([string]$line)) {
            Write-Host ("[{0}] {1}" -f $entry.Label, $line)
        }
    }
    try {
        $entry.Position = [long](Get-Item -LiteralPath $entry.Path -ErrorAction Stop).Length
    }
    catch {
        $entry.Position = 0
    }
}

$utf8 = New-Object System.Text.UTF8Encoding($false, $false)

# Poll each active file by byte offset. This follows stdout and stderr from both
# managed processes at the same time and treats carriage returns as progress
# updates, so tqdm/ComfyUI sampler output becomes visible step-by-step.
while ($true) {
    foreach ($entry in $logEntries) {
        try {
            $info = Get-Item -LiteralPath $entry.Path -ErrorAction Stop
            $length = [long]$info.Length
            if ($length -lt [long]$entry.Position) {
                $entry.Position = 0
                $entry.Pending = ''
            }
            if ($length -le [long]$entry.Position) { continue }

            $stream = [IO.File]::Open(
                $entry.Path,
                [IO.FileMode]::Open,
                [IO.FileAccess]::Read,
                [IO.FileShare]::ReadWrite
            )
            try {
                [void]$stream.Seek([long]$entry.Position, [IO.SeekOrigin]::Begin)
                while ($stream.Position -lt $stream.Length) {
                    $remaining = [long]($stream.Length - $stream.Position)
                    $chunkSize = [int][Math]::Min(65536, $remaining)
                    if ($chunkSize -le 0) { break }

                    $buffer = New-Object byte[] $chunkSize
                    $read = $stream.Read($buffer, 0, $buffer.Length)
                    if ($read -le 0) { break }

                    $entry.Position = [long]$stream.Position
                    $entry.Pending += $utf8.GetString($buffer, 0, $read)

                    # ComfyUI/tqdm refreshes one terminal line with CR while
                    # ordinary Python logs use LF/CRLF. Treat all three as an
                    # event boundary so every sampling update can be inspected.
                    $parts = @([regex]::Split([string]$entry.Pending, "`r`n|`n|`r"))
                    $hasTerminator = ([string]$entry.Pending -match "(`r`n|`n|`r)$")
                    $emitCount = if ($hasTerminator) { $parts.Count } else { [Math]::Max(0, $parts.Count - 1) }

                    for ($i = 0; $i -lt $emitCount; $i++) {
                        $line = [string]$parts[$i]
                        if (-not [string]::IsNullOrWhiteSpace($line)) {
                            Write-Host ("[{0}] {1}" -f $entry.Label, $line)
                        }
                    }

                    if ($hasTerminator) {
                        $entry.Pending = ''
                    }
                    elseif ($parts.Count -gt 0) {
                        $entry.Pending = [string]$parts[$parts.Count - 1]
                    }
                }
            }
            finally {
                $stream.Dispose()
            }
        }
        catch {
            # A log can briefly disappear during a backend restart. The next
            # poll will pick it up again without terminating the supervisor.
        }
    }

    Start-Sleep -Milliseconds $PollMilliseconds
}
