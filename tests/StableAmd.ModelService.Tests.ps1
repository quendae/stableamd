Describe 'StableAMD model service serialization' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $listModelsScript = Join-Path $repoRoot 'scripts/List-Models.ps1'
    }

    It 'returns a stable model envelope for an empty library' {
        $isolatedRoot = Join-Path $TestDrive 'empty-model-repo'
        New-Item -ItemType Directory -Path $isolatedRoot -Force | Out-Null

        $result = & $listModelsScript -RepoRoot $isolatedRoot

        $result.count | Should -Be 0
        @($result.models).Count | Should -Be 0
    }

    It 'serializes the same empty model envelope under Windows PowerShell 5.1' {
        $windowsPowerShell = Get-Command powershell.exe -ErrorAction SilentlyContinue
        if ($null -eq $windowsPowerShell) {
            Set-ItResult -Skipped -Because 'powershell.exe is unavailable'
            return
        }

        $isolatedRoot = Join-Path $TestDrive 'empty-model-repo-ps5'
        New-Item -ItemType Directory -Path $isolatedRoot -Force | Out-Null
        $escapedScript = $listModelsScript.Replace("'", "''")
        $escapedRoot = $isolatedRoot.Replace("'", "''")
        $command = "`$WarningPreference = 'SilentlyContinue'; & '$escapedScript' -RepoRoot '$escapedRoot' | ConvertTo-Json -Depth 20 -Compress"

        $json = (& $windowsPowerShell.Source -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $command | Out-String).Trim()
        $parsed = $json | ConvertFrom-Json

        $LASTEXITCODE | Should -Be 0
        $parsed.count | Should -Be 0
        @($parsed.models).Count | Should -Be 0
    }
}
