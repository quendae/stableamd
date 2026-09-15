Describe 'StableAMD derived registry recovery' {
    It 'quarantines a corrupt checkpoint registry and rebuilds valid JSON' {
        $repoRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-registry-recovery-' + [guid]::NewGuid().ToString('N'))
        $runtimeRoot = Join-Path $repoRoot '.runtime/stableamd'
        New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
        $modelsPath = Join-Path $runtimeRoot 'models.json'
        [IO.File]::WriteAllText($modelsPath, '{"schemaVersion":1,"models":[')

        try {
            $script = Join-Path $PSScriptRoot '../scripts/List-Models.ps1'
            $result = & $script -RepoRoot $repoRoot

            @($result.models).Count | Should -Be 0
            { Get-Content -LiteralPath $modelsPath -Raw | ConvertFrom-Json } | Should -Not -Throw
            @(Get-ChildItem -LiteralPath $runtimeRoot -Filter 'models.json.corrupt-*' -File).Count | Should -Be 1
        }
        finally {
            Remove-Item -LiteralPath $repoRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'replaces a broken bundle registry with one complete JSON document' {
        $repoRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-bundle-registry-recovery-' + [guid]::NewGuid().ToString('N'))
        $runtimeRoot = Join-Path $repoRoot '.runtime/stableamd'
        New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
        $bundlesPath = Join-Path $runtimeRoot 'bundles.json'
        [IO.File]::WriteAllText($bundlesPath, '{broken-json')

        try {
            $script = Join-Path $PSScriptRoot '../scripts/List-BundleModels.ps1'
            $result = & $script -RepoRoot $repoRoot

            @($result.models).Count | Should -Be 2
            $registry = Get-Content -LiteralPath $bundlesPath -Raw | ConvertFrom-Json
            $registry.schemaVersion | Should -Be 1
            @($registry.bundles).Count | Should -Be 0
        }
        finally {
            Remove-Item -LiteralPath $repoRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
