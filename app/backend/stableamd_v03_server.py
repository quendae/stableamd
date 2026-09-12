from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import stableamd_server as base


class PowerShellBridge(base.PowerShellBridge):
    def generate(self, request: dict[str, Any]) -> Any:
        mode = str(request.get("mode", "txt2img")).lower()
        if mode != "inpaint":
            return super().generate(request)

        staged_input: Path | None = None
        parameters: list[tuple[str, Any]] = [("Prompt", request["prompt"])]
        mapping = {
            "negativePrompt": "NegativePrompt",
            "modelId": "ModelId",
            "width": "Width",
            "height": "Height",
            "steps": "Steps",
            "cfg": "Cfg",
            "seed": "Seed",
            "samplerName": "SamplerName",
            "scheduler": "Scheduler",
            "loraName": "LoraName",
            "loraModelStrength": "LoraModelStrength",
            "loraClipStrength": "LoraClipStrength",
            "startBackendIfNeeded": "StartBackendIfNeeded",
        }
        for source, target in mapping.items():
            if source in request:
                parameters.append((target, request[source]))
        if "loraStack" in request:
            parameters.append(("LoraStackJson", json.dumps(request["loraStack"], ensure_ascii=False, separators=(",", ":"))))

        staged_input = base.stage_input_image(self.repo_root, request["inputImage"])
        parameters.extend(
            [
                ("Mode", "inpaint"),
                ("InputImagePath", str(staged_input)),
                ("Denoise", request.get("denoise", 0.8)),
            ]
        )
        try:
            return self._run_script("Invoke-Txt2Img.ps1", parameters)
        except Exception:
            try:
                staged_input.unlink(missing_ok=True)
            except OSError:
                pass
            raise


class StableAmdApi(base.StableAmdApi):
    def _validate_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        mode = request.get("mode", "txt2img")
        if mode != "inpaint":
            return super()._validate_generation(request)

        unsupported = sorted(set(request) - self._generation_fields)
        if unsupported:
            raise ValueError("Unsupported generation field(s): " + ", ".join(unsupported))

        # Reuse the proven img2img validation for prompt, image payload,
        # denoise, LoRA and numeric generation fields, then enforce the
        # inpaint-specific PNG contract used to carry the painted mask in alpha.
        proxy = dict(request)
        proxy["mode"] = "img2img"
        super()._validate_generation(proxy)

        image = request.get("inputImage")
        if not isinstance(image, dict):
            raise ValueError("inpaint requires inputImage.")
        if image.get("mimeType") != "image/png" or Path(str(image.get("name", ""))).suffix.lower() != ".png":
            raise ValueError("inpaint requires a PNG input with the mask embedded in its alpha channel.")
        return request


# The shared server creates these classes through module globals at runtime.
# Patch only the v0.3 extension points and keep the proven loopback server,
# static-file handling and lifecycle implementation untouched.
base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
