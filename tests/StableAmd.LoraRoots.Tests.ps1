BeforeAll {
    $modulePath = Join-Path $PSScriptRoot '../scripts/StableAmd.ModelRoots.psm1'
    Import-Module $modulePath -Force
}

Describe 'StableAMD LoRA root management' {
    It 'adds lists and removes an external LoRA folder without copying files' {
        $tempRepo = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-lora-roots-' + [guid]::NewGuid().ToString('N'))
        $externalRoot = Join-Path $tempRepo 'external-loras'
        New-Item -ItemType Directory -Path $externalRoot -Force | Out-Null
        try {
            $added = Add-StableAmdLoraRoot -RepoRoot $tempRepo -Path $externalRoot
            $added.added | Should -BeTrue
            $added.kind | Should -Be 'loras'

            $roots = @(Get-StableAmdLoraRootRecords -RepoRoot $tempRepo)
            @($roots | Where-Object { $_.path -eq [IO.Path]::GetFullPath($externalRoot) }).Count | Should -Be 1

            $removed = Remove-StableAmdLoraRoot -RepoRoot $tempRepo -Path $externalRoot
            $removed.removed | Should -BeTrue
            @((Get-StableAmdLoraRootRecords -RepoRoot $tempRepo) | Where-Object { $_.path -eq [IO.Path]::GetFullPath($externalRoot) }).Count | Should -Be 0
        }
        finally {
            Remove-Item -Path $tempRepo -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'does not allow removal of the StableAMD managed LoRA directory' {
        $tempRepo = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-managed-lora-root-' + [guid]::NewGuid().ToString('N'))
        try {
            Import-Module (Join-Path $PSScriptRoot '../scripts/StableAmd.Runtime.psm1') -Force
            $paths = Get-StableAmdRuntimePaths -RepoRoot $tempRepo
            Initialize-StableAmdRuntimeDirectories -Paths $paths
            { Remove-StableAmdLoraRoot -RepoRoot $tempRepo -Path $paths.LorasRoot } | Should -Throw '*managed lora folder cannot be removed*'
        }
        finally {
            Remove-Item -Path $tempRepo -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}
