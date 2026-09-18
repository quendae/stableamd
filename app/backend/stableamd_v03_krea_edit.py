from __future__ import annotations

import json
import math
from pathlib import Path
from threading import local
from typing import Any

import stableamd_v03_pose_control as posecontrol

base = posecontrol.base


class KreaImageEditBridgeMixin:
    """Whole-image instruction editing for Krea 2 Turbo.

    The transport deliberately reuses StableAMD's existing img2img request
    contract, but Krea does not perform classic latent denoise img2img. The
    source image is reference-conditioned through the pinned Ostris Krea edit
    nodes, matching the published workflow: FluxKontextImageScale ->
    TextEncodeKrea2OstrisEdit -> index_timestep_zero reference conditioning.

    The accepted Krea provider remains responsible for model loading, LoRA,
    async timeout handling and history creation. This mixin only stages the
    source image, composes the edit graph, and rewrites result/history metadata
    from the internal txt2img transport to the public Image Edit operation.
    """

    _KREA_EDIT_NODES = (
        "TextEncodeKrea2OstrisEdit",
        "Krea2OstrisEditModelPatch",
        "FluxKontextImageScale",
        "FluxKontextMultiReferenceLatentMethod",
        "GetImageSize",
        "SelectVAEDevice",
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        self._stableamd_krea_edit_context = local()

    def _active_krea_edit_context(self) -> dict[str, Any] | None:
        context = getattr(self._stableamd_krea_edit_context, "value", None)
        return context if isinstance(context, dict) else None

    def _krea_image_edit_ready(self) -> bool:
        return all(self._node_available(node_name) for node_name in self._KREA_EDIT_NODES)

    def model_support(self) -> dict[str, Any]:
        support = super().model_support()
        if not isinstance(support, dict):
            return support

        ready = self._krea_image_edit_ready()
        for entry in support.get("models", []):
            if not isinstance(entry, dict) or str(entry.get("family") or "").lower() != "krea2":
                continue
            entry["editPolicy"] = {
                "mode": "img2img",
                "label": "Image Edit",
                "status": "supported" if ready else "planned",
                "inputKind": "source-image",
                "wholeImage": True,
                "masked": False,
                "provider": "krea2-ostris-edit",
                "referenceScaler": "FluxKontextImageScale",
                "sourceSizeOutput": True,
                "tasks": [
                    {
                        "id": "general",
                        "label": "General edit",
                        "referenceImages": 0,
                        "masked": False,
                    },
                    {
                        "id": "material-replace",
                        "label": "Material / texture",
                        "referenceImages": 0,
                        "masked": False,
                    },
                ],
            }
            capabilities = entry.get("capabilities")
            if isinstance(capabilities, dict) and ready:
                capabilities["img2img"] = "supported"
        return support

    def _inject_krea_image_edit(
        self,
        workflow: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        for node_id in ("10", "11", "12", "5", "3", "6", "8"):
            if not isinstance(workflow.get(node_id), dict):
                raise base.StableAmdBridgeError(
                    "Krea 2 workflow anchors are missing for Image Edit."
                )
        for node_name in self._KREA_EDIT_NODES:
            if not self._node_available(node_name):
                raise base.StableAmdBridgeError(
                    f"Krea 2 Image Edit requires ComfyUI node '{node_name}'. "
                    "Install/restart the pinned Krea edit integration first."
                )

        sampler = workflow["3"]
        sampler_inputs = sampler.get("inputs")
        clip_loader = workflow["11"]
        clip_inputs = clip_loader.get("inputs")
        latent = workflow["5"]
        latent_inputs = latent.get("inputs")
        decode = workflow["8"]
        decode_inputs = decode.get("inputs")
        prompt_node = workflow["6"]
        prompt_inputs = prompt_node.get("inputs")
        if not all(
            isinstance(value, dict)
            for value in (sampler_inputs, clip_inputs, latent_inputs, decode_inputs, prompt_inputs)
        ):
            raise base.StableAmdBridgeError(
                "Krea 2 workflow inputs are incomplete for Image Edit."
            )

        current_model = sampler_inputs.get("model")
        if not isinstance(current_model, list):
            current_model = ["10", 0]
        prompt = str(prompt_inputs.get("text") or "")
        image_name = str(context.get("image_name") or "").strip()
        if not image_name:
            raise base.StableAmdBridgeError("Krea 2 Image Edit source image is missing.")

        workflow["80"] = {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        }
        workflow["81"] = {
            "class_type": "FluxKontextImageScale",
            "inputs": {"image": ["80", 0]},
        }
        workflow["82"] = {
            "class_type": "GetImageSize",
            "inputs": {"image": ["81", 0]},
        }
        workflow["83"] = {
            "class_type": "Krea2OstrisEditModelPatch",
            "inputs": {"model": current_model, "kv_cache": True},
        }
        workflow["84"] = {
            "class_type": "SelectVAEDevice",
            "inputs": {"vae": ["12", 0], "device": "gpu:0"},
        }
        workflow["85"] = {
            "class_type": "TextEncodeKrea2OstrisEdit",
            "inputs": {
                "clip": ["11", 0],
                "prompt": prompt,
                "vae": ["84", 0],
                "image1": ["81", 0],
            },
        }

        cfg_value = sampler_inputs.get("cfg")
        try:
            cfg_is_one = math.isclose(float(cfg_value), 1.0, rel_tol=1e-9, abs_tol=1e-9)
        except (TypeError, ValueError):
            cfg_is_one = False
        negative_inputs: dict[str, Any] = {
            "clip": ["11", 0],
            "prompt": "",
        }
        if not cfg_is_one:
            negative_inputs["vae"] = ["84", 0]
            negative_inputs["image1"] = ["81", 0]
        workflow["86"] = {
            "class_type": "TextEncodeKrea2OstrisEdit",
            "inputs": negative_inputs,
        }
        workflow["87"] = {
            "class_type": "FluxKontextMultiReferenceLatentMethod",
            "inputs": {
                "conditioning": ["85", 0],
                "reference_latents_method": "index_timestep_zero",
            },
        }
        workflow["88"] = {
            "class_type": "FluxKontextMultiReferenceLatentMethod",
            "inputs": {
                "conditioning": ["86", 0],
                "reference_latents_method": "index_timestep_zero",
            },
        }

        latent_inputs["width"] = ["82", 0]
        latent_inputs["height"] = ["82", 1]
        sampler_inputs["model"] = ["83", 0]
        sampler_inputs["positive"] = ["87", 0]
        sampler_inputs["negative"] = ["88", 0]
        clip_inputs["device"] = "default"
        decode_inputs["vae"] = ["84", 0]
        return workflow

    def _run_script(self, name: str, parameters: list[tuple[str, Any]] | None = None) -> Any:
        result = super()._run_script(name, parameters)
        context = self._active_krea_edit_context()
        if name != "Build-StableAmdWorkflow.ps1" or not context or not isinstance(result, dict):
            return result
        return self._inject_krea_image_edit(result, context)

    @staticmethod
    def _png_dimensions(path: Path) -> tuple[int, int] | None:
        try:
            header = path.read_bytes()[:24]
        except OSError:
            return None
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
            return None
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        if width <= 0 or height <= 0:
            return None
        return width, height

    def _persist_krea_image_edit_metadata(
        self,
        result: dict[str, Any],
        source_name: str,
    ) -> None:
        result["Mode"] = "img2img"
        result["EditOperation"] = "image-edit"
        result["Provider"] = "krea2-ostris-edit"
        result["InputImageName"] = source_name
        result.pop("Denoise", None)

        raw_image = str(result.get("ImagePath") or "").strip()
        if raw_image:
            dimensions = self._png_dimensions(Path(raw_image))
            if dimensions:
                result["Width"], result["Height"] = dimensions

        raw_history = str(result.get("HistoryPath") or "").strip()
        if not raw_history:
            return
        history_root = (self.repo_root / ".runtime" / "stableamd" / "history").resolve()
        history_path = Path(raw_history).resolve()
        if history_root not in history_path.parents or not history_path.is_file():
            return
        try:
            record = json.loads(history_path.read_text(encoding="utf-8-sig"))
            if not isinstance(record, dict):
                return
            record["mode"] = "img2img"
            record["editOperation"] = "image-edit"
            record["provider"] = "krea2-ostris-edit"
            record["inputImageName"] = source_name
            record.pop("denoise", None)
            if "Width" in result and "Height" in result:
                record["width"] = int(result["Width"])
                record["height"] = int(result["Height"])
            temporary = history_path.with_suffix(history_path.suffix + ".tmp-krea-edit")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(history_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise base.StableAmdBridgeError(
                f"Krea 2 Image Edit completed, but Gallery metadata could not be updated: {exc}"
            ) from exc

    def generate(self, request: dict[str, Any]) -> Any:
        selected = self._selected_product_model(request)
        family = ""
        asset_mode = ""
        if isinstance(selected, dict):
            family = str(selected.get("family") or selected.get("Family") or "").lower()
            asset_mode = str(selected.get("assetMode") or selected.get("AssetMode") or "").lower()
        mode = str(request.get("mode") or "txt2img").lower()
        if family != "krea2" or asset_mode != "bundle" or mode != "img2img":
            return super().generate(request)

        if not self._krea_image_edit_ready():
            raise base.StableAmdBridgeError(
                "Krea 2 Image Edit is not ready. Install/restart the pinned Krea edit integration first."
            )
        control_reader = getattr(self, "_control_request", None)
        if callable(control_reader) and control_reader(request) is not None:
            raise base.StableAmdBridgeError(
                "Krea 2 Image Edit and Control guidance cannot be combined in the first Image Edit gate."
            )

        source = request.get("inputImage")
        source_name = str(source.get("name") or "source-image") if isinstance(source, dict) else "source-image"
        staged = base.stage_input_image(self.repo_root, source)
        clean = dict(request)
        clean["mode"] = "txt2img"
        clean.pop("inputImage", None)
        clean.pop("denoise", None)
        clean.pop("control", None)

        self._stableamd_krea_edit_context.value = {
            "image_name": staged.name,
            "source_name": source_name,
        }
        try:
            result = super()._generate_krea2_turbo(clean, selected)
        finally:
            self._stableamd_krea_edit_context.value = None
            staged.unlink(missing_ok=True)

        if not isinstance(result, dict):
            raise base.StableAmdBridgeError("Krea 2 Image Edit provider did not return a result object.")
        self._persist_krea_image_edit_metadata(result, source_name)
        return result
