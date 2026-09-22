Describe 'StableAMD v0.3 module import composition' {
    It 'keeps generation helper commands available after workflow modules load' {
        $generationModule = Join-Path $PSScriptRoot '../scripts/StableAmd.Generation.psm1'
        $workflowsModule = Join-Path $PSScriptRoot '../scripts/StableAmd.Workflows.psm1'

        Remove-Module StableAmd.Workflows, StableAmd.Img2Img, StableAmd.Generation -Force -ErrorAction SilentlyContinue
        try {
            Import-Module $generationModule -Force
            Import-Module $workflowsModule -Force

            Get-Command New-StableAmdRandomSeed -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
            Get-Command Resolve-StableAmdComfyCheckpointName -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
            Get-Command Resolve-StableAmdGeneratedImagePath -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
        }
        finally {
            Remove-Module StableAmd.Workflows, StableAmd.Img2Img, StableAmd.Generation -Force -ErrorAction SilentlyContinue
        }
    }

    It 'keeps runtime and bundle helper commands available after dependent bundle modules load' {
        $runtimeModule = Join-Path $PSScriptRoot '../scripts/StableAmd.Runtime.psm1'
        $bundleRootsModule = Join-Path $PSScriptRoot '../scripts/StableAmd.BundleRoots.psm1'
        $bundlesModule = Join-Path $PSScriptRoot '../scripts/StableAmd.Bundles.psm1'
        $templateBundlesModule = Join-Path $PSScriptRoot '../scripts/StableAmd.TemplateBundles.psm1'

        Remove-Module StableAmd.TemplateBundles, StableAmd.Bundles, StableAmd.BundleRoots, StableAmd.Runtime -Force -ErrorAction SilentlyContinue
        try {
            Import-Module $runtimeModule -Force
            Import-Module $bundleRootsModule -Force
            Import-Module $bundlesModule -Force
            Import-Module $templateBundlesModule -Force

            Get-Command Get-StableAmdRuntimePaths -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
            Get-Command Initialize-StableAmdRuntimeDirectories -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
            Get-Command Test-StableAmdBundleEntry -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
            Get-Command New-StableAmdEmptyBundleRegistry -ErrorAction SilentlyContinue | Should -Not -BeNullOrEmpty
        }
        finally {
            Remove-Module StableAmd.TemplateBundles, StableAmd.Bundles, StableAmd.BundleRoots, StableAmd.Runtime -Force -ErrorAction SilentlyContinue
        }
    }

    It 'keeps Character Sheet v2 modules in the final server composition' {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $identityModule = Join-Path $repoRoot 'app/backend/stableamd_v03_krea_identity_edit.py'
        $sheetModule = Join-Path $repoRoot 'app/backend/stableamd_v03_character_sheet_v2.py'
        $finalServer = Join-Path $repoRoot 'app/backend/stableamd_v03_edit_server.py'

        Test-Path $identityModule -PathType Leaf | Should -BeTrue
        Test-Path $sheetModule -PathType Leaf | Should -BeTrue
        Test-Path $finalServer -PathType Leaf | Should -BeTrue

        $serverSource = Get-Content -Path $finalServer -Raw
        $serverSource | Should -Match 'stableamd_v03_krea_identity_edit'
        $serverSource | Should -Match 'stableamd_v03_character_sheet_v2'
        $serverSource | Should -Match 'CharacterSheetV2BridgeMixin'
        $serverSource | Should -Match 'CharacterSheetV2ApiMixin'
    }
}