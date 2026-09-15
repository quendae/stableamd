from __future__ import annotations

import json
import secrets
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_lora_server as features

base = features.base

# The original Union patch is a control-only model. Although the pinned
# ZImageFunControlnet node exposes optional inpaint_image/mask inputs, that old
# model reports additional_in_dim == 0, so ComfyUI does not build an inpaint
# latent and sampling eventually dereferences a None encoded image. Target the
# official inpaint-capable 2.1 distilled Lite patch instead. The Lite build is
# the deliberate RX 6950 XT / 16 GiB choice and keeps the same 8-step cadence
# as the accepted Z-Image Turbo profile.
ZIMAGE_FUN_PATCH = "Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2602-8steps.safetensors"
ZIMAGE_FUN_LEGACY_PATCH = "Z-Image-Turbo-Fun-Controlnet-Union.safetensors"
ZIMAGE_FUN_PATCH_SHA256 = "3ea098db9bd145be525c7e2366920b6d76c5ffd46b3d7aa8169bbc943fdaee35"
ZIMAGE_FUN_PATCH_BYTES = 2016627488


class PowerShellBridge(features.PowerShellBridge):
    """v0.3 provider-native editing extensions.

    The base Z-Image txt2img/LoRA path remains in stableamd_v03_lora_server.
    Native Z-Image inpaint/outpaint is enabled only when ComfyUI actually
    exposes the official inpaint-capable Fun Control Union 2.1 model patch.
    """

    def _zimage_fun_patch_name(self, *, required: bool = False) -> str | None:
        try:
            info = self._comfy_json("object_info/ModelPatchLoader")
            choices = self._combo_choices(info, "ModelPatchLoader", "name")
        except base.StableAmdBridgeError:
            choices = []

        target = ZIMAGE_FUN_PATCH.lower()
        legacy = ZIMAGE_FUN_LEGACY_PATCH.lower()
        matches = [
            str(name)
            for name in choices
            if Path(str(name).replace("\\", "/")).name.lower() == target
        ]
        if len(matches) == 1:
            return matches[0]
        if required:
            legacy_present = any(
                Path(str(name).replace("\\", "/")).name.lower() == legacy
                for name in choices
            )
            if not matches:
                if legacy_present:
                    raise base.StableAmdBridgeError(
                        "The installed Z-Image-Turbo-Fun-Controlnet-Union.safetensors is the older control-only patch and cannot perform native inpaint. "
                        f"Install '{ZIMAGE_FUN_PATCH}' from the official Alibaba PAI Union 2.1 repository and restart StableAMD."
                    )
                raise base.StableAmdBridgeError(
                    "Z-Image native inpaint/outpaint requires "
                    f"'{ZIMAGE_FUN_PATCH}' in a ComfyUI model_patches folder. "
                    "Install the official Alibaba PAI Fun Control Union 2.1 Lite 2602 8-step patch and restart StableAMD."
                )
            raise base.StableAmdBridgeError(
                f"ComfyUI exposes more than one '{ZIMAGE_FUN_PATCH}'. Keep a single unambiguous model patch."
            )
        return None

    def model_support(self) -> dict[str, Any]:
        support = super().model_support()
        if not isinstance(support, dict):
            return support

        patch_ready = self._zimage_fun_patch_name(required=False) is not None
        if not patch_ready:
            return support

        for entry in support.get("models", []):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("family") or "").lower() != "z-image-turbo":
                continue
            capabilities = entry.get("capabilities")
            if isinstance(capabilities, dict):
                # Outpaint reuses the inpaint request contract + editContext.
                # img2img/controlnet stay gated until their dedicated product
                # workflows are implemented and target-tested.
                capabilities["inpaint"] = "supported"
        return support

    @staticmethod
    def _zimage_edit_workflow(
        *,
        diffusion_name: str,
        encoder_name: str,
        vae_name: str,
        model_patch_name: str,
        input_image_name: str,
        prompt: str,
        width: int,
        height: int,
        seed: int,
        steps: int,
        cfg: float,
        sampler: str,
        scheduler: str,
        filename_prefix: str,
        control_strength: float = 1.0,
    ) -> dict[str, Any]:
        # Pinned ComfyUI 40c4fcdf contains ModelPatchLoader +
        # ZImageFunControlnet with optional inpaint_image and mask inputs.
        # The selected Union 2.1 patch is actually inpaint-capable
        # (additional_in_dim > 0). LoadImage exposes PNG alpha as MASK
        # (transparent -> 1); ZImageFunControlnet performs the model-required
        # mask inversion internally.
        return {
            "28": {
                "class_type": "UNETLoader",
                "inputs": {"unet_name": diffusion_name, "weight_dtype": "default"},
            },
            "30": {
                "class_type": "CLIPLoader",
                "inputs": {"clip_name": encoder_name, "type": "lumina2", "device": "cpu"},
            },
            "29": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
            "27": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": prompt, "clip": ["30", 0]},
            },
            "33": {
                "class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["27", 0]},
            },
            "40": {"class_type": "LoadImage", "inputs": {"image": input_image_name}},
            "41": {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["40", 0],
                    "upscale_method": "lanczos",
                    "width": width,
                    "height": height,
                    "crop": "center",
                },
            },
            "42": {"class_type": "MaskToImage", "inputs": {"mask": ["40", 1]}},
            "43": {
                "class_type": "ImageScale",
                "inputs": {
                    "image": ["42", 0],
                    "upscale_method": "nearest-exact",
                    "width": width,
                    "height": height,
                    "crop": "center",
                },
            },
            "44": {
                "class_type": "ImageToMask",
                "inputs": {"image": ["43", 0], "channel": "red"},
            },
            "45": {
                "class_type": "ModelPatchLoader",
                "inputs": {"name": model_patch_name},
            },
            "46": {
                "class_type": "ZImageFunControlnet",
                "inputs": {
                    "model": ["28", 0],
                    "model_patch": ["45", 0],
                    "vae": ["29", 0],
                    "strength": control_strength,
                    "inpaint_image": ["41", 0],
                    "mask": ["44", 0],
                },
            },
            "11": {
                "class_type": "ModelSamplingAuraFlow",
                "inputs": {"model": ["46", 0], "shift": 3.0},
            },
            "13": {
                "class_type": "EmptySD3LatentImage",
                "inputs": {"width": width, "height": height, "batch_size": 1},
            },
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler,
                    "scheduler": scheduler,
                    "denoise": 1.0,
                    "model": ["11", 0],
                    "positive": ["27", 0],
                    "negative": ["33", 0],
                    "latent_image": ["13", 0],
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {"samples": ["3", 0], "vae": ["29", 0]},
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]},
            },
        }

    def _generate_zimage_inpaint(self, request: dict[str, Any], model: dict[str, Any]) -> Any:
        if request.get("loraStack") or str(request.get("loraName") or "").strip():
            raise base.StableAmdBridgeError(
                "Z-Image native inpaint/outpaint is being target-tested without LoRA first. Disable the LoRA stack for this edit."
            )
        if str(request.get("mode") or "").lower() != "inpaint":
            raise base.StableAmdBridgeError("Z-Image Fun Control editing currently accepts the inpaint/outpaint request contract only.")

        if request.get("startBackendIfNeeded"):
            try:
                backend_url = self._backend_base_url()
            except base.StableAmdBridgeError:
                self.start_backend()
                backend_url = self._backend_base_url()
        else:
            backend_url = self._backend_base_url()

        patch_name = self._zimage_fun_patch_name(required=True)
        staged_input = base.stage_input_image(self.repo_root, request["inputImage"])
        started = time.monotonic()
        try:
            label = "Z-Image Turbo"
            diffusion_path = self._bundle_asset_path_for(model, "diffusion_model", label)
            encoder_path = self._bundle_asset_path_for(model, "text_encoder", label)
            vae_path = self._bundle_asset_path_for(model, "vae", label)
            diffusion_name = self._resolve_comfy_bundle_asset_for("UNETLoader", "unet_name", diffusion_path, label)
            encoder_name = self._resolve_comfy_bundle_asset_for("CLIPLoader", "clip_name", encoder_path, label)
            vae_name = self._resolve_comfy_bundle_asset_for("VAELoader", "vae_name", vae_path, label)

            seed = int(request["seed"]) if "seed" in request else secrets.randbits(63)
            width = int(request.get("width", 1024))
            height = int(request.get("height", 1024))
            steps = int(request.get("steps", 8))
            cfg = float(request.get("cfg", 1.0))
            sampler = str(request.get("samplerName") or "res_multistep")
            scheduler = str(request.get("scheduler") or "simple")
            filename_prefix = f"StableAMD_ZIMAGE_INPAINT_{uuid.uuid4().hex}"

            workflow = self._zimage_edit_workflow(
                diffusion_name=diffusion_name,
                encoder_name=encoder_name,
                vae_name=vae_name,
                model_patch_name=str(patch_name),
                input_image_name=staged_input.name,
                prompt=str(request["prompt"]),
                width=width,
                height=height,
                seed=seed,
                steps=steps,
                cfg=cfg,
                sampler=sampler,
                scheduler=scheduler,
                filename_prefix=filename_prefix,
                control_strength=1.0,
            )

            client_id = uuid.uuid4().hex
            queued = self._post_comfy_json("prompt", {"prompt": workflow, "client_id": client_id})
            prompt_id = str(queued.get("prompt_id") or "") if isinstance(queued, dict) else ""
            if not prompt_id:
                raise base.StableAmdBridgeError("ComfyUI /prompt did not return a prompt_id for Z-Image inpainting.")
            node_errors = queued.get("node_errors") if isinstance(queued, dict) else None
            if isinstance(node_errors, dict) and node_errors:
                raise base.StableAmdBridgeError(
                    "ComfyUI rejected the StableAMD Z-Image inpaint workflow: "
                    + json.dumps(node_errors, ensure_ascii=False)
                )

            deadline = time.monotonic() + 900
            history_entry: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                history = self._comfy_json(f"history/{prompt_id}")
                candidate = history.get(prompt_id) if isinstance(history, dict) else None
                if isinstance(candidate, dict):
                    status = candidate.get("status") or {}
                    status_str = str(status.get("status_str") or "") if isinstance(status, dict) else ""
                    if status_str == "error":
                        raise base.StableAmdBridgeError(
                            "ComfyUI reported a Z-Image inpaint execution error: "
                            + json.dumps(status, ensure_ascii=False)
                        )
                    if status_str == "success" or bool(status.get("completed")):
                        history_entry = candidate
                        break
                time.sleep(0.25)
            if history_entry is None:
                raise base.StableAmdBridgeError(
                    f"Z-Image inpainting did not complete within 900 seconds. Prompt ID: {prompt_id}"
                )

            image_path = self._resolve_bundle_output(label, prompt_id, history_entry)
            generation_seconds = round(time.monotonic() - started, 3)
            edit_context = request.get("editContext") if isinstance(request.get("editContext"), dict) else None
            is_outpaint = bool(edit_context and edit_context.get("kind") == "outpaint")
            operation = "outpaint" if is_outpaint else "inpaint"
            model_id = str(model.get("id") or model.get("Id") or "")
            model_name = str(model.get("name") or model.get("Name") or "Z-Image Turbo")
            assets = {
                "diffusion_model": [str(diffusion_path)],
                "text_encoder": [str(encoder_path)],
                "vae": [str(vae_path)],
                "model_patch": [str(patch_name)],
            }
            record: dict[str, Any] = {
                "schemaVersion": 3,
                "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                "promptId": prompt_id,
                "mode": operation,
                "editOperation": operation,
                "prompt": request["prompt"],
                "negativePrompt": "",
                "negativeConditioning": "zeroed-positive",
                "modelId": model_id,
                "modelName": model_name,
                "modelPath": str(diffusion_path),
                "family": "z-image-turbo",
                "provider": "z-image-fun-control-inpaint",
                "assetMode": "bundle",
                "bundleAssets": assets,
                "inputImagePath": str(staged_input),
                "maskMode": "embedded-alpha",
                "controlStrength": 1.0,
                "denoise": 1.0,
                "width": width,
                "height": height,
                "steps": steps,
                "cfg": cfg,
                "seed": seed,
                "sampler": sampler,
                "scheduler": scheduler,
                "loraStack": [],
                "generationSeconds": generation_seconds,
                "imagePath": str(image_path),
                "backendUrl": backend_url,
            }
            if is_outpaint and edit_context is not None:
                record["sourcePromptId"] = str(edit_context.get("sourcePromptId") or "")
                record["sourceImagePath"] = str(edit_context.get("sourceImagePath") or "")
                record["outpaintMargins"] = dict(edit_context.get("margins") or {})
                record["outpaintBlendOverlap"] = int(edit_context.get("blendOverlap") or 0)

            history_path = self._save_bundle_history(record)
            result: dict[str, Any] = {
                "PromptId": prompt_id,
                "Mode": operation,
                "EditOperation": operation,
                "Prompt": record["prompt"],
                "NegativePrompt": "",
                "ModelId": model_id,
                "ModelName": model_name,
                "ModelPath": str(diffusion_path),
                "Family": "z-image-turbo",
                "Provider": "z-image-fun-control-inpaint",
                "AssetMode": "bundle",
                "BundleAssets": assets,
                "InputImagePath": str(staged_input),
                "MaskMode": "embedded-alpha",
                "ControlStrength": 1.0,
                "Denoise": 1.0,
                "Width": width,
                "Height": height,
                "Steps": steps,
                "Cfg": cfg,
                "Seed": seed,
                "Sampler": sampler,
                "Scheduler": scheduler,
                "LoraStack": [],
                "GenerationSeconds": generation_seconds,
                "ImagePath": str(image_path),
                "HistoryPath": str(history_path),
                "BackendUrl": backend_url,
            }
            if is_outpaint and edit_context is not None:
                result["SourcePromptId"] = record["sourcePromptId"]
                result["SourceImagePath"] = record["sourceImagePath"]
                result["OutpaintMargins"] = record["outpaintMargins"]
                result["OutpaintBlendOverlap"] = record["outpaintBlendOverlap"]
            return result
        except Exception:
            try:
                staged_input.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def generate(self, request: dict[str, Any]) -> Any:
        selected = self._selected_product_model(request)
        if selected is not None:
            family = str(selected.get("family") or selected.get("Family") or "").lower()
            asset_mode = str(selected.get("assetMode") or selected.get("AssetMode") or "checkpoint").lower()
            mode = str(request.get("mode") or "txt2img").lower()
            if family == "z-image-turbo" and asset_mode == "bundle" and mode == "inpaint":
                return self._generate_zimage_inpaint(request, selected)
        return super().generate(request)


class StableAmdApi(features.StableAmdApi):
    pass


# Importing stableamd_v03_lora_server installs its extension points into the
# proven base server. Replace them once more with the edit-aware layer.
base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
