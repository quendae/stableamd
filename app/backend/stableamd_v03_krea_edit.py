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
    source/reference images, composes the edit graph, and rewrites result/history
    metadata from the internal txt2img transport to the public Image Edit operation.
    """

    _KREA_EDIT_NODES = (
        "TextEncodeKrea2OstrisEdit",
        "Krea2OstrisEditModelPatch",
        "FluxKontextImageScale",
        "FluxKontextMultiReferenceLatentMethod",
        "GetImageSize",
        "SelectVAEDevice",
    )
    _REFERENCE_ROLES = ("style", "material", "content")
    _TURNAROUND_WIDTH = 1536
    _TURNAROUND_HEIGHT = 768
    _TURNAROUND_LAYOUT = "four-view-horizontal"
    _TURNAROUND_VIEWS = ("front", "three-quarter", "side", "back")
    _TURNAROUND_PROMPT_PREFIX = "Create a single character turnaround sheet using Picture 1 as the identity reference."

    def __post_init__(self) -> None:
        super().__post_init__()
        self._stableamd_krea_edit_context = local()

    def _active_krea_edit_context(self) -> dict[str, Any] | None:
        context = getattr(self._stableamd_krea_edit_context, "value", None)
        return context if isinstance(context, dict) else None

    def _krea_image_edit_ready(self) -> bool:
        return all(self._node_available(node_name) for node_name in self._KREA_EDIT_NODES)

    @staticmethod
    def _compose_reference_prompt(prompt: str, roles: str | list[str] | tuple[str, ...]) -> str:
        instruction = str(prompt or "").strip()
        role_values = [roles] if isinstance(roles, str) else list(roles or [])
        role_values = [str(role or "").strip().lower() for role in role_values][:2]
        role_values = [role for role in role_values if role in KreaImageEditBridgeMixin._REFERENCE_ROLES]
        if not role_values:
            return instruction

        parts = ["Picture 1 is the source image to edit."]
        for picture_number, role in enumerate(role_values, start=2):
            if role == "style":
                parts.append(
                    f"Picture {picture_number} is the style reference. "
                    f"Use Picture {picture_number} only as visual style guidance while preserving the source content, "
                    "geometry, layout, identity, and unrelated details unless the edit instruction says otherwise."
                )
            elif role == "material":
                parts.append(
                    f"Picture {picture_number} is the material or texture reference. "
                    f"Use the material appearance of Picture {picture_number} only where requested while preserving the source "
                    "geometry, lighting, composition, identity, and unrelated areas."
                )
            elif role == "content":
                parts.append(
                    f"Picture {picture_number} is the content reference. "
                    f"Use Picture {picture_number} as guidance for the requested object, subject, or content while preserving "
                    "the source scene and unrelated details."
                )
        prefix = " ".join(parts)
        return f"{prefix} Edit instruction: {instruction}" if instruction else prefix

    @staticmethod
    def _build_character_turnaround_instruction(notes: str = "") -> str:
        additional = str(notes or "").strip()
        instruction = (
            f"{KreaImageEditBridgeMixin._TURNAROUND_PROMPT_PREFIX} "
            "Show the same character four times from left to right: front view, three-quarter view, side profile, and back view. "
            "Keep the character identity, face, hairstyle, clothing, accessories, body proportions, colors, and materials consistent in every view. "
            "Show the full body from head to toe at equal scale, aligned to a common ground line, with a neutral relaxed pose and consistent camera height. "
            "Use a clean neutral studio background with even lighting. "
            "Do not add text, labels, borders, extra characters, props, cropped body parts, or alternate outfits."
        )
        return f"{instruction} Additional character notes: {additional}" if additional else instruction

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
                "referenceImages": {
                    "max": 2,
                    "roles": list(self._REFERENCE_ROLES),
                },
                "tasks": [
                    {
                        "id": "general",
                        "label": "General edit",
                        "referenceImages": 2,
                        "masked": False,
                    },
                    {
                        "id": "material-replace",
                        "label": "Material / texture",
                        "referenceImages": 2,
                        "masked": False,
                    },
                    {
                        "id": "character-turnaround",
                        "label": "Character turnaround",
                        "referenceImages": 0,
                        "masked": False,
                        "sourceSizeOutput": False,
                        "outputSize": {
                            "width": self._TURNAROUND_WIDTH,
                            "height": self._TURNAROUND_HEIGHT,
                        },
                        "layout": self._TURNAROUND_LAYOUT,
                        "views": list(self._TURNAROUND_VIEWS),
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
        raw_references = context.get("references")
        references: list[dict[str, str]] = []
        if isinstance(raw_references, list):
            for item in raw_references[:2]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                role = str(item.get("role") or "").strip().lower()
                if name:
                    references.append({"name": name, "role": role})
        else:
            legacy_name = str(context.get("reference_name") or "").strip()
            legacy_role = str(context.get("reference_role") or "").strip().lower()
            if legacy_name:
                references.append({"name": legacy_name, "role": legacy_role})
        if not image_name:
            raise base.StableAmdBridgeError("Krea 2 Image Edit source image is missing.")

        output_width: int | None = None
        output_height: int | None = None
        raw_output_size = context.get("output_size")
        if isinstance(raw_output_size, dict):
            try:
                output_width = int(raw_output_size.get("width"))
                output_height = int(raw_output_size.get("height"))
            except (TypeError, ValueError):
                output_width = None
                output_height = None
            if output_width is not None and output_height is not None:
                if output_width <= 0 or output_height <= 0 or output_width % 16 or output_height % 16:
                    raise base.StableAmdBridgeError("Krea 2 Image Edit output size must use positive dimensions divisible by 16.")

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
        positive_inputs: dict[str, Any] = {
            "clip": ["11", 0],
            "prompt": prompt,
            "vae": ["84", 0],
            "image1": ["81", 0],
        }
        reference_bindings: list[tuple[str, list[Any]]] = []
        for index, reference in enumerate(references):
            node_id = str(89 + index)
            input_name = f"image{index + 2}"
            workflow[node_id] = {
                "class_type": "LoadImage",
                "inputs": {"image": reference["name"]},
            }
            binding = [node_id, 0]
            positive_inputs[input_name] = binding
            reference_bindings.append((input_name, binding))
        workflow["85"] = {
            "class_type": "TextEncodeKrea2OstrisEdit",
            "inputs": positive_inputs,
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
            for input_name, binding in reference_bindings:
                negative_inputs[input_name] = binding
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

        if output_width is not None and output_height is not None:
            latent_inputs["width"] = output_width
            latent_inputs["height"] = output_height
        else:
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

    @staticmethod
    def _normalize_reference_metadata(
        references: list[dict[str, Any]] | None = None,
        reference_name: str | None = None,
        reference_role: str | None = None,
    ) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for item in references or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            role = str(item.get("role") or "").strip().lower()
            if name and role:
                normalized.append({"name": name, "role": role})
        if not normalized and reference_name and reference_role:
            normalized.append({"name": str(reference_name), "role": str(reference_role).lower()})
        return normalized[:2]

    def _persist_krea_image_edit_metadata(
        self,
        result: dict[str, Any],
        source_name: str,
        references: list[dict[str, Any]] | None = None,
        reference_name: str | None = None,
        reference_role: str | None = None,
        edit_operation: str = "image-edit",
        turnaround: dict[str, Any] | None = None,
    ) -> None:
        normalized_references = self._normalize_reference_metadata(
            references,
            reference_name=reference_name,
            reference_role=reference_role,
        )
        result["Mode"] = "img2img"
        result["EditOperation"] = "image-edit"
        if edit_operation != "image-edit":
            result["EditOperation"] = edit_operation
        result["Provider"] = "krea2-ostris-edit"
        result["InputImageName"] = source_name
        if normalized_references:
            result["ReferenceImages"] = normalized_references
            result["ReferenceImageName"] = normalized_references[0]["name"]
            result["ReferenceRole"] = normalized_references[0]["role"]
        if isinstance(turnaround, dict):
            layout = str(turnaround.get("layout") or "").strip()
            views = [str(view) for view in turnaround.get("views", []) if str(view).strip()]
            try:
                width = int(turnaround.get("width"))
                height = int(turnaround.get("height"))
            except (TypeError, ValueError):
                width = 0
                height = 0
            if layout:
                result["TurnaroundLayout"] = layout
            if views:
                result["TurnaroundViews"] = views
            if width > 0:
                result["TurnaroundWidth"] = width
            if height > 0:
                result["TurnaroundHeight"] = height
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
            record["editOperation"] = edit_operation
            record["provider"] = "krea2-ostris-edit"
            record["inputImageName"] = source_name
            if normalized_references:
                record["referenceImages"] = normalized_references
                record["referenceImageName"] = normalized_references[0]["name"]
                record["referenceRole"] = normalized_references[0]["role"]
            if isinstance(turnaround, dict):
                layout = str(turnaround.get("layout") or "").strip()
                views = [str(view) for view in turnaround.get("views", []) if str(view).strip()]
                try:
                    width = int(turnaround.get("width"))
                    height = int(turnaround.get("height"))
                except (TypeError, ValueError):
                    width = 0
                    height = 0
                if layout:
                    record["turnaroundLayout"] = layout
                if views:
                    record["turnaroundViews"] = views
                if width > 0:
                    record["turnaroundWidth"] = width
                if height > 0:
                    record["turnaroundHeight"] = height
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
        references = request.get("references")
        edit_task = str(request.get("editTask") or "").strip().lower()
        turnaround_active = edit_task == "character-turnaround"
        if references and turnaround_active:
            raise base.StableAmdBridgeError(
                "Character turnaround uses only the source character image and does not accept extra references."
            )
        if references and (family != "krea2" or asset_mode != "bundle" or mode != "img2img"):
            raise base.StableAmdBridgeError(
                "Reference images are currently supported only by Krea 2 Image Edit."
            )
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

        staged_references: list[dict[str, Any]] = []
        metadata_references: list[dict[str, str]] = []
        if isinstance(references, list) and not turnaround_active:
            for index, reference in enumerate(references[:2], start=1):
                if not isinstance(reference, dict):
                    continue
                role = str(reference.get("role") or "").lower()
                reference_image = reference.get("image")
                if not isinstance(reference_image, dict):
                    continue
                original_name = str(reference_image.get("name") or f"reference-{index}")
                staged_reference = base.stage_input_image(self.repo_root, reference_image)
                staged_references.append({
                    "path": staged_reference,
                    "name": staged_reference.name,
                    "role": role,
                })
                metadata_references.append({"name": original_name, "role": role})

        clean = dict(request)
        clean["mode"] = "txt2img"
        clean.pop("inputImage", None)
        clean.pop("denoise", None)
        clean.pop("control", None)
        clean.pop("references", None)
        clean.pop("editTask", None)

        turnaround_metadata: dict[str, Any] | None = None
        if turnaround_active:
            current_prompt = str(clean.get("prompt") or "").strip()
            if not current_prompt.startswith(self._TURNAROUND_PROMPT_PREFIX):
                clean["prompt"] = self._build_character_turnaround_instruction(current_prompt)
            clean["width"] = self._TURNAROUND_WIDTH
            clean["height"] = self._TURNAROUND_HEIGHT
            turnaround_metadata = {
                "layout": self._TURNAROUND_LAYOUT,
                "views": list(self._TURNAROUND_VIEWS),
                "width": self._TURNAROUND_WIDTH,
                "height": self._TURNAROUND_HEIGHT,
            }
        elif staged_references:
            clean["prompt"] = self._compose_reference_prompt(
                str(clean.get("prompt") or ""),
                [item["role"] for item in staged_references],
            )

        context: dict[str, Any] = {
            "image_name": staged.name,
            "source_name": source_name,
            "references": [
                {"name": item["name"], "role": item["role"]}
                for item in staged_references
            ],
        }
        if turnaround_active:
            context["output_size"] = {
                "width": self._TURNAROUND_WIDTH,
                "height": self._TURNAROUND_HEIGHT,
            }
        self._stableamd_krea_edit_context.value = context
        try:
            result = super()._generate_krea2_turbo(clean, selected)
        finally:
            self._stableamd_krea_edit_context.value = None
            staged.unlink(missing_ok=True)
            for item in staged_references:
                item["path"].unlink(missing_ok=True)

        if not isinstance(result, dict):
            raise base.StableAmdBridgeError("Krea 2 Image Edit provider did not return a result object.")
        self._persist_krea_image_edit_metadata(
            result,
            source_name,
            references=metadata_references,
            edit_operation="character-turnaround" if turnaround_active else "image-edit",
            turnaround=turnaround_metadata,
        )
        return result
