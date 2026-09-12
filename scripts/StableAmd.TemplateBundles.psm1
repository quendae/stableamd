Set-StrictMode -Version 2.0

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Bundles.psm1') -Force

function Find-StableAmdTemplateAsset {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string[]]$Roots,
        [Parameter(Mandatory = $true)][string]$FileName
    )

    foreach ($root in @($Roots)) {
        if ([string]::IsNullOrWhiteSpace([string]$root)) { continue }
        $resolved = [IO.Path]::GetFullPath([string]$root)
        if (-not (Test-Path $resolved -PathType Container)) { continue }

        $match = Get-ChildItem -LiteralPath $resolved -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name.Equals($FileName, [StringComparison]::OrdinalIgnoreCase) } |
            Sort-Object FullName |
            Select-Object -First 1
        if ($null -ne $match) { return [IO.Path]::GetFullPath($match.FullName) }
    }
    return $null
}

function Find-StableAmdTemplateBundles {
    [CmdletBinding()]
    param(
        [string[]]$DiffusionRoots = @(),
        [string[]]$TextEncoderRoots = @(),
        [string[]]$VaeRoots = @()
    )

    $bundles = @()

    # Official ComfyUI template: image_z_image_turbo.json
    $diffusion = Find-StableAmdTemplateAsset -Roots $DiffusionRoots -FileName 'z_image_turbo_bf16.safetensors'
    $encoder = Find-StableAmdTemplateAsset -Roots $TextEncoderRoots -FileName 'qwen_3_4b.safetensors'
    $vae = Find-StableAmdTemplateAsset -Roots $VaeRoots -FileName 'ae.safetensors'

    if ($null -ne $diffusion -and $null -ne $encoder -and $null -ne $vae) {
        $bundles += New-StableAmdBundleEntry `
            -Family 'z-image-turbo' `
            -Name 'Z-Image Turbo' `
            -Provider 'z-image-turbo-bundle' `
            -Assets @{
                diffusion_model = @($diffusion)
                text_encoder = @($encoder)
                vae = @($vae)
            }
    }

    return @($bundles)
}

Export-ModuleMember -Function Find-StableAmdTemplateBundles
