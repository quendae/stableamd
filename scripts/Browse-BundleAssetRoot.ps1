[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [Parameter(Mandatory = $true)]
    [ValidateSet('diffusion_model', 'text_encoder', 'vae')]
    [string]$Role
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'Bundle asset folder browsing is available on Windows only.'
}
if ([string]::IsNullOrWhiteSpace($RepoRoot)) { $RepoRoot = Split-Path -Parent $PSScriptRoot }

$labels = @{
    diffusion_model = 'Select a folder containing diffusion models'
    text_encoder = 'Select a folder containing text encoders'
    vae = 'Select a folder containing VAE models'
}

$shell = New-Object -ComObject Shell.Application
try {
    $folder = $shell.BrowseForFolder(0, $labels[$Role], 0, 0)
    if ($null -eq $folder -or $null -eq $folder.Self -or [string]::IsNullOrWhiteSpace([string]$folder.Self.Path)) {
        return [pscustomobject]@{ cancelled = $true; role = $Role; path = $null }
    }
    $selected = [IO.Path]::GetFullPath([string]$folder.Self.Path)
    if (-not (Test-Path $selected -PathType Container)) { throw "Selected bundle asset folder does not exist: '$selected'." }
    return [pscustomobject]@{ cancelled = $false; role = $Role; path = $selected }
}
finally {
    if ($null -ne $shell) { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null }
}
