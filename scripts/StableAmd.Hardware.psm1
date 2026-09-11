Set-StrictMode -Version 2.0

function Resolve-StableAmdGfxTarget {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    if ($Name -match '(?i)\bRadeon\s+RX\s+(6950\s+XT|6900\s+XT|6800(?:\s+XT)?)\b') {
        return 'gfx1030'
    }

    return $null
}

function Get-StableAmdSupportTier {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $gfxTarget = Resolve-StableAmdGfxTarget -Name $Name

    if ($gfxTarget -eq 'gfx1030') {
        return [pscustomobject]@{
            GfxTarget = $gfxTarget
            Tier = 'experimental-windows'
            OfficialWindowsHipSdkSupport = $false
            Notes = 'RDNA2 gfx1030 is build/sanity-tested in TheRock on Windows, but RX 6950 XT is not listed as supported in AMD Windows HIP SDK compatibility tables.'
        }
    }

    return [pscustomobject]@{
        GfxTarget = $gfxTarget
        Tier = 'unknown'
        OfficialWindowsHipSdkSupport = $false
        Notes = 'No StableAMD support classification is defined for this GPU in the RX 6950 XT validation spike.'
    }
}

function New-StableAmdPreflightRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$VideoControllers,

        [Parameter(Mandatory = $true)]
        [string]$OsCaption,

        [Parameter(Mandatory = $true)]
        [string]$OsVersion,

        [Parameter(Mandatory = $true)]
        [string]$OsBuild,

        [Parameter(Mandatory = $true)]
        [hashtable]$CommandVersions
    )

    $gpuRecords = @()
    foreach ($controller in $VideoControllers) {
        $name = [string]$controller.Name
        $support = Get-StableAmdSupportTier -Name $name

        $gpuRecords += [pscustomobject]@{
            Name = $name
            DriverVersion = [string]$controller.DriverVersion
            AdapterRAM = $controller.AdapterRAM
            GfxTarget = $support.GfxTarget
            SupportTier = $support.Tier
            OfficialWindowsHipSdkSupport = $support.OfficialWindowsHipSdkSupport
            Notes = $support.Notes
        }
    }

    return [pscustomobject]@{
        SchemaVersion = 1
        CreatedAtUtc = [DateTime]::UtcNow.ToString('o')
        Os = [pscustomobject]@{
            Caption = $OsCaption
            Version = $OsVersion
            Build = $OsBuild
        }
        Gpus = @($gpuRecords)
        Tools = $CommandVersions
        Environment = [pscustomobject]@{
            HsaOverrideGfxVersion = [Environment]::GetEnvironmentVariable('HSA_OVERRIDE_GFX_VERSION')
        }
    }
}

function Get-StableAmdSpikeEnvironment {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('Baseline', 'GfxOverride')]
        [string]$Mode
    )

    $result = @{}
    if ($Mode -eq 'GfxOverride') {
        $result['HSA_OVERRIDE_GFX_VERSION'] = '10.3.0'
    }

    return $result
}

function Test-StableAmdDotNet8Sdk {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$SdkList
    )

    foreach ($sdk in $SdkList) {
        if ([string]$sdk -match '^8\.0\.\d+\s') {
            return $true
        }
    }

    return $false
}

function Resolve-StableAmdSwarmUrl {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [string[]]$LogLines
    )

    for ($i = $LogLines.Count - 1; $i -ge 0; $i--) {
        $line = [string]$LogLines[$i]
        if ($line -match '(?i)Starting webserver on\s+https?://(?:localhost|127\.0\.0\.1):(?<port>\d+)') {
            return "http://127.0.0.1:$($Matches['port'])/"
        }
    }

    return $null
}

function Get-StableAmdTheRockInstallArgs {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [ValidatePattern('^gfx\d+$')]
        [string]$GfxTarget
    )

    return [pscustomobject]@{
        IndexUrl = 'https://rocm.nightlies.amd.com/whl-multi-arch/'
        Packages = @(
            "torch[device-$GfxTarget]",
            "torchvision[device-$GfxTarget]",
            'torchaudio'
        )
    }
}

Export-ModuleMember -Function Resolve-StableAmdGfxTarget, Get-StableAmdSupportTier, New-StableAmdPreflightRecord, Get-StableAmdSpikeEnvironment, Test-StableAmdDotNet8Sdk, Resolve-StableAmdSwarmUrl, Get-StableAmdTheRockInstallArgs
