BeforeAll {
    $modulePath = Join-Path $PSScriptRoot '../scripts/StableAmd.Generation.psm1'
    Import-Module $modulePath -Force
}

Describe 'New-StableAmdSdxlWorkflow' {
    It 'builds the v0.1 default SDXL txt2img graph' {
        $workflow = New-StableAmdSdxlWorkflow `
            -CheckpointName 'OfficialStableDiffusion\sd_xl_base_1.0.safetensors' `
            -Prompt 'a red biplane' `
            -Seed 123

        $workflow.'4'.class_type | Should -Be 'CheckpointLoaderSimple'
        $workflow.'4'.inputs.ckpt_name | Should -Be 'OfficialStableDiffusion\sd_xl_base_1.0.safetensors'
        $workflow.'6'.class_type | Should -Be 'CLIPTextEncode'
        $workflow.'6'.inputs.text | Should -Be 'a red biplane'
        $workflow.'7'.class_type | Should -Be 'CLIPTextEncode'
        $workflow.'5'.class_type | Should -Be 'EmptyLatentImage'
        $workflow.'5'.inputs.width | Should -Be 1024
        $workflow.'5'.inputs.height | Should -Be 1024
        $workflow.'5'.inputs.batch_size | Should -Be 1
        $workflow.'3'.class_type | Should -Be 'KSampler'
        $workflow.'3'.inputs.seed | Should -Be 123
        $workflow.'3'.inputs.steps | Should -Be 20
        $workflow.'3'.inputs.cfg | Should -Be 7.0
        $workflow.'3'.inputs.sampler_name | Should -Be 'euler'
        $workflow.'3'.inputs.scheduler | Should -Be 'normal'
        $workflow.'8'.class_type | Should -Be 'VAEDecode'
        $workflow.'9'.class_type | Should -Be 'SaveImage'
    }

    It 'honors custom generation settings without changing graph wiring' {
        $workflow = New-StableAmdSdxlWorkflow `
            -CheckpointName 'custom.safetensors' `
            -Prompt 'test prompt' `
            -NegativePrompt 'bad' `
            -Width 832 `
            -Height 1216 `
            -Steps 30 `
            -Cfg 5.5 `
            -Seed 987654321 `
            -SamplerName 'dpmpp_2m' `
            -Scheduler 'karras' `
            -FilenamePrefix 'StableAMD_Custom'

        $workflow.'7'.inputs.text | Should -Be 'bad'
        $workflow.'5'.inputs.width | Should -Be 832
        $workflow.'5'.inputs.height | Should -Be 1216
        $workflow.'3'.inputs.steps | Should -Be 30
        $workflow.'3'.inputs.cfg | Should -Be 5.5
        $workflow.'3'.inputs.seed | Should -Be 987654321
        $workflow.'3'.inputs.sampler_name | Should -Be 'dpmpp_2m'
        $workflow.'3'.inputs.scheduler | Should -Be 'karras'
        $workflow.'3'.inputs.model[0] | Should -Be '4'
        $workflow.'3'.inputs.positive[0] | Should -Be '6'
        $workflow.'3'.inputs.negative[0] | Should -Be '7'
        $workflow.'9'.inputs.filename_prefix | Should -Be 'StableAMD_Custom'
    }

    It 'rejects non-positive or non-Comfy-compatible dimensions' {
        { New-StableAmdSdxlWorkflow -CheckpointName 'x.safetensors' -Prompt 'x' -Width 0 -Height 1024 } | Should -Throw
        { New-StableAmdSdxlWorkflow -CheckpointName 'x.safetensors' -Prompt 'x' -Width 1025 -Height 1024 } | Should -Throw
    }
}

Describe 'Resolve-StableAmdComfyCheckpointName' {
    It 'matches an installed model to the checkpoint name exposed by ComfyUI' {
        $choice = Resolve-StableAmdComfyCheckpointName `
            -ModelPath 'C:\StableAMD\.runtime\stableamd\models\checkpoints\model.safetensors' `
            -CheckpointChoices @('other.safetensors', 'checkpoints\model.safetensors')

        $choice | Should -Be 'checkpoints\model.safetensors'
    }

    It 'returns null when ComfyUI does not expose the selected model' {
        Resolve-StableAmdComfyCheckpointName `
            -ModelPath 'C:\AI\missing.safetensors' `
            -CheckpointChoices @('known.safetensors') | Should -BeNullOrEmpty
    }
}

