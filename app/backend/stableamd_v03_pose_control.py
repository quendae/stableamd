from __future__ import annotations

from typing import Any

import stableamd_v03_controlnet as controlnet

base = controlnet.base

KREA_POSE_REF_MAX_SIDE = 512


class PoseControlBridgeMixin:
    """Adds direct OpenPose-map control for Z-Image Turbo and Krea 2 tuning.

    Alibaba PAI Union 2.1 is a union control model: the same model patch accepts
    Canny, Depth, Pose, MLSD and other prepared control maps. The existing
    StableAMD Z-Image Canny route already proves the ModelPatchLoader +
    ZImageFunControlnet path; this layer reuses it without the Canny
    preprocessor when the user supplies a prepared OpenPose map.

    Krea 2's published pose adapter was trained with isolated reference
    attention (the Ostris ``kv_cache`` mode). Running it with the normal joint
    reference path can produce weak pose adherence and visible control-image
    leakage. On the 16 GiB target, full-resolution cached references are far too
    expensive, so StableAMD keeps the correct training semantics while reducing
    only the sparse OpenPose reference map to at most 512 px on its longest
    side. The generated image itself remains at the user's selected resolution.
    """

    def _zimage_pose_ready(self) -> bool:
        patch_resolver = getattr(self, "_zimage_fun_patch_name", None)
        patch_ready = bool(callable(patch_resolver) and patch_resolver(required=False))
        return patch_ready and all(
            self._node_available(name)
            for name in ("ModelPatchLoader", "ZImageFunControlnet")
        )

    def _krea_openpose_ready(self) -> bool:
        return super()._krea_openpose_ready() and self._node_available(
            "FluxKontextMultiReferenceLatentMethod"
        )

    @staticmethod
    def _krea_pose_reference_size(width: int, height: int) -> tuple[int, int]:
        width = max(16, int(width))
        height = max(16, int(height))
        scale = min(1.0, KREA_POSE_REF_MAX_SIDE / float(max(width, height)))

        def snap(value: float) -> int:
            return max(16, int(round(value / 16.0)) * 16)

        return snap(width * scale), snap(height * scale)

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
                        item["referenceMaxSide"] = KREA_POSE_REF_MAX_SIDE
                policy["note"] = (
                    "Krea 2 OpenPose uses the adapter's isolated-reference training mode. "
                    "StableAMD feeds a compact 512 px pose reference to keep it practical on 16 GiB; "
                    "10 steps and strength 0.8-1.0 are recommended."
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
        """Use the pose adapter's trained isolated-reference mode economically.

        The published thedeoxen workflow enables ``kv_cache`` and marks both
        positive and negative reference conditioning as ``index_timestep_zero``.
        Keep those semantics, but encode the sparse pose map at <=512 px so the
        reference-only K/V pass does not carry a 1 MP OpenPose latent on the
        RX 6950 XT target.
        """
        result = super()._inject_krea_openpose(workflow, context)
        patch = result.get("62")
        sampler = result.get("3")
        scale_node = result.get("61")
        if not isinstance(patch, dict) or patch.get("class_type") != "Krea2OstrisEditModelPatch":
            raise base.StableAmdBridgeError("Krea 2 OpenPose patch node is missing after workflow composition.")
        if not isinstance(sampler, dict) or not isinstance(sampler.get("inputs"), dict):
            raise base.StableAmdBridgeError("Krea 2 OpenPose KSampler is missing after workflow composition.")
        if not isinstance(scale_node, dict) or not isinstance(scale_node.get("inputs"), dict):
            raise base.StableAmdBridgeError("Krea 2 OpenPose control-image scaler is missing after workflow composition.")
        if not self._node_available("FluxKontextMultiReferenceLatentMethod"):
            raise base.StableAmdBridgeError(
                "Krea 2 OpenPose requires FluxKontextMultiReferenceLatentMethod from the pinned ComfyUI runtime."
            )

        ref_width, ref_height = self._krea_pose_reference_size(
            int(context["width"]), int(context["height"])
        )
        scale_node["inputs"]["width"] = ref_width
        scale_node["inputs"]["height"] = ref_height
        patch.setdefault("inputs", {})["kv_cache"] = True

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
