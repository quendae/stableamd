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
}
