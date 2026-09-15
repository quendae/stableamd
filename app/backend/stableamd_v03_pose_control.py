from __future__ import annotations

from typing import Any

import stableamd_v03_controlnet as controlnet

base = controlnet.base


class PoseControlBridgeMixin:
    """Adds direct OpenPose-map control for Z-Image Turbo.

    Alibaba PAI Union 2.1 is a union control model: the same model patch accepts
    Canny, Depth, Pose, MLSD and other prepared control maps. The existing
    StableAMD Z-Image Canny route already proves the ModelPatchLoader +
    ZImageFunControlnet path; this layer reuses it without the Canny
    preprocessor when the user supplies a prepared OpenPose map.

    The Krea 2 OpenPose adapter has one provider-specific performance detail as
    well: its published example workflow enables the Ostris edit node's
    reference K/V cache. Keep that optimization scoped to this accepted pose
    adapter instead of changing generic Krea edit behavior.
    """

    def _zimage_pose_ready(self) -> bool:
        patch_resolver = getattr(self, "_zimage_fun_patch_name", None)
        patch_ready = bool(callable(patch_resolver) and patch_resolver(required=False))
        return patch_ready and all(
            self._node_available(name)
            for name in ("ModelPatchLoader", "ZImageFunControlnet")
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
        """Match the published Krea 2 pose workflow's cached-reference mode.

        This is intentionally limited to the accepted OpenPose adapter. The
        Ostris node warns that kv_cache must only be used with adapters trained
        for it, and the published thedeoxen workflow enables the option.
        """
        result = super()._inject_krea_openpose(workflow, context)
        patch = result.get("62")
        if not isinstance(patch, dict) or patch.get("class_type") != "Krea2OstrisEditModelPatch":
            raise base.StableAmdBridgeError("Krea 2 OpenPose patch node is missing after workflow composition.")
        inputs = patch.setdefault("inputs", {})
        inputs["kv_cache"] = True
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
