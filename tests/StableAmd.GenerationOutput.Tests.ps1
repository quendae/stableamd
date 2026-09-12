BeforeAll {
    $modulePath = Join-Path $PSScriptRoot '../scripts/StableAmd.Generation.psm1'
    Import-Module $modulePath -Force
}

Describe 'StableAMD generated image resolution' {
    It 'uses SaveImage history metadata when ComfyUI returns it' {
        $outputRoot = Join-Path $TestDrive 'output-history'
        New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
        $imagePath = Join-Path $outputRoot 'StableAMD_SDXL_known_00001_.png'
        Set-Content -Path $imagePath -Value 'png' -Encoding Ascii

        $historyEntry = [pscustomobject]@{
            outputs = [pscustomobject]@{
                '9' = [pscustomobject]@{
                    images = @(
                        [pscustomobject]@{
                            filename = 'StableAMD_SDXL_known_00001_.png'
                            subfolder = ''
                            type = 'output'
                        }
                    )
                }
            }
        }

        $resolved = Resolve-StableAmdGeneratedImagePath `
            -HistoryEntry $historyEntry `
            -OutputRoot $outputRoot `
            -FilenamePrefix 'StableAMD_SDXL_known'

        $resolved | Should -Be ([IO.Path]::GetFullPath($imagePath))
    }

    It 'falls back to the unique generation prefix when successful Comfy history has no image metadata' {
        $outputRoot = Join-Path $TestDrive 'output-fallback'
        New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
        Set-Content -Path (Join-Path $outputRoot 'StableAMD_SDXL_other_00001_.png') -Value 'old' -Encoding Ascii
        $expected = Join-Path $outputRoot 'StableAMD_SDXL_abc123_00001_.png'
        Set-Content -Path $expected -Value 'png' -Encoding Ascii

        $historyEntry = [pscustomobject]@{
            outputs = [pscustomobject]@{
                '9' = [pscustomobject]@{ images = @() }
            }
            status = [pscustomobject]@{
                status_str = 'success'
                completed = $true
            }
        }

        $resolved = Resolve-StableAmdGeneratedImagePath `
            -HistoryEntry $historyEntry `
            -OutputRoot $outputRoot `
            -FilenamePrefix 'StableAMD_SDXL_abc123'

        $resolved | Should -Be ([IO.Path]::GetFullPath($expected))
    }

    It 'does not substitute an unrelated image when neither history nor the unique prefix resolves' {
        $outputRoot = Join-Path $TestDrive 'output-missing'
        New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
        Set-Content -Path (Join-Path $outputRoot 'StableAMD_SDXL_someone_else_00001_.png') -Value 'old' -Encoding Ascii

        $historyEntry = [pscustomobject]@{
            outputs = [pscustomobject]@{
                '9' = [pscustomobject]@{ images = @() }
            }
        }

        Resolve-StableAmdGeneratedImagePath `
            -HistoryEntry $historyEntry `
            -OutputRoot $outputRoot `
            -FilenamePrefix 'StableAMD_SDXL_missing' | Should -BeNullOrEmpty
    }
}

Describe 'StableAMD generation output correlation' {
    It 'uses a per-generation mode-aware filename prefix and the output resolver' {
        $script = Get-Content (Join-Path $PSScriptRoot '../scripts/Invoke-Txt2Img.ps1') -Raw

        $script | Should -Match 'generationToken'
        $script | Should -Match 'modeToken'
        $script | Should -Match 'StableAMD_SDXL_\$\{modeToken\}_\$generationToken'
        $script | Should -Match 'Resolve-StableAmdGeneratedImagePath'
        $script | Should -Not -Match "FilenamePrefix 'StableAMD_SDXL'"
    }
}
