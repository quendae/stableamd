Describe 'StableAMD clean-machine runtime bootstrap' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $installerPath = Join-Path $repoRoot 'scripts/Install-StableAMDRuntime.ps1'
        $launcherPath = Join-Path $repoRoot 'scripts/Launch-StableAMD.ps1'
    }

    It 'ships an installer with a deterministic no-network plan mode' {
        Test-Path $installerPath | Should -BeTrue

        $plan = & $installerPath -RepoRoot $repoRoot -PlanOnly
        $plan.PythonVersion | Should -Be '3.12.10'
        $plan.GfxTarget | Should -Be 'gfx1030'
        $plan.PythonArchiveUrl | Should -Be 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'
        $plan.PythonArchiveSha256 | Should -Be '4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3'
        $plan.GetPipUrl | Should -Be 'https://bootstrap.pypa.io/get-pip.py'
        $plan.TheRockIndexUrl | Should -Be 'https://rocm.nightlies.amd.com/whl-multi-arch/'
        $plan.TorchPackage | Should -Be 'torch[device-gfx1030]==2.13.0+rocm10.1.0a20260822'
        $plan.TorchVisionPackage | Should -Be 'torchvision[device-gfx1030]==0.28.0+rocm10.1.0a20260822'
        $plan.TorchAudioPackage | Should -Be 'torchaudio==2.11.0+rocm10.1.0a20260822'
        $plan.ComfyVersion | Should -Be '0.35.0'
        $plan.ComfyCommit | Should -Be '40c4fcdf513a4523e39d54a9d391908af8df8171'
    }

    It 'uses an actually portable embedded Python runtime so repeated isolated installs do not register globally' {
        $script = Get-Content -Path $installerPath -Raw
        $script | Should -Match 'python-\$pythonVersion-embed-amd64\.zip'
        $script | Should -Match 'Expand-Archive'
        $script | Should -Match 'python312\._pth'
        $script | Should -Match 'import site'
        $script | Should -Match 'get-pip\.py'
        $script | Should -Not -Match 'Start-Process\s+-FilePath\s+\$pythonInstaller'
        $script | Should -Not -Match 'InstallAllUsers=0'
    }

    It 'uses only the locked runtime versions rather than an unpinned nightly upgrade' {
        $script = Get-Content -Path $installerPath -Raw
        $script | Should -Match 'runtime-lock\.v0\.1\.json'
        $script | Should -Match 'device-\$gfxTarget'
        $script | Should -Match 'torchvision'
        $script | Should -Match 'torchaudio'
        $script | Should -Match 'amd_backend_probe\.py'
        $script | Should -Not -Match "torch\[device-\$gfxTarget\]'\s*,?\s*$"
    }

    It 'pins ComfyUI by immutable commit and installs its product dependencies after ROCm' {
        $script = Get-Content -Path $installerPath -Raw
        $script | Should -Match 'ComfyCommit'
        $script | Should -Match 'archive/.+\.zip'
        $script | Should -Match 'requirements\.txt'
        $script | Should -Match 'pip.+install'
    }

    It 'makes the one-click launcher repair a missing runtime automatically' {
        $launcher = Get-Content -Path $launcherPath -Raw
        $launcher | Should -Match 'Install-StableAMDRuntime\.ps1'
        $launcher | Should -Match 'ComfyRoot'
        $launcher | Should -Match 'TheRockPython'
        $launcher | Should -Match 'runtime.+missing'
    }
}
