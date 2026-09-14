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
        [AllowNull()][string]$Path,
        [Int64]$ExpectedBytes = 0,
        [string]$ExpectedSha256 = ''
    )

    $found = -not [string]::IsNullOrWhiteSpace($Path)
    $resolvedPath = if ($found) { [IO.Path]::GetFullPath($Path) } else { $null }
    $actualBytes = $null
    $sizeValid = $true
    if ($found) {
        try {
            $actualBytes = [Int64](Get-Item -LiteralPath $resolvedPath -ErrorAction Stop).Length
        }
        catch {
            $found = $false
            $resolvedPath = $null
        }
    }
    if ($found -and $ExpectedBytes -gt 0) {
        $sizeValid = $actualBytes -eq $ExpectedBytes
    }

    # For official very-large packages, a byte-length mismatch is a cheap and
    # reliable signal that a browser/Xet/LFS download is incomplete. Do not hash
    # multi-gigabyte assets on every model refresh; the pinned SHA is exposed as
    # metadata for explicit/manual verification when needed.
    $usable = $found -and $sizeValid
    $displayLabel = $Label
    $problem = $null
    if ($found -and -not $sizeValid) {
        $displayLabel = "$Label · incomplete/corrupt file"
        $problem = "Found $actualBytes bytes; expected $ExpectedBytes bytes. Re-download $ExpectedName."
    }

    return [pscustomobject]@{
        role = $Role
        label = $displayLabel
        expectedName = $ExpectedName
        path = $resolvedPath
        present = $usable
        found = $found
        actualBytes = $actualBytes
        expectedBytes = if ($ExpectedBytes -gt 0) { $ExpectedBytes } else { $null }
        expectedSha256 = if ([string]::IsNullOrWhiteSpace($ExpectedSha256)) { $null } else { $ExpectedSha256.ToLowerInvariant() }
        integrity = if (-not $found) { 'missing' } elseif ($sizeValid) { 'size-ok' } else { 'size-mismatch' }
        problem = $problem
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
    # Byte lengths and SHA-256 values are pinned from Comfy-Org/Krea-2. The
    # scanner checks length immediately, while SHA remains available for an
    # explicit integrity check without re-hashing ~18.6 GB on every refresh.
    $kDiffusion = Find-StableAmdTemplateAsset -Roots $DiffusionRoots -FileName 'krea2_turbo_fp8_scaled.safetensors'
    $kEncoder = Find-StableAmdTemplateAsset -Roots $TextEncoderRoots -FileName 'qwen3vl_4b_fp8_scaled.safetensors'
    $kVae = Find-StableAmdTemplateAsset -Roots $VaeRoots -FileName 'qwen_image_vae.safetensors'
    $kComponents = @(
        New-StableAmdTemplateComponent -Role 'diffusion_model' -Label 'Diffusion model (FP8)' -ExpectedName 'krea2_turbo_fp8_scaled.safetensors' -Path $kDiffusion -ExpectedBytes 13141730784 -ExpectedSha256 'eb4dd8c612cfd10f64f25b057e6e6bbcb5737c94a7372177e456dbf7579502f1'
        New-StableAmdTemplateComponent -Role 'text_encoder' -Label 'Qwen3-VL text encoder (FP8)' -ExpectedName 'qwen3vl_4b_fp8_scaled.safetensors' -Path $kEncoder -ExpectedBytes 5242467968 -ExpectedSha256 '54bd5144df0bbc25dd6ccadfcb826b521445a1b06ae5a42570bdd2974ca87094'
        New-StableAmdTemplateComponent -Role 'vae' -Label 'Qwen Image VAE' -ExpectedName 'qwen_image_vae.safetensors' -Path $kVae -ExpectedBytes 253806246 -ExpectedSha256 'a70580f0213e67967ee9c95f05bb400e8fb08307e017a924bf3441223e023d1f'
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
