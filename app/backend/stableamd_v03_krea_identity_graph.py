from __future__ import annotations

from typing import Any

import stableamd_v03_krea_identity_edit as identity

base = identity.base


class KreaIdentityGraphBridgeMixin:
    """Patch the live Krea graph by semantic connections rather than historical node ids."""

    @staticmethod
    def _identity_graph_ref(value: Any, workflow: dict[str, Any]) -> list[Any] | None:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            return None
        node_id = str(value[0])
        if not isinstance(workflow.get(node_id), dict):
            return None
        return [node_id, value[1]]

    @staticmethod
    def _identity_graph_nodes(workflow: dict[str, Any], class_type: str) -> list[tuple[str, dict[str, Any]]]:
        return [
            (str(node_id), node)
            for node_id, node in workflow.items()
            if isinstance(node, dict) and node.get("class_type") == class_type
        ]

    @classmethod
    def _identity_graph_single_node(
        cls,
        workflow: dict[str, Any],
        class_type: str,
        label: str,
    ) -> tuple[str, dict[str, Any]]:
        matches = cls._identity_graph_nodes(workflow, class_type)
        if len(matches) != 1:
            raise base.StableAmdBridgeError(
                f"Krea 2 workflow is missing an unambiguous {label} anchor for Identity Edit."
            )
        return matches[0]

    @staticmethod
    def _identity_graph_allocate_ids(workflow: dict[str, Any], count: int) -> list[str]:
        numeric_ids = [int(key) for key in workflow if str(key).isdigit()]
        candidate = max([119, *numeric_ids]) + 1
        allocated: list[str] = []
        while len(allocated) < count:
            node_id = str(candidate)
            if node_id not in workflow:
                allocated.append(node_id)
            candidate += 1
        return allocated

    @classmethod
    def _identity_graph_anchors(cls, workflow: dict[str, Any]) -> dict[str, Any]:
        sampler_id, sampler = cls._identity_graph_single_node(workflow, "KSampler", "KSampler")
        sampler_inputs = sampler.get("inputs")
        if not isinstance(sampler_inputs, dict):
            raise base.StableAmdBridgeError("Krea 2 KSampler inputs are incomplete for Identity Edit.")

        latent_ref = cls._identity_graph_ref(sampler_inputs.get("latent_image"), workflow)
        model_ref = cls._identity_graph_ref(sampler_inputs.get("model"), workflow)
        negative_ref = cls._identity_graph_ref(sampler_inputs.get("negative"), workflow)
        positive_ref = cls._identity_graph_ref(sampler_inputs.get("positive"), workflow)
        if not all((latent_ref, model_ref, negative_ref, positive_ref)):
            raise base.StableAmdBridgeError(
                "Krea 2 KSampler is missing model/positive/negative/latent connections required by Identity Edit."
            )

        latent = workflow[latent_ref[0]]
        latent_inputs = latent.get("inputs") if isinstance(latent, dict) else None
        if not isinstance(latent_inputs, dict) or latent.get("class_type") not in {
            "EmptyLatentImage",
            "EmptySD3LatentImage",
        }:
            raise base.StableAmdBridgeError(
                "Krea 2 workflow latent anchor is incompatible with Identity Edit."
            )

        decode_candidates: list[tuple[str, dict[str, Any]]] = []
        for node_id, node in cls._identity_graph_nodes(workflow, "VAEDecode"):
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue
            samples_ref = cls._identity_graph_ref(inputs.get("samples"), workflow)
            if samples_ref and samples_ref[0] == sampler_id:
                decode_candidates.append((node_id, node))
        if len(decode_candidates) != 1:
            raise base.StableAmdBridgeError(
                "Krea 2 workflow is missing an unambiguous VAEDecode connected to the sampler."
            )
        decode_id, decode = decode_candidates[0]
        decode_inputs = decode.get("inputs")
        vae_ref = cls._identity_graph_ref(decode_inputs.get("vae"), workflow) if isinstance(decode_inputs, dict) else None
        if not vae_ref:
            raise base.StableAmdBridgeError("Krea 2 workflow is missing the VAE connection required by Identity Edit.")

        positive_node = workflow[positive_ref[0]]
        positive_inputs = positive_node.get("inputs") if isinstance(positive_node, dict) else None
        clip_ref = cls._identity_graph_ref(positive_inputs.get("clip"), workflow) if isinstance(positive_inputs, dict) else None
        if clip_ref is None:
            clip_id, _ = cls._identity_graph_single_node(workflow, "CLIPLoader", "CLIP")
            clip_ref = [clip_id, 0]

        return {
            "sampler_id": sampler_id,
            "sampler_inputs": sampler_inputs,
            "latent_ref": latent_ref,
            "latent_inputs": latent_inputs,
            "model_ref": model_ref,
            "negative_ref": negative_ref,
            "decode_id": decode_id,
            "decode_inputs": decode_inputs,
            "vae_ref": vae_ref,
            "clip_ref": clip_ref,
        }

    def _inject_krea_identity_edit(
        self,
        workflow: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(workflow, dict):
            raise base.StableAmdBridgeError("Krea 2 workflow is invalid for Identity Edit.")
        for node_name in identity.KREA_IDENTITY_REQUIRED_NODES:
            if not self._node_available(node_name):
                raise base.StableAmdBridgeError(
                    f"Krea Identity Edit requires ComfyUI node '{node_name}'. Install the pinned dependency and restart ComfyUI."
                )

        lora_name = self._lora_choice_by_leaf(identity.KREA_IDENTITY_LORA_FILENAME)
        if not lora_name:
            raise base.StableAmdBridgeError(
                f"ComfyUI does not expose '{identity.KREA_IDENTITY_LORA_FILENAME}'. Install the Krea Identity Edit dependency and restart ComfyUI."
            )

        image_name = str(context.get("image_name") or "").strip()
        identity_image_name = str(context.get("identity_image_name") or "").strip()
        if not image_name:
            raise base.StableAmdBridgeError("Krea Identity Edit source image is missing.")
        width, height = self._validate_identity_target(
            context.get("width", identity.KREA_IDENTITY_BASE_WIDTH),
            context.get("height", identity.KREA_IDENTITY_BASE_HEIGHT),
        )
        prompt = str(context.get("prompt") or "").strip()
        if not prompt:
            raise base.StableAmdBridgeError("Krea Identity Edit prompt is required.")

        anchors = self._identity_graph_anchors(workflow)
        sampler_inputs = anchors["sampler_inputs"]
        latent_inputs = anchors["latent_inputs"]
        decode_inputs = anchors["decode_inputs"]
        latent_ref = anchors["latent_ref"]
        vae_ref = anchors["vae_ref"]
        clip_ref = anchors["clip_ref"]
        negative_ref = anchors["negative_ref"]

        latent_inputs["width"] = width
        latent_inputs["height"] = height
        latent_inputs["batch_size"] = 1
        sampler_inputs["steps"] = identity.KREA_IDENTITY_BASE_STEPS
        sampler_inputs["cfg"] = 1.0
        sampler_inputs["sampler_name"] = "euler"
        sampler_inputs["scheduler"] = "simple"
        sampler_inputs["denoise"] = 1.0

        node_count = 7 if identity_image_name else 5
        ids = self._identity_graph_allocate_ids(workflow, node_count)
        source_image_id, source_latent_id = ids[0], ids[1]
        cursor = 2
        identity_image_id: str | None = None
        identity_latent_id: str | None = None
        if identity_image_name:
            identity_image_id, identity_latent_id = ids[cursor], ids[cursor + 1]
            cursor += 2
        lora_id, patch_id, grounded_id = ids[cursor], ids[cursor + 1], ids[cursor + 2]

        workflow[source_image_id] = {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        }
        workflow[source_latent_id] = {
            "class_type": "VAEEncode",
            "inputs": {"pixels": [source_image_id, 0], "vae": vae_ref},
        }
        if identity_image_name and identity_image_id and identity_latent_id:
            workflow[identity_image_id] = {
                "class_type": "LoadImage",
                "inputs": {"image": identity_image_name},
            }
            workflow[identity_latent_id] = {
                "class_type": "VAEEncode",
                "inputs": {"pixels": [identity_image_id, 0], "vae": vae_ref},
            }

        workflow[lora_id] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {
                "model": anchors["model_ref"],
                "lora_name": lora_name,
                "strength_model": identity.KREA_IDENTITY_LORA_STRENGTH,
            },
        }
        patch_inputs: dict[str, Any] = {
            "model": [lora_id, 0],
            "source_latent": [source_latent_id, 0],
            "ref_boost": identity.KREA_IDENTITY_REF_BOOST,
            "ref_boost_a": identity.KREA_IDENTITY_SCENE_REF_BOOST,
            "fit_mode": "fit",
            "vae": vae_ref,
            "source_image": [source_image_id, 0],
            "target_latent": latent_ref,
        }
        if identity_image_id and identity_latent_id:
            patch_inputs["source_latent_b"] = [identity_latent_id, 0]
            patch_inputs["source_image_b"] = [identity_image_id, 0]
        workflow[patch_id] = {
            "class_type": "Krea2EditModelPatch",
            "inputs": patch_inputs,
        }

        grounded_inputs: dict[str, Any] = {
            "clip": clip_ref,
            "prompt": prompt,
            "image": [source_image_id, 0],
            "grounding_px": identity.KREA_IDENTITY_GROUNDING_PX,
        }
        if identity_image_id:
            grounded_inputs["image_b"] = [identity_image_id, 0]
        workflow[grounded_id] = {
            "class_type": "Krea2EditGroundedEncode",
            "inputs": grounded_inputs,
        }

        sampler_inputs["model"] = [patch_id, 0]
        sampler_inputs["positive"] = [grounded_id, 0]
        # Preserve the provider graph's own negative-conditioning route. The
        # current Krea workflow uses ConditioningZeroOut; older graphs used a
        # blank CLIPTextEncode. Identity Edit must not invent either one.
        sampler_inputs["negative"] = negative_ref
        decode_inputs["vae"] = vae_ref
        return workflow
