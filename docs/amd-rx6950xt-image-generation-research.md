# StableAMD — AMD RX 6950 XT image-generation stack research

## Executive summary

For a new Windows-first image-generation application targeting the Radeon RX 6950 XT (16 GB), the strongest foundation in September 2026 is **native Windows ROCm + PyTorch + ComfyUI as the inference engine**, with a much simpler application UI in front of it.

The RX 6950 XT is an RDNA2 `gfx1030` GPU. AMD's current TheRock support tracker marks `gfx1030` on Windows as build-passing, sanity-tested and release-ready, and current multi-architecture releases provide a `device-gfx1030` package target. ComfyUI now documents native Windows ROCm 10 installation and ships an official AMD Windows portable build. This makes DirectML and ZLUDA fallback paths rather than the primary architecture.

If the goal is the **fastest route to a usable product**, the best existing project to adapt is **SwarmUI**. It is MIT-licensed, already uses ComfyUI as its primary backend, deliberately separates backend / middle layer / frontend, exposes a normal form-style Generate interface, can download models through its API, and its current releases use native ROCm-PyTorch-Windows for AMD.

If the goal is the **cleanest long-term product**, build a new compact frontend and orchestration service around ComfyUI's API rather than forking the full ComfyUI frontend. StableAMD can then provide a Fooocus-like UX while retaining ComfyUI's broad support for modern image/video architectures.

**Recommended direction:**

1. Native Windows ROCm is the default compute path for RX 6950 XT.
2. ComfyUI runs as a managed local backend process.
3. StableAMD owns a simple Generate / Models / Gallery / Settings interface.
4. Use curated workflow templates to hide ComfyUI nodes from ordinary users.
5. Integrate Hugging Face directly for discovery and downloads; optionally support URL imports from CivitAI later.
6. Keep WSL2, ZLUDA and DirectML as advanced fallback backends, not the default.

## RX 6950 XT status in 2026

AMD identifies the Radeon RX 6950 XT as **RDNA2, `gfx1030`, 16 GB VRAM, 80 compute units**.[1] The current TheRock GPU roadmap marks Radeon `gfx1030` on **Windows** as build-passing, sanity-tested and release-ready.[2] Its release documentation exposes `device-gfx1030` as a downloadable target and maps that target to the RX 6900 XT / RX 6800 XT family; the 6950 XT shares that same LLVM target.[3]

ComfyUI's current documentation includes a native **AMD GPUs (Windows, ROCm 10.0)** path using AMD's multi-architecture PyTorch wheels. It recommends Windows 11, a current AMD driver and 64-bit Python 3.13. A separate HIP SDK installation is not needed because the `device-*` PyTorch extras pull the matching ROCm runtime and kernels.[4]

There is an important documentation wrinkle: AMD's older / legacy HIP SDK 7.2 Windows compatibility page still lists RX 6000 RDNA2 as unsupported, while the newer TheRock multi-architecture release track marks `gfx1030` ready. StableAMD should therefore not infer support solely from the old HIP SDK matrix. It should install the modern ROCm/PyTorch packages and perform an actual GPU self-test during first run.[2][3][5]

### Native Windows vs WSL2

For this particular card, native Windows should be the primary route. AMD's current ROCDXG WSL layer has production support, but its published compatibility list focuses on RX 9000 / RX 7900 / RX 7800 / RX 7700-class hardware and does not list RX 6950 XT / `gfx1030`.[6] In contrast, TheRock's Windows architecture tracker does list `gfx1030` as release-ready.[2]

WSL2 remains useful as an optional advanced backend if support broadens or if a Linux-only dependency becomes necessary. It should not be required for StableAMD's normal installation.

## Comparison of candidate applications

| Candidate | AMD Windows path | Modern model breadth | Simplicity | Suitability as StableAMD base | Verdict |
|---|---|---:|---:|---:|---|
| **ComfyUI** | Native ROCm 10 documented; AMD portable available | Excellent | Low in node UI, high as backend | **Excellent backend** | Use as engine/API, hide graph by default |
| **SwarmUI** | Current releases use native ROCm-PyTorch-Windows | Excellent via ComfyUI | Medium-high | **Best existing fork/base** | Strongest shortcut to product |
| **SD.Next** | ROCm Windows + ZLUDA/DirectML fallbacks | Very good | Medium | Good alternative | Useful reference / fallback, but broader UI than desired |
| **Stability Matrix** | Can manage ROCm-capable packages | Depends on managed backend | High as launcher | Good inspiration, heavier base | Borrow installer/model-manager ideas; AGPL source |
| **Fooocus** | Historically DirectML on Windows | SDXL-centric | **Excellent** | Poor in 2026 | Use as UX inspiration only |
| **AUTOMATIC1111** | Official wiki still points Windows AMD to DirectML fork | Legacy ecosystem is large | Medium | Poor | Do not use as new foundation |
| **InvokeAI** | Official docs still say AMD is Linux-only | Good | High | Poor for Windows RX 6950 XT | Not suitable for this target today |

