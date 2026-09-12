[CmdletBinding()]
param([string]$RepoRoot = '')

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'LoRA folder browsing is available on Windows only.'
}
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path -Parent $PSScriptRoot }

$shell = New-Object -ComObject Shell.Application
try {
    $folder = $shell.BrowseForFolder(0, 'Select a folder containing LoRA files', 0, 0)
    if ($null -eq $folder -or $null -eq $folder.Self -or [string]::IsNullOrWhiteSpace([string]$folder.Self.Path)) {
        return [pscustomobject]@{ cancelled = $true; path = $null }
    }
    $selected = [IO.Path]::GetFullPath([string]$folder.Self.Path)
    if (-not (Test-Path $selected -PathType Container)) { throw "Selected LoRA folder does not exist: '$selected'." }
    return [pscustomobject]@{ cancelled = $false; path = $selected }
}
finally {
    if ($null -ne $shell) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null }
}
