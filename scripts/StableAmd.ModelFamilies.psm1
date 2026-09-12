Set-StrictMode -Version 2.0

function Get-StableAmdModelFamily {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $leaf = [IO.Path]::GetFileNameWithoutExtension($Name)
    if ([string]::IsNullOrWhiteSpace($leaf)) { return 'unknown' }

    # Most specific families must be checked before their parent lineages.
    if ($leaf -match '(?i)(?:^|[._ -])krea[._ -]?2(?:[._ -]|$)|^krea2(?:[._ -]|$)') {
        return 'krea2'
    }
    if ($leaf -match '(?i)(?:^|[._ -])flux(?:[._ -]?[12])?(?:[._ -]|$)|^flux[12](?:[._ -]|$)') {
        return 'flux'
    }
    if ($leaf -match '(?i)(?:sd|stable[._ -]?diffusion)[._ -]?3[._-]?5[._ -]?large(?:[._ -]|$)') {
        return 'sd35-large'
    }
    if ($leaf -match '(?i)(?:sd|stable[._ -]?diffusion)[._ -]?3[._-]?5[._ -]?medium(?:[._ -]|$)') {
        return 'sd35-medium'
    }
    if ($leaf -match '(?i)(?:sd|stable[._ -]?diffusion)[._ -]?3(?:[._ -]?medium)?(?:[._ -]|$)') {
        return 'sd3'
    }
    if ($leaf -match '(?i)(?:sd[._ -]?xl|sdxl).*turbo|turbo.*(?:sd[._ -]?xl|sdxl)') {
        return 'sdxl-turbo'
    }
    if ($leaf -match '(?i)(?:sd[._ -]?xl|sdxl|xl(?:[._ -]|$))') {
        return 'sdxl'
    }
    if ($leaf -match '(?i)(?:stable[._ -]?diffusion[._ -]?2[._-]?1|sd[._ -]?2[._-]?1|v2[._-]?1)(?:[._ -]|$)') {
        return 'sd21'
    }
    if ($leaf -match '(?i)(?:stable[._ -]?diffusion[._ -]?1[._-]?5|sd[._ -]?1[._-]?5|v1[._-]?5)(?:[._ -]|$)') {
        return 'sd15'
    }

    return 'unknown'
}

Export-ModuleMember -Function Get-StableAmdModelFamily