### ComfyUI

ComfyUI is the best inference engine because it has the broadest current architecture support, a stable queue/workflow model and a documented API. The server exposes `/prompt` to submit workflows and `/ws` for real-time execution events.[7] Comfy Org also now publishes an MIT-licensed Python SDK for Comfy API v2, including self-hosted instances.[8]

The node editor is not a reason to reject ComfyUI. StableAMD can ship known-good API-format workflow templates and only expose the parameters users actually understand. An optional **Open in ComfyUI / Advanced workflow** action can remain for expert users.

ComfyUI itself is GPL-3.0, so if StableAMD is intended to use a more permissive license, the cleanest architectural boundary is to keep ComfyUI as a separately managed process and communicate through its API rather than copying/modifying ComfyUI core code inside StableAMD.[9] This is an engineering/licensing design recommendation, not legal advice.

### SwarmUI

SwarmUI is the closest existing open-source application to the requested product. Its current README describes a beginner-friendly Generate tab while retaining advanced features and modern model support. Current releases explicitly state that **AMD on Windows now uses native ROCm-PyTorch-Windows**.[10][11]

Its architecture is especially relevant: SwarmUI uses a C# server and deliberately separates backends, middle layer and web frontend. ComfyUI is its primary backend.[12] The project itself is MIT-licensed.[13]

It already has a model download WebSocket API with progress reporting (`/API/DoModelDownloadWS`).[14] Therefore a StableAMD fork could focus on removing power-user complexity, building a better curated Models screen and adding a first-run RX 6950 XT ROCm installer instead of rebuilding generation plumbing.

The disadvantage is that SwarmUI remains a fairly large application. If StableAMD aims for an intentionally small Fooocus-like product, a fresh frontend over ComfyUI may ultimately be easier to keep coherent than continuously deleting features from SwarmUI.

### Fooocus

Fooocus remains the best reference for **interaction design**: prompt first, sensible defaults, advanced controls hidden until needed. It is not a good technical base now. The project is in **Limited Long-Term Support** with bug fixes only, is built entirely around SDXL and explicitly says there are no current plans to migrate to newer architectures. Its own README points users wanting newer models toward Forge or ComfyUI/SwarmUI.[15]

StableAMD should imitate Fooocus's simplicity, not inherit its model architecture.

### AUTOMATIC1111

AUTOMATIC1111 is a weak foundation for a new AMD-first Windows product. Its official AMD wiki still states that Windows+AMD support is not officially provided and points users to the DirectML fork.[16] DirectML was an important compatibility bridge, but native ROCm is now the more promising path for this hardware.

A1111's extension ecosystem is large, but adapting its old assumptions and UI structure would create more work than using ComfyUI as a modular engine.

### SD.Next

SD.Next is the strongest alternative if StableAMD should be based on a traditional all-in-one WebUI rather than ComfyUI. It supports AMD ROCm on Windows and Linux and also retains ZLUDA, DirectML, OpenVINO and other backends. Its current platform documentation now describes ZLUDA and DirectML as secondary stop-gap solutions after native ROCm became available.[17][18]

SD.Next switched to Apache-2.0 and has removed a large amount of legacy A1111 code.[19] It is therefore a much better candidate than A1111 itself. The tradeoff is product scope: SD.Next is an all-in-one image/video application with many controls, so reducing it to a deliberately simple product still requires significant UI pruning.

### Stability Matrix

Stability Matrix is the best reference for the **installation and model-management experience**. It manages multiple image-generation packages and their dependencies, including ComfyUI, SwarmUI, SD.Next, Fooocus variants, InvokeAI and AMD-oriented A1111/Forge variants.[20]

Its source is AGPL-3.0 and released binaries have a separate EULA, so it is less attractive as a base if StableAMD should have a permissive codebase.[20] Functionally, however, it demonstrates the right product ideas: package isolation, shared models, one-click installation, backend selection and model discovery.

### InvokeAI

InvokeAI is polished and has a strong creator-oriented UI, but its current system requirements still describe AMD GPU support as **Linux only**.[21] It is therefore not the right base for a Windows-first RX 6950 XT application unless its Windows AMD support changes later.

## Recommended StableAMD architecture

### Product surface

Keep the primary UI deliberately small:

