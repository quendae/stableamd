from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CAPABILITY_MODES = ("txt2img", "img2img", "inpaint", "controlnet", "lora")
VALID_CAPABILITY_STATES = {"supported", "planned", "unsupported"}


def load_model_support_catalog(repo_root: Path) -> dict[str, Any]:
    path = Path(repo_root).resolve() / "config" / "model-support.v0.3.json"
    if not path.is_file():
        raise FileNotFoundError(f"StableAMD model support catalog is missing: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("StableAMD model support catalog has an unsupported schema.")

    families = payload.get("families")
    if not isinstance(families, dict):
        raise ValueError("StableAMD model support catalog does not contain a families map.")

    for family_id, family in families.items():
        if not isinstance(family, dict):
            raise ValueError(f"Model family '{family_id}' must be an object.")
        capabilities = family.get("capabilities")
        if not isinstance(capabilities, dict):
            raise ValueError(f"Model family '{family_id}' does not define capabilities.")
        for mode in CAPABILITY_MODES:
            state = capabilities.get(mode, "unsupported")
            if state not in VALID_CAPABILITY_STATES:
                raise ValueError(f"Model family '{family_id}' has invalid capability state '{state}' for '{mode}'.")

    return payload


def resolve_model_support(catalog: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    family_id = str(model.get("family") or "unknown").strip().lower() or "unknown"
    family = (catalog.get("families") or {}).get(family_id)

    if not isinstance(family, dict):
        return {
            "id": model.get("id"),
            "name": model.get("name"),
            "family": family_id,
            "label": "Unsupported / unknown model",
            "provider": "unsupported",
            "assetMode": "unknown",
            "requiredAssetRoles": [],
            "capabilities": {mode: "unsupported" for mode in CAPABILITY_MODES},
        }

    capabilities = {
        mode: str((family.get("capabilities") or {}).get(mode, "unsupported"))
        for mode in CAPABILITY_MODES
    }
    return {
        "id": model.get("id"),
        "name": model.get("name"),
        "family": family_id,
        "label": family.get("label") or family_id,
        "provider": family.get("provider") or "unsupported",
        "assetMode": family.get("assetMode") or "unknown",
        "requiredAssetRoles": list(family.get("requiredAssetRoles") or []),
        "capabilities": capabilities,
    }


def summarize_model_support(catalog: dict[str, Any], models: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "catalogVersion": str(catalog.get("catalogVersion") or "0.3"),
        "modes": list(catalog.get("modes") or CAPABILITY_MODES),
        "models": [resolve_model_support(catalog, model) for model in models],
    }
