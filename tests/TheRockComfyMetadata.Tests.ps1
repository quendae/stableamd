Describe 'TheRock ComfyUI source metadata' {
    It 'persists the source commit before removing isolated git metadata' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/Test-TheRockComfy.ps1'
        Test-Path $scriptPath | Should -BeTrue

        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'stableamd-source-commit'
        $script | Should -Match 'Set-Content.*sourceCommitMarker'
        $script | Should -Match 'Get-Content.*sourceCommitMarker'
    }
}
