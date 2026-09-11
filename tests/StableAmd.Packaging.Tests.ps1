Describe 'StableAMD v0.1 release packaging' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
    }

    It 'ships a packaging script, runtime lock and acceptance document' {
        Test-Path (Join-Path $repoRoot 'scripts/Build-StableAMDPackage.ps1') | Should -BeTrue
        Test-Path (Join-Path $repoRoot 'config/runtime-lock.v0.1.json') | Should -BeTrue
        Test-Path (Join-Path $repoRoot 'docs/v0.1-validation.md') | Should -BeTrue
    }

    It 'records the proven gfx1030 runtime versions' {
        $lockPath = Join-Path $repoRoot 'config/runtime-lock.v0.1.json'
        Test-Path $lockPath | Should -BeTrue

        $lock = Get-Content -Path $lockPath -Raw | ConvertFrom-Json
        $lock.schemaVersion | Should -Be 1
        $lock.release | Should -Be '0.1.0'
        $lock.gpu.gfxTarget | Should -Be 'gfx1030'
        $lock.runtime.torch | Should -Be '2.13.0+rocm10.1.0a20260822'
        $lock.runtime.comfyui | Should -Be '0.35.0'
        $lock.runtime.indexUrl | Should -Be 'https://rocm.nightlies.amd.com/whl-multi-arch/'
    }

    It 'builds a source package without runtime, diagnostics, tests, git metadata or models' {
        $buildScript = Join-Path $repoRoot 'scripts/Build-StableAMDPackage.ps1'
        Test-Path $buildScript | Should -BeTrue

        $output = Join-Path $TestDrive 'dist'
        $result = & $buildScript -RepoRoot $repoRoot -OutputDirectory $output -Version '0.1.0-test'

        Test-Path $result.ZipPath | Should -BeTrue
        Test-Path $result.PackageRoot | Should -BeTrue
        Test-Path (Join-Path $result.PackageRoot 'Start-StableAMD.cmd') | Should -BeTrue
        Test-Path (Join-Path $result.PackageRoot 'app/backend/stableamd_server.py') | Should -BeTrue
        Test-Path (Join-Path $result.PackageRoot 'app/frontend/index.html') | Should -BeTrue
        Test-Path (Join-Path $result.PackageRoot 'config/stableamd.default.json') | Should -BeTrue
        Test-Path (Join-Path $result.PackageRoot 'config/runtime-lock.v0.1.json') | Should -BeTrue
        Test-Path (Join-Path $result.PackageRoot 'scripts/Launch-StableAMD.ps1') | Should -BeTrue
        Test-Path (Join-Path $result.PackageRoot 'README.md') | Should -BeTrue
        Test-Path (Join-Path $result.PackageRoot '.runtime') | Should -BeFalse
        Test-Path (Join-Path $result.PackageRoot 'diagnostics') | Should -BeFalse
        Test-Path (Join-Path $result.PackageRoot 'tests') | Should -BeFalse
        Test-Path (Join-Path $result.PackageRoot '.git') | Should -BeFalse
    }

    It 'documents the remaining hardware acceptance gate instead of claiming unverified clean-install support' {
        $validation = Get-Content -Path (Join-Path $repoRoot 'docs/v0.1-validation.md') -Raw
        $validation | Should -Match 'RX 6950 XT'
        $validation | Should -Match 'gfx1030'
        $validation | Should -Match '2\.13\.0\+rocm10\.1\.0a20260822'
        $validation | Should -Match '1024x1024'
        $validation | Should -Match 'clean-machine'
        $validation | Should -Match 'pending'
    }
}
