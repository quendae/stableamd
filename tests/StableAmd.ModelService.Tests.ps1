Describe 'StableAMD model service serialization' {
    BeforeAll {
        $repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        $listModelsScript = Join-Path $repoRoot 'scripts/List-Models.ps1'
    }

    It 'serializes an empty model library as a JSON array' {
        $isolatedRoot = Join-Path $TestDrive 'empty-model-repo'
        New-Item -ItemType Directory -Path $isolatedRoot -Force | Out-Null

        $json = & $listModelsScript -RepoRoot $isolatedRoot | ConvertTo-Json -Depth 20 -Compress

        $json | Should -Be '[]'
    }

    It 'serializes an empty model library as a JSON array under Windows PowerShell 5.1' {
        $windowsPowerShell = Get-Command powershell.exe -ErrorAction SilentlyContinue
        if ($null -eq $windowsPowerShell) {
            Set-ItResult -Skipped -Because 'powershell.exe is unavailable'
            return
        }

        $isolatedRoot = Join-Path $TestDrive 'empty-model-repo-ps5'
        New-Item -ItemType Directory -Path $isolatedRoot -Force | Out-Null
        $escapedScript = $listModelsScript.Replace("'", "''")
        $escapedRoot = $isolatedRoot.Replace("'", "''")
        $command = "& '$escapedScript' -RepoRoot '$escapedRoot' | ConvertTo-Json -Depth 20 -Compress"

        $json = (& $windowsPowerShell.Source -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command $command | Out-String).Trim()

        $LASTEXITCODE | Should -Be 0
        $json | Should -Be '[]'
    }
}
