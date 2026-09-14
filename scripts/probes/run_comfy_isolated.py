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

    # Keep the guard that was already proven useful on the target gfx1030
    # machine. The additional host-memory flags introduced in 6a15f6b,
    # especially --disable-mmap, regressed Z-Image before sampling by moving
    # the multi-GB diffusion model load through CPU allocation/copy paths. The
    # attached target log then crashed natively in load_torch_file / UNETLoader.
    # CPU VAE stays enabled; StableAMD's Z-Image workflow separately uses tiled
    # VAE decode to reduce decode-time peak pressure.
    if "--cpu-vae" not in forwarded_args:
        forwarded_args.append("--cpu-vae")

    # Make the effective runtime arguments visible in the normal backend log so
    # a native crash can be correlated with the exact launch profile next time.
    print(
        "[StableAMD bootstrap] ComfyUI args: " + " ".join(forwarded_args),
        file=sys.stderr,
        flush=True,
    )

    sys.argv = [main_py, *forwarded_args]
    os.chdir(comfy_root)

    # Validate the exact import that previously failed before running main.py.
    import comfy.options  # noqa: F401

    runpy.run_path(main_py, run_name="__main__")


if __name__ == "__main__":
    main()
