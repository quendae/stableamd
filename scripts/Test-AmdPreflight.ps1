[CmdletBinding()]
param(
    [string]$OutputDirectory = '',
    [switch]$PassThru
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'StableAMD RX 6950 XT preflight must be run on Windows.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Hardware.psm1') -Force

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $repoRoot 'diagnostics'
}

function Get-StableAmdCommandVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Command,
        [string[]]$Arguments = @('--version')
    )

    $resolved = Get-Command $Command -ErrorAction SilentlyContinue
    if ($null -eq $resolved) {
        return $null
    }

    try {
        $output = & $resolved.Source @Arguments 2>&1 | Select-Object -First 1
        if ($null -eq $output) {
            return $resolved.Source
        }
        return ([string]$output).Trim()
    }
    catch {
        return "present: $($resolved.Source); version probe failed: $($_.Exception.Message)"
    }
}

$controllers = @(Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, AdapterRAM, PNPDeviceID)
$os = Get-CimInstance Win32_OperatingSystem

$toolVersions = @{
    git = Get-StableAmdCommandVersion -Command 'git'
    dotnet = Get-StableAmdCommandVersion -Command 'dotnet'
    py = Get-StableAmdCommandVersion -Command 'py'
    python = Get-StableAmdCommandVersion -Command 'python'
    hipinfo = Get-StableAmdCommandVersion -Command 'hipinfo' -Arguments @('--version')
    offloadArch = Get-StableAmdCommandVersion -Command 'offload-arch' -Arguments @('--version')
}

$record = New-StableAmdPreflightRecord `
    -VideoControllers $controllers `
    -OsCaption ([string]$os.Caption) `
    -OsVersion ([string]$os.Version) `
    -OsBuild ([string]$os.BuildNumber) `
    -CommandVersions $toolVersions

$amdControllers = @($record.Gpus | Where-Object { $_.Name -match '(?i)AMD|Radeon' })
$targetControllers = @($record.Gpus | Where-Object { $_.GfxTarget -eq 'gfx1030' })

$record | Add-Member -NotePropertyName Summary -NotePropertyValue ([pscustomobject]@{
    HasAmdGpu = ($amdControllers.Count -gt 0)
    HasGfx1030 = ($targetControllers.Count -gt 0)
    RecommendedSpikeMode = 'Baseline'
    WindowsSupportWarning = 'RX 6950 XT is not listed as supported in AMD Windows HIP SDK compatibility tables. Treat ROCm on this GPU as experimental.'
})

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outputPath = Join-Path $OutputDirectory "preflight-$stamp.json"
$record | ConvertTo-Json -Depth 8 | Set-Content -Path $outputPath -Encoding UTF8

Write-Host ''
Write-Host 'StableAMD AMD preflight' -ForegroundColor Cyan
Write-Host "Windows: $($record.Os.Caption) $($record.Os.Version) build $($record.Os.Build)"
foreach ($gpu in $record.Gpus) {
    $target = if ($gpu.GfxTarget) { $gpu.GfxTarget } else { 'unclassified' }
    Write-Host "GPU: $($gpu.Name) | driver $($gpu.DriverVersion) | $target | $($gpu.SupportTier)"
}
Write-Host "Git: $($record.Tools.git)"
Write-Host "dotnet: $($record.Tools.dotnet)"
Write-Host "Existing HSA override: $($record.Environment.HsaOverrideGfxVersion)"
Write-Host "Report: $outputPath" -ForegroundColor Green

if (-not $record.Summary.HasGfx1030) {
    Write-Warning 'No supported spike target (gfx1030 / RX 6950 XT family) was detected. Review the report before continuing.'
}
else {
    Write-Warning $record.Summary.WindowsSupportWarning
    Write-Host 'Next test should be Baseline mode, with no HSA_OVERRIDE_GFX_VERSION.' -ForegroundColor Yellow
}

if ($PassThru) {
    return $record
}