Describe 'StableAMD generation history' {
    It 'persists a generation record and returns its path' {
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-history-' + [guid]::NewGuid().ToString('N'))
        try {
            $record = [pscustomobject]@{
                createdAtUtc = '2026-09-11T16:00:00Z'
                promptId = 'abc-123'
                prompt = 'a red biplane'
                modelId = 'mdl_0123456789abcdef'
                width = 1024
                height = 1024
                imagePath = 'C:\StableAMD\output\image.png'
            }

            $savedPath = Save-StableAmdGenerationRecord -HistoryRoot $tempRoot -Record $record
            Test-Path $savedPath | Should -BeTrue

            $saved = Get-Content $savedPath -Raw | ConvertFrom-Json
            $saved.promptId | Should -Be 'abc-123'
            $saved.prompt | Should -Be 'a red biplane'
            $saved.width | Should -Be 1024
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'returns generation records newest first and ignores malformed sidecars' {
        $tempRoot = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-history-sort-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
        try {
            @{
                createdAtUtc = '2026-09-11T16:00:00Z'
                promptId = 'older'
                imagePath = 'older.png'
            } | ConvertTo-Json | Set-Content -Path (Join-Path $tempRoot 'older.json') -Encoding UTF8
            @{
                createdAtUtc = '2026-09-11T17:00:00Z'
                promptId = 'newer'
                imagePath = 'newer.png'
            } | ConvertTo-Json | Set-Content -Path (Join-Path $tempRoot 'newer.json') -Encoding UTF8
            Set-Content -Path (Join-Path $tempRoot 'broken.json') -Value '{not json' -Encoding UTF8

            $history = @(Get-StableAmdGenerationHistory -HistoryRoot $tempRoot)
            $history.Count | Should -Be 2
            $history[0].promptId | Should -Be 'newer'
            $history[1].promptId | Should -Be 'older'
        }
        finally {
            Remove-Item -Path $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    It 'returns an empty list when history storage does not exist' {
        $missing = Join-Path ([IO.Path]::GetTempPath()) ('stableamd-history-missing-' + [guid]::NewGuid().ToString('N'))
        @(Get-StableAmdGenerationHistory -HistoryRoot $missing).Count | Should -Be 0
    }
}

Describe 'StableAMD txt2img command' {
    It 'uses managed backend status, registered models and Comfy prompt/history endpoints' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/Invoke-Txt2Img.ps1'
        Test-Path $scriptPath | Should -BeTrue

        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'Get-StableAMDStatus\.ps1'
        $script | Should -Match 'Start-StableAMD\.ps1'
        $script | Should -Match 'Read-StableAmdModelRegistry'
        $script | Should -Match 'New-StableAmdSdxlWorkflow'
        $script | Should -Match 'CheckpointLoaderSimple'
        $script | Should -Match '/prompt'
        $script | Should -Match 'history/\$promptId'
        $script | Should -Match "status_str"
        $script | Should -Match "'error'"
        $script | Should -Match 'SaveImage'
        $script | Should -Match 'Save-StableAmdGenerationRecord'
        $script | Should -Match 'HistoryPath'
    }

    It 'does not accept arbitrary ComfyUI workflow JSON from the normal product command' {
        $script = Get-Content (Join-Path $PSScriptRoot '../scripts/Invoke-Txt2Img.ps1') -Raw
        $script | Should -Not -Match 'WorkflowJson|RawWorkflow|CustomWorkflow'
    }
}

Describe 'StableAMD generation history command' {
    It 'reads history from the canonical runtime path' {
        $scriptPath = Join-Path $PSScriptRoot '../scripts/Get-GenerationHistory.ps1'
        Test-Path $scriptPath | Should -BeTrue

        $script = Get-Content $scriptPath -Raw
        $script | Should -Match 'StableAmd\.Runtime\.psm1'
        $script | Should -Match 'StableAmd\.Generation\.psm1'
        $script | Should -Match 'HistoryRoot'
        $script | Should -Match 'Get-StableAmdGenerationHistory'
    }
}
