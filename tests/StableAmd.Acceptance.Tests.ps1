Describe 'StableAMD clean-package acceptance harness' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $acceptancePath = Join-Path $repoRoot 'scripts/Test-StableAMDPackage.ps1'
    }

    It 'ships an isolated package acceptance command' {
        Test-Path $acceptancePath | Should -BeTrue
        $script = Get-Content -Path $acceptancePath -Raw

        $script | Should -Match 'Build-StableAMDPackage\.ps1'
        $script | Should -Match 'Install-StableAMDRuntime\.ps1'
        $script | Should -Match 'Launch-StableAMD\.ps1'
        $script | Should -Match 'Get-StableAMDStatus\.ps1'
        $script | Should -Match 'Stop-StableAMD\.ps1'
        $script | Should -Match '/api/health'
        $script | Should -Match 'acceptance-package'
    }

    It 'does not reuse or delete the development repository runtime' {
        $script = Get-Content -Path $acceptancePath -Raw

        $script | Should -Match 'PackageRoot'
        $script | Should -Match 'AcceptanceRoot'
        $script | Should -Not -Match 'Remove-Item\s+-Path\s+\$repoRoot.+\.runtime'
    }

    It 'supports plan-only validation without downloading the GPU runtime' {
        $script = Get-Content -Path $acceptancePath -Raw
        $script | Should -Match 'PlanOnly'
        $script | Should -Match 'runtimePlan'
    }
}
