Set-StrictMode -Version 2.0

# Shared dependency: avoid -Force here so callers that already imported the
# bundle primitives do not lose their exported commands when templates load.
Import-Module (Join-Path $PSScriptRoot 'StableAmd.Bundles.psm1')

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

function New-StableAmdTemplateComponent {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Role,
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$ExpectedName,
        [AllowNull()][string]$Path
    )

    $present = -not [string]::IsNullOrWhiteSpace($Path)
    return [pscustomobject]@{
        role = $Role
        label = $Label
        expectedName = $ExpectedName
        path = if ($present) { [IO.Path]::GetFullPath($Path) } else { $null }
        present = $present
    }
}

function Find-StableAmdTemplatePackages {
    [CmdletBinding()]
    param(
        [string[]]$DiffusionRoots = @(),
        [string[]]$TextEncoderRoots = @(),
        [string[]]$VaeRoots = @()
    )

    # Official ComfyUI template: image_z_image_turbo.json
    # A package is returned even when incomplete so the product UI can explain
    # what is present and what is still missing instead of silently hiding it.
    $diffusion = Find-StableAmdTemplateAsset -Roots $DiffusionRoots -FileName 'z_image_turbo_bf16.safetensors'
    $encoder = Find-StableAmdTemplateAsset -Roots $TextEncoderRoots -FileName 'qwen_3_4b.safetensors'
    $vae = Find-StableAmdTemplateAsset -Roots $VaeRoots -FileName 'ae.safetensors'

    $components = @(
        New-StableAmdTemplateComponent -Role 'diffusion_model' -Label 'Diffusion model' -ExpectedName 'z_image_turbo_bf16.safetensors' -Path $diffusion
        New-StableAmdTemplateComponent -Role 'text_encoder' -Label 'Text encoder' -ExpectedName 'qwen_3_4b.safetensors' -Path $encoder
        New-StableAmdTemplateComponent -Role 'vae' -Label 'VAE' -ExpectedName 'ae.safetensors' -Path $vae
    )
    $ready = @($components | Where-Object { -not $_.present }).Count -eq 0

    $diffusionAssets = @($components | Where-Object { $_.role -eq 'diffusion_model' -and $_.present } | ForEach-Object { $_.path })
    $encoderAssets = @($components | Where-Object { $_.role -eq 'text_encoder' -and $_.present } | ForEach-Object { $_.path })
    $vaeAssets = @($components | Where-Object { $_.role -eq 'vae' -and $_.present } | ForEach-Object { $_.path })

    return @(
        [pscustomobject]@{
            id = Get-StableAmdBundleId -Family 'z-image-turbo' -Name 'Z-Image Turbo'
            name = 'Z-Image Turbo'
            family = 'z-image-turbo'
            provider = 'z-image-turbo-bundle'
            assetMode = 'bundle'
            ready = $ready
            status = if ($ready) { 'ready' } else { 'incomplete' }
            components = [object[]]@($components)
            assets = [pscustomobject]@{
                diffusion_model = [object[]]@($diffusionAssets)
                text_encoder = [object[]]@($encoderAssets)
                vae = [object[]]@($vaeAssets)
            }
            updatedAtUtc = [DateTime]::UtcNow.ToString('o')
        }
    )
}

function Find-StableAmdTemplateBundles {
    [CmdletBinding()]
    param(
        [string[]]$DiffusionRoots = @(),
        [string[]]$TextEncoderRoots = @(),
        [string[]]$VaeRoots = @()
    )

    return @(
        Find-StableAmdTemplatePackages `
            -DiffusionRoots $DiffusionRoots `
            -TextEncoderRoots $TextEncoderRoots `
            -VaeRoots $VaeRoots |
            Where-Object { $_.ready }
    )
}

Export-ModuleMember -Function Find-StableAmdTemplatePackages, Find-StableAmdTemplateBundles
