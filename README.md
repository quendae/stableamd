# StableAMD

StableAMD is a planned simple local AI image-generation application focused first on AMD Radeon GPUs on Windows.

The initial target is **Radeon RX 6950 XT 16 GB (`gfx1030`)**. The current architecture direction is:

- native Windows **ROCm + PyTorch** as the default compute backend;
- **ComfyUI** as a managed local inference engine/API;
- a much simpler Fooocus-style StableAMD interface instead of exposing the ComfyUI node graph;
- built-in model discovery/downloads, starting with **Hugging Face**;
- curated/versioned workflow recipes for supported model families;
- WSL2/ROCDXG, ZLUDA and DirectML only as optional fallback paths.

For the full comparison of ComfyUI, SwarmUI, SD.Next, Stability Matrix, Fooocus, AUTOMATIC1111 and InvokeAI, plus the proposed installer/model-manager architecture, see:

**[AMD RX 6950 XT image-generation stack research](docs/amd-rx6950xt-image-generation-research.md)**

## Current recommendation

For the cleanest long-term product, build a small StableAMD frontend/orchestrator around a separately managed ComfyUI backend. If development speed is more important, **SwarmUI** is the strongest existing open-source project to fork and simplify: it is MIT-licensed, already uses ComfyUI as its main backend, and current releases support native ROCm-PyTorch on Windows.

## Proposed first milestone

Before building the full UI, prove the critical hardware path:

1. Detect RX 6950 XT and resolve it to `gfx1030`.
2. Create an isolated Python environment.
3. Install the current AMD multi-architecture ROCm/PyTorch wheels for `gfx1030`.
4. Install and launch ComfyUI.
5. Run an automated GPU self-test.
6. Generate a known SDXL 1024×1024 image entirely on the GPU.
7. Save a diagnostic report containing runtime, GPU, VRAM and package information.

Once this is repeatable, build the Generate / Models / Gallery / Settings UI on top.