- **Generate** — prompt, negative prompt, model, image size/aspect ratio, count, seed; one Advanced drawer for sampler/steps/CFG/LoRA/ControlNet-style features.
- **Models** — Installed / Discover / Downloads; search Hugging Face; show architecture, size, precision, license and estimated VRAM; one-click install.
- **Gallery** — generated images, metadata, reuse settings, reveal/open folder.
- **Settings** — GPU/backend status, storage paths, HF token, update channel, advanced backend controls.

Do not expose a node graph as the default UX. Each supported model family should map to a maintained StableAMD workflow recipe.

### Process layout

```text
StableAMD UI
    |
    v
StableAMD local service / orchestrator
    |-- hardware + backend detector
    |-- model registry/download manager
    |-- workflow-template renderer
    |-- generation queue/history
    |
    v
Managed ComfyUI process
    |
    v
PyTorch + ROCm 10 / gfx1030
    |
    v
Radeon RX 6950 XT 16 GB
```

A practical first implementation is **React + Vite** for the UI and a small **Python service** for hardware detection, Hugging Face integration and ComfyUI process/API orchestration. This minimizes friction with the Python AI ecosystem. A desktop wrapper can be added later if required; the first release can simply launch the local service and open the UI in the default browser.

If development speed matters more than owning the architecture, fork SwarmUI instead and simplify its Generate surface.

## ROCm installation strategy

StableAMD should treat the GPU runtime as a managed component, not expect the user to configure Python manually.

For the RX 6950 XT:

- Detect Windows 11 and the GPU via PowerShell/WMI and/or the AMD runtime.
- Resolve RX 6950 XT -> RDNA2 -> `gfx1030`.
- Create an isolated Python environment.
- Install the current AMD ROCm/PyTorch multi-architecture wheels with the `device-gfx1030` target where available, rather than `device-all`, to reduce download and disk size.[3][4]
- Install ComfyUI and pinned StableAMD-compatible dependencies.
- Run a startup probe: import torch, confirm the AMD GPU is visible, report VRAM/device name, allocate a tensor, run a small matrix operation and then run a tiny known ComfyUI workflow.
- Save a machine-readable diagnostics report for support.

Backend priority should be:

1. **Native Windows ROCm** — default.
2. **WSL2/ROCDXG** — advanced/experimental for RX 6950 XT until its compatibility matrix includes the card.
3. **ZLUDA** — legacy compatibility fallback only. SD.Next currently calls it unofficial/limited.[22]
4. **DirectML** — final compatibility fallback; not the performance target.

## Model discovery and Hugging Face

Hugging Face can be integrated directly through `huggingface_hub`. `hf_hub_download()` downloads individual files with revision-aware caching, while `snapshot_download()` downloads repositories concurrently and can target a local directory.[23]

StableAMD should not blindly download every file in a repository. Create a **model recipe/manifest layer** that knows how model families are assembled:

```text
model recipe
  id
  family: sdxl | sd35 | flux | qwen-image | z-image | ...
  source: huggingface
  repo_id
  revision
  required_files[]
  optional_files[]
  destination mapping
  workflow template
  default settings
  minimum/recommended VRAM
  license metadata
```

This is particularly important for modern models that use separate transformer/UNet, VAE and text-encoder files. A recipe can download the correct dependencies and place them in the correct ComfyUI folders automatically.

For gated/private Hugging Face models, store the user's token using the Windows credential store rather than plaintext configuration. The UI should clearly present a model's upstream license before download when the metadata provides it.

## Suggested implementation phases

### Phase 0 — hardware proof

Build a minimal command-line proof that creates the ROCm environment for `gfx1030`, launches ComfyUI and runs one SDXL generation. This is the critical technical risk and should be solved before UI work.

Success criteria:

- RX 6950 XT detected correctly.
- Native ROCm PyTorch initializes repeatedly after reboot.
- SDXL 1024x1024 generation completes without fallback to CPU.
- VRAM is released sufficiently between jobs.
- Diagnostics clearly identify runtime failures.

### Phase 1 — StableAMD MVP

Build the simple Generate interface with one maintained SDXL workflow, gallery/history and local model selection. No custom nodes are required in the first milestone.

### Phase 2 — model manager

Add Hugging Face search/import, resumable downloads, checksum/revision tracking, model recipes and storage management.

### Phase 3 — modern architectures

Add curated workflows for selected current architectures one at a time. Treat every model family as a tested capability rather than exposing arbitrary ComfyUI graphs and hoping they work on RDNA2.

### Phase 4 — advanced escape hatch

Add LoRA, image-to-image, ControlNet-like conditioning and an **Open workflow in ComfyUI** option for experts. Keep these out of the first-run experience.

### Phase 5 — alternate compute backends

