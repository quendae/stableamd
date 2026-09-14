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

function New-StableAmdTemplatePackage {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Family,
        [Parameter(Mandatory = $true)][string]$Provider,
        [Parameter(Mandatory = $true)][object[]]$Components
    )

    $ready = @($Components | Where-Object { -not $_.present }).Count -eq 0
    $diffusionAssets = @($Components | Where-Object { $_.role -eq 'diffusion_model' -and $_.present } | ForEach-Object { $_.path })
    $encoderAssets = @($Components | Where-Object { $_.role -eq 'text_encoder' -and $_.present } | ForEach-Object { $_.path })
    $vaeAssets = @($Components | Where-Object { $_.role -eq 'vae' -and $_.present } | ForEach-Object { $_.path })

    return [pscustomobject]@{
        id = Get-StableAmdBundleId -Family $Family -Name $Name
        name = $Name
        family = $Family
        provider = $Provider
        assetMode = 'bundle'
        ready = $ready
        status = if ($ready) { 'ready' } else { 'incomplete' }
        components = [object[]]@($Components)
        assets = [pscustomobject]@{
            diffusion_model = [object[]]@($diffusionAssets)
            text_encoder = [object[]]@($encoderAssets)
            vae = [object[]]@($vaeAssets)
        }
        updatedAtUtc = [DateTime]::UtcNow.ToString('o')
    }
}

function Find-StableAmdTemplatePackages {
    [CmdletBinding()]
    param(
        [string[]]$DiffusionRoots = @(),
        [string[]]$TextEncoderRoots = @(),
        [string[]]$VaeRoots = @()
    )

    # Official ComfyUI template: image_z_image_turbo.json.
    $zDiffusion = Find-StableAmdTemplateAsset -Roots $DiffusionRoots -FileName 'z_image_turbo_bf16.safetensors'
    $zEncoder = Find-StableAmdTemplateAsset -Roots $TextEncoderRoots -FileName 'qwen_3_4b.safetensors'
    $zVae = Find-StableAmdTemplateAsset -Roots $VaeRoots -FileName 'ae.safetensors'
    $zComponents = @(
        New-StableAmdTemplateComponent -Role 'diffusion_model' -Label 'Diffusion model' -ExpectedName 'z_image_turbo_bf16.safetensors' -Path $zDiffusion
        New-StableAmdTemplateComponent -Role 'text_encoder' -Label 'Text encoder' -ExpectedName 'qwen_3_4b.safetensors' -Path $zEncoder
        New-StableAmdTemplateComponent -Role 'vae' -Label 'VAE' -ExpectedName 'ae.safetensors' -Path $zVae
    )

    # Official ComfyUI Krea-2 Turbo package. FP8 is the first StableAMD target
    # because it is the realistic fit for a 16 GiB Radeon. RAW/BF16 can be
    # added as separate logical packages after the Turbo path is target-tested.
    $kDiffusion = Find-StableAmdTemplateAsset -Roots $DiffusionRoots -FileName 'krea2_turbo_fp8_scaled.safetensors'
    $kEncoder = Find-StableAmdTemplateAsset -Roots $TextEncoderRoots -FileName 'qwen3vl_4b_fp8_scaled.safetensors'
    $kVae = Find-StableAmdTemplateAsset -Roots $VaeRoots -FileName 'qwen_image_vae.safetensors'
    $kComponents = @(
        New-StableAmdTemplateComponent -Role 'diffusion_model' -Label 'Diffusion model (FP8)' -ExpectedName 'krea2_turbo_fp8_scaled.safetensors' -Path $kDiffusion
        New-StableAmdTemplateComponent -Role 'text_encoder' -Label 'Qwen3-VL text encoder (FP8)' -ExpectedName 'qwen3vl_4b_fp8_scaled.safetensors' -Path $kEncoder
        New-StableAmdTemplateComponent -Role 'vae' -Label 'Qwen Image VAE' -ExpectedName 'qwen_image_vae.safetensors' -Path $kVae
    )

    return @(
        New-StableAmdTemplatePackage -Name 'Z-Image Turbo' -Family 'z-image-turbo' -Provider 'z-image-turbo-bundle' -Components $zComponents
        New-StableAmdTemplatePackage -Name 'Krea 2 Turbo (FP8)' -Family 'krea2' -Provider 'krea2-bundle' -Components $kComponents
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
