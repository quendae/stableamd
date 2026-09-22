from __future__ import annotations

import json
import math
from typing import Any
from urllib.request import Request, urlopen

import stableamd_v03_controlnet as controlnet

base = controlnet.base


class PoseControlBridgeMixin:
    """Adds direct OpenPose-map control for Z-Image Turbo and Krea 2 tuning.

    Alibaba PAI Union 2.1 is a union control model: the same model patch accepts
    Canny, Depth, Pose, MLSD and other prepared control maps. The existing
    StableAMD Z-Image Canny route already proves the ModelPatchLoader +
    ZImageFunControlnet path; this layer reuses it without the Canny
    preprocessor when the user supplies a prepared OpenPose map.

    Krea 2 follows the published pose adapter workflow: a pose map is framed to
    the selected output aspect in the browser, then passed through ComfyUI's
    FluxKontextImageScale before the Ostris edit encoder. The adapter keeps its
    trained isolated-reference semantics (kv_cache + index_timestep_zero).
    """

    def _zimage_pose_ready(self) -> bool:
        patch_resolver = getattr(self, "_zimage_fun_patch_name", None)
        patch_ready = bool(callable(patch_resolver) and patch_resolver(required=False))
        return patch_ready and all(
            self._node_available(name)
            for name in ("ModelPatchLoader", "ZImageFunControlnet")
        )

    def _krea_openpose_ready(self) -> bool:
        return super()._krea_openpose_ready() and all(
            self._node_available(name)
            for name in (
                "FluxKontextImageScale",
                "FluxKontextMultiReferenceLatentMethod",
                "SelectVAEDevice",
            )
        )

    def model_support(self) -> dict[str, Any]:
        support = super().model_support()
        if not isinstance(support, dict):
            return support

        pose_ready = self._zimage_pose_ready()
        for entry in support.get("models", []):
            if not isinstance(entry, dict):
                continue
            family = str(entry.get("family") or "").lower()
            if family == "krea2":
                policy = entry.setdefault("controlPolicy", {})
                controls = policy.setdefault("controls", [])
                for item in controls:
                    if isinstance(item, dict) and str(item.get("id") or "").lower() == "openpose":
                        item["strengthDefault"] = 1.0
                        item["recommendedSteps"] = 10
                        item.pop("referenceMaxSide", None)
                        item["referenceScaler"] = "FluxKontextImageScale"
                policy["note"] = (
                    "Krea 2 OpenPose follows the adapter's isolated-reference workflow and "
                    "ComfyUI FluxKontextImageScale training-size preprocessing; 10 steps and "
                    "strength 0.8-1.0 are recommended."
                )
                continue
            if family != "z-image-turbo":
                continue

            policy = entry.setdefault("controlPolicy", {})
            controls = policy.setdefault("controls", [])
            if not any(str(item.get("id") or "").lower() == "openpose" for item in controls if isinstance(item, dict)):
                controls.append(
                    {
                        "id": "openpose",
                        "label": "OpenPose map",
                        "status": "supported" if pose_ready else "planned",
                        "inputKind": "openpose-map",
                        "preprocessor": "precomputed-or-editor",
                        "strengthDefault": 0.9,
                    }
                )
            policy["note"] = (
                "Union 2.1 exposes Canny and prepared OpenPose maps. "
                "Choose a template, use the interactive pose editor, or upload your own map."
            )
            capabilities = entry.get("capabilities")
            if isinstance(capabilities, dict) and pose_ready:
                capabilities["controlnet"] = "supported"
        return support

    def _inject_krea_openpose(self, workflow: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Mirror the published Krea pose-reference preprocessing and semantics.

        The published workflow sends the pose map through FluxKontextImageScale
        before TextEncodeKrea2OstrisEdit, enables kv_cache on the model patch,
        and marks positive and negative reference conditioning as
        index_timestep_zero. StableAMD keeps the user's target latent size while
        matching that reference path. The process-wide CPU-VAE guard remains in
        place for the accepted Z-Image path, while this Krea-only graph retargets
        its small WanVAE to gpu:0 for the reference encode and final decode.
        Krea OpenPose also lets the Qwen3-VL text/vision encoder use ComfyUI's
        normal DynamicVRAM device policy instead of pinning its ~5 GiB model to
        CPU; model management can offload it again before the Krea2 denoiser.
        At CFG=1 ComfyUI does not evaluate the unconditional branch during
        denoising, so its expensive duplicate reference-image/VAE encode is
        omitted while the positive reference path remains unchanged.
        """
        result = super()._inject_krea_openpose(workflow, context)
        patch = result.get("62")
        sampler = result.get("3")
        clip_loader = result.get("11")
        positive = result.get("64")
        decode = result.get("8")
        if not isinstance(patch, dict) or patch.get("class_type") != "Krea2OstrisEditModelPatch":
            raise base.StableAmdBridgeError("Krea 2 OpenPose patch node is missing after workflow composition.")
        if not isinstance(sampler, dict) or not isinstance(sampler.get("inputs"), dict):
            raise base.StableAmdBridgeError("Krea 2 OpenPose KSampler is missing after workflow composition.")
        if not isinstance(clip_loader, dict) or clip_loader.get("class_type") != "CLIPLoader" or not isinstance(clip_loader.get("inputs"), dict):
            raise base.StableAmdBridgeError("Krea 2 OpenPose CLIP loader is missing after workflow composition.")
        if not isinstance(positive, dict) or not isinstance(positive.get("inputs"), dict):
            raise base.StableAmdBridgeError("Krea 2 OpenPose positive reference encoder is missing after workflow composition.")
        if not isinstance(decode, dict) or decode.get("class_type") != "VAEDecode" or not isinstance(decode.get("inputs"), dict):
            raise base.StableAmdBridgeError("Krea 2 OpenPose VAE decode node is missing after workflow composition.")
        if not self._node_available("FluxKontextImageScale"):
            raise base.StableAmdBridgeError(
                "Krea 2 OpenPose requires FluxKontextImageScale from the pinned ComfyUI runtime."
            )
        if not self._node_available("FluxKontextMultiReferenceLatentMethod"):
            raise base.StableAmdBridgeError(
                "Krea 2 OpenPose requires FluxKontextMultiReferenceLatentMethod from the pinned ComfyUI runtime."
            )
        if not self._node_available("SelectVAEDevice"):
            raise base.StableAmdBridgeError(
                "Krea 2 OpenPose requires SelectVAEDevice from the pinned ComfyUI runtime."
            )

        result["61"] = {
            "class_type": "FluxKontextImageScale",
            "inputs": {"image": ["60", 0]},
        }
        patch.setdefault("inputs", {})["kv_cache"] = True
        clip_loader["inputs"]["device"] = "default"

        original_vae = positive["inputs"].get("vae")
        if not isinstance(original_vae, list) or len(original_vae) != 2:
            raise base.StableAmdBridgeError("Krea 2 OpenPose VAE input is missing after workflow composition.")
        result["68"] = {
            "class_type": "SelectVAEDevice",
            "inputs": {
                "vae": original_vae,
                "device": "gpu:0",
            },
        }
        positive["inputs"]["vae"] = ["68", 0]
        decode["inputs"]["vae"] = ["68", 0]

        cfg_value = sampler["inputs"].get("cfg")
        try:
            cfg_is_one = math.isclose(float(cfg_value), 1.0, rel_tol=1e-9, abs_tol=1e-9)
        except (TypeError, ValueError):
            cfg_is_one = False
        negative = result.get("65")
        if cfg_is_one and isinstance(negative, dict) and isinstance(negative.get("inputs"), dict):
            # ComfyUI sampling_function sets uncond=None at CFG=1 unless a model
            # explicitly disables that optimization. Avoid running the same
            # 1024px pose through Qwen3-VL + WanVAE a second time for an unused
            # branch. CFG>1 keeps the published positive+negative reference path.
            negative["inputs"].pop("image1", None)
            negative["inputs"].pop("vae", None)
        elif isinstance(negative, dict) and isinstance(negative.get("inputs"), dict):
            negative["inputs"]["vae"] = ["68", 0]

        result["66"] = {
            "class_type": "FluxKontextMultiReferenceLatentMethod",
            "inputs": {
                "conditioning": ["64", 0],
                "reference_latents_method": "index_timestep_zero",
            },
        }
        result["67"] = {
            "class_type": "FluxKontextMultiReferenceLatentMethod",
            "inputs": {
                "conditioning": ["65", 0],
                "reference_latents_method": "index_timestep_zero",
            },
        }
        sampler["inputs"]["positive"] = ["66", 0]
        sampler["inputs"]["negative"] = ["67", 0]
        return result

    def _inject_zimage_openpose(self, workflow: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        for node_id in ("11", "29", "3"):
            if not isinstance(workflow.get(node_id), dict):
                raise base.StableAmdBridgeError("Z-Image workflow anchors are missing for OpenPose control.")

        sampler_model = workflow["11"].get("inputs", {}).get("model")
        if not isinstance(sampler_model, list):
            raise base.StableAmdBridgeError("Z-Image sampling model input is missing for OpenPose control.")

        patch_name = self._zimage_fun_patch_name(required=True)
        width = int(context["width"])
        height = int(context["height"])

        workflow["70"] = {
            "class_type": "LoadImage",
            "inputs": {"image": context["image_name"]},
        }
        workflow["71"] = {
            "class_type": "ImageScale",
            "inputs": {
                "image": ["70", 0],
                "upscale_method": "nearest-exact",
                "width": width,
                "height": height,
                "crop": "center",
            },
        }
        workflow["72"] = {
            "class_type": "ModelPatchLoader",
            "inputs": {"name": str(patch_name)},
        }
        workflow["73"] = {
            "class_type": "ZImageFunControlnet",
            "inputs": {
                "model": sampler_model,
                "model_patch": ["72", 0],
                "vae": ["29", 0],
                "strength": float(context["strength"]),
                "image": ["71", 0],
            },
        }
        workflow["11"]["inputs"]["model"] = ["73", 0]
        return workflow

    def _run_script(self, name: str, parameters: list[tuple[str, Any]] | None = None) -> Any:
        result = super()._run_script(name, parameters)
        context = self._active_control_context()
        if name != "Build-StableAmdWorkflow.ps1" or not context or not isinstance(result, dict):
            return result

        if (
            str(context.get("family") or "") == "z-image-turbo"
            and str(context.get("type") or "") == "openpose"
        ):
            return self._inject_zimage_openpose(result, context)
        return result

    def _generate_zimage_openpose(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        control: dict[str, Any],
    ) -> Any:
        if not self._zimage_pose_ready():
            raise base.StableAmdBridgeError(
                "Z-Image OpenPose requires the curated Union 2.1 Lite patch and "
                "the pinned ModelPatchLoader/ZImageFunControlnet nodes."
            )
        if request.get("loraStack") or str(request.get("loraName") or "").strip():
            raise base.StableAmdBridgeError(
                "Disable regular LoRAs for the first Z-Image OpenPose acceptance gate."
            )

        staged = base.stage_input_image(self.repo_root, control["image"])
        strength = self._number(control.get("strength"), 0.9, 0.0, 2.0, "Control strength")
        context = {
            "family": "z-image-turbo",
            "type": "openpose",
            "image_name": staged.name,
            "width": int(request.get("width", 1024)),
            "height": int(request.get("height", 1024)),
            "strength": strength,
        }
        clean = dict(request)
        clean.pop("control", None)
        self._stableamd_control_context.value = context
        try:
            result = super()._generate_zimage_turbo(clean, model)
        finally:
            self._stableamd_control_context.value = None
            staged.unlink(missing_ok=True)

        metadata = {
            "type": "openpose",
            "inputKind": "precomputed-or-editor-openpose-map",
            "inputName": str(control.get("image", {}).get("name") or "openpose-map"),
            "strength": strength,
            "provider": "z-image-fun-control-union-2.1",
        }
        result["Mode"] = "controlnet"
        result["Control"] = metadata
        self._persist_control_metadata(result, metadata)
        return result

    def _post_comfy_no_content(self, relative_path: str, payload: dict[str, Any], timeout: int = 60) -> None:
        url = self._backend_base_url() + relative_path.lstrip("/")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=timeout) as response:
            response.read()

    def _release_krea_openpose_runtime(self) -> bool:
        """Best-effort reset of the Krea pose working set between generations.

        Target RX 6950 XT testing showed that a second Krea OpenPose prompt can
        retain a fragmented DynamicVRAM working set and roughly double denoise
        time. ComfyUI's native /free endpoint restores the fast path without a
        backend restart. Keep this scoped to Krea OpenPose so accepted plain
        Krea and Z-Image caching behavior remains unchanged.
        """
        try:
            self._post_comfy_no_content(
                "free",
                {"unload_models": True, "free_memory": True},
                timeout=10,
            )
        except (OSError, base.StableAmdBridgeError):
            return False
        return True

    def _generate_krea_control(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        control: dict[str, Any],
    ) -> Any:
        if str(control.get("type") or "").lower() != "openpose":
            return super()._generate_krea_control(request, model, control)
        try:
            return super()._generate_krea_control(request, model, control)
        finally:
            # /free sets queue flags and wakes ComfyUI's idle worker, so the
            # unload/reset runs before the user can normally submit the next
            # StableAMD prompt. Cleanup failure must never hide a generated
            # image or the original execution error.
            self._release_krea_openpose_runtime()

    def generate(self, request: dict[str, Any]) -> Any:
        control = self._control_request(request)
        if control is None:
            return super().generate(request)

        selected = self._selected_product_model(request)
        family = ""
        if isinstance(selected, dict):
            family = str(selected.get("family") or selected.get("Family") or "").lower()
        control_type = str(control.get("type") or "").lower()

        if family == "z-image-turbo" and control_type == "openpose":
            if str(request.get("mode") or "txt2img").lower() != "txt2img":
                raise base.StableAmdBridgeError("OpenPose control currently starts from txt2img mode only.")
            return self._generate_zimage_openpose(request, selected, control)

        return super().generate(request)