Only after native Windows ROCm is solid, consider WSL2/ROCDXG and fallback engines. Keeping the backend boundary explicit from day one makes this possible without rewriting the UI.

## Main risks

**RDNA2 kernel/performance differences.** `gfx1030` is now on the modern Windows ROCm path, but newer GPU architectures can have faster or broader optimized attention kernels. StableAMD should benchmark the actual RX 6950 XT and choose conservative default attention/precision settings rather than copying RDNA3/RDNA4 defaults.

**ROCm documentation transition.** AMD currently has overlapping legacy HIP SDK documentation and the newer TheRock multi-architecture distribution. The installer should pin known-good versions and self-test instead of making support decisions from one static compatibility page.

**Rapid model churn.** Avoid hardcoding UI logic to a single model generation. Workflow recipes should be data-driven and versioned.

**Dependency churn in custom nodes.** Do not make third-party ComfyUI nodes a core MVP dependency. Every mandatory node increases the chance that an upstream Python package breaks the application.

**Licenses.** Application code, ComfyUI, custom nodes and model weights can all have different licenses. Surface upstream model licenses and keep third-party components clearly separated.

## Final decision

For `quendae/stableamd`, I would choose this order:

**Best product architecture:** custom simple StableAMD UI + managed ComfyUI backend + native Windows ROCm `gfx1030`.

**Best existing project to fork when speed matters:** SwarmUI, then aggressively simplify the UI and add a first-class Hugging Face model browser / RX 6950 XT setup path.

**Useful projects to study:** Stability Matrix for installation/model management; Fooocus for UX simplicity; SD.Next for multi-backend AMD handling.

**Do not use as the main foundation:** Fooocus (SDXL LTS only), AUTOMATIC1111 (Windows AMD path remains tied to DirectML forks), InvokeAI (current docs still make AMD Linux-only).

## Sources

1. AMD ROCm, “Accelerator and GPU hardware specifications” — RX 6950 XT = RDNA2 / gfx1030 / 16 GB: https://rocm.docs.amd.com/en/docs-7.0.0/reference/gpu-arch-specs.html
2. ROCm/TheRock, `SUPPORTED_GPUS.md`: https://github.com/ROCm/TheRock/blob/main/SUPPORTED_GPUS.md
3. ROCm/TheRock, `RELEASES.md`: https://github.com/ROCm/TheRock/blob/main/RELEASES.md
4. ComfyUI README, AMD GPUs (Windows, ROCm 10.0): https://github.com/Comfy-Org/ComfyUI
5. AMD HIP SDK Windows system requirements (legacy/current 7.2 documentation stream): https://rocm.docs.amd.com/projects/install-on-windows/en/latest/reference/system-requirements.html
6. ROCm/librocdxg WSL compatibility matrix: https://github.com/ROCm/librocdxg
7. ComfyUI server routes: https://docs.comfy.org/development/comfyui-server/comms_routes
8. Comfy Org, `comfy-python-sdk`: https://github.com/Comfy-Org/comfy-python-sdk
9. ComfyUI GPL-3.0 repository license: https://github.com/Comfy-Org/ComfyUI
10. SwarmUI releases: https://github.com/mcmonkeyprojects/SwarmUI/releases
11. SwarmUI README: https://github.com/mcmonkeyprojects/SwarmUI
12. SwarmUI architecture motivations: https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/Motivations.md
13. SwarmUI MIT license: https://github.com/mcmonkeyprojects/SwarmUI/blob/master/LICENSE.txt
14. SwarmUI Models API: https://github.com/mcmonkeyprojects/SwarmUI/blob/master/docs/APIRoutes/ModelsAPI.md
15. Fooocus project status: https://github.com/lllyasviel/Fooocus/blob/main/readme.md
16. AUTOMATIC1111 AMD installation wiki: https://github.com/AUTOMATIC1111/stable-diffusion-webui/wiki/Install-and-Run-on-AMD-GPUs
17. SD.Next repository/platform support: https://github.com/vladmandic/sdnext
18. SD.Next platform documentation: https://github.com/vladmandic/sdnext/wiki/Platforms
19. SD.Next changelog/license transition: https://github.com/vladmandic/sdnext/wiki/CHANGELOG
20. Stability Matrix: https://github.com/LykosAI/StabilityMatrix
21. InvokeAI system requirements: https://github.com/invoke-ai/InvokeAI/blob/main/docs/src/content/docs/start-here/system-requirements.mdx
22. SD.Next ZLUDA documentation: https://github.com/vladmandic/sdnext/wiki/ZLUDA
23. Hugging Face Hub download documentation: https://huggingface.co/docs/huggingface_hub/main/guides/download
