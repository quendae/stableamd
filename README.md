# StableAMD

StableAMD is a planned simple local AI image-generation application focused first on AMD Radeon GPUs on Windows.

The initial hardware target is **Radeon RX 6950 XT 16 GB (`gfx1030`)**. Windows ROCm support for this card is treated as **experimental**: AMD's current Windows HIP SDK compatibility table does not mark RX 6950 XT as supported, although TheRock now builds and sanity-tests `gfx1030` on Windows.

The current product direction is:

- use **SwarmUI** as the practical open-source base after hardware validation;
- keep **ComfyUI** as the managed inference backend under SwarmUI;
- simplify the normal experience toward Generate / Models / Gallery / Settings;
- keep raw Comfy workflows as an advanced mode rather than the default UI;
- add StableAMD-owned AMD detection, diagnostics and compatibility handling;
- add built-in model discovery/downloads, starting with Hugging Face;
- keep WSL2/Linux, ZLUDA and DirectML as deliberate fallback investigations rather than silent automatic fallbacks.

For the original comparison of ComfyUI, SwarmUI, SD.Next, Stability Matrix, Fooocus, AUTOMATIC1111 and InvokeAI, see:

**[AMD RX 6950 XT image-generation stack research](docs/amd-rx6950xt-image-generation-research.md)**

## Current milestone: SwarmUI + RX 6950 XT validation

Before modifying SwarmUI's UI, StableAMD must prove that the current Windows AMD backend can actually execute GPU workloads on the RX 6950 XT.

The spike branch contains:

- Windows/GPU preflight and diagnostic report;
- RX 6950 XT -> `gfx1030` classification;
- pinned SwarmUI bootstrap;
- clean baseline mode with no HSA override;
- optional `HSA_OVERRIDE_GFX_VERSION=10.3.0` comparison mode;
- embedded ComfyUI PyTorch/HIP probe;
- real FP16 GPU matrix-multiplication smoke test;
- a manual SDXL 1024x1024 end-to-end gate.

See **[RX 6950 XT + SwarmUI Windows spike](docs/RX6950XT-SWARMUI-SPIKE.md)** for the exact test procedure.

## Decision gate

If the baseline or documented gfx1030 compatibility mode is stable enough to run SDXL on the 6950 XT, the next phase is to use SwarmUI as the StableAMD base and start simplifying its UI and model-management experience.

If the Windows backend remains unstable, the diagnostics from this spike will determine whether to fix the gfx1030 packaging path or move the backend to Linux/WSL2. The frontend direction does not need to be discarded.
