"""Launch an isolated ComfyUI checkout from an embedded Python runtime.

Python's Windows embeddable distribution can use a python3xx._pth file that
replaces normal sys.path discovery. In that mode, invoking an arbitrary
ComfyUI/main.py does not guarantee that the checkout directory is importable.
This bootstrap explicitly adds the selected checkout before executing main.py.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: run_comfy_isolated.py <ComfyUI-root> [ComfyUI arguments...]"
        )

    comfy_root = str(Path(sys.argv[1]).resolve())
    main_py = os.path.join(comfy_root, "main.py")
    comfy_options = os.path.join(comfy_root, "comfy", "options.py")

    if not os.path.isfile(main_py):
        raise RuntimeError(f"ComfyUI main.py not found: {main_py}")
    if not os.path.isfile(comfy_options):
        raise RuntimeError(f"ComfyUI package not found: {comfy_options}")

    # The embeddable Windows Python used by portable ComfyUI can have a ._pth
    # file that prevents the script directory from being discovered normally.
    # Inject the checkout explicitly instead of modifying that runtime file.
    if comfy_root in sys.path:
        sys.path.remove(comfy_root)
    sys.path.insert(0, comfy_root)

    forwarded_args = list(sys.argv[2:])

    # StableAMD's Windows ROCm/gfx1030 runtime deliberately uses conservative
    # host-memory behavior. The target machine has shown native 0xC0000005
    # crashes both while switching large Z-Image model graphs and inside CPU
    # VAE decode. Keep VAE on CPU, avoid mmap-backed multi-GB safetensors and
    # disable pinned/async host offload paths. The sampler still runs on Radeon.
    stableamd_windows_rocm_guards = (
        "--cpu-vae",
        "--disable-mmap",
        "--disable-pinned-memory",
        "--disable-async-offload",
    )
    for flag in stableamd_windows_rocm_guards:
        if flag not in forwarded_args:
            forwarded_args.append(flag)

    sys.argv = [main_py, *forwarded_args]
    os.chdir(comfy_root)

    # Validate the exact import that previously failed before running main.py.
    import comfy.options  # noqa: F401

    runpy.run_path(main_py, run_name="__main__")


if __name__ == "__main__":
    main()
