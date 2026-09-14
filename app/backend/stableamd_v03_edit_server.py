from __future__ import annotations

from pathlib import Path
from typing import Any

import stableamd_v03_edit_server_base as editing
from curated_model_patches import (
    CuratedModelPatchError,
    install_curated_model_patch,
    public_catalog as public_model_patch_catalog,
)

# Re-export the accepted native-edit contract so existing imports/tests keep the
# same public module surface while dependency installation is layered on top.
base = editing.base
features = editing.features
ZIMAGE_FUN_PATCH = editing.ZIMAGE_FUN_PATCH
ZIMAGE_FUN_LEGACY_PATCH = editing.ZIMAGE_FUN_LEGACY_PATCH
ZIMAGE_FUN_PATCH_SHA256 = editing.ZIMAGE_FUN_PATCH_SHA256
ZIMAGE_FUN_PATCH_BYTES = editing.ZIMAGE_FUN_PATCH_BYTES


class PowerShellBridge(editing.PowerShellBridge):
    """Final v0.3 product bridge with curated provider dependency installs."""

    def _registered_model_patches(self) -> list[str]:
        try:
            info = self._comfy_json("object_info/ModelPatchLoader")
        except base.StableAmdBridgeError:
            return []
        return self._combo_choices(info, "ModelPatchLoader", "name")

    def curated_model_patches(self) -> dict[str, Any]:
        root = (self.repo_root / ".runtime" / "stableamd" / "models" / "model_patches").resolve()
        try:
            models = public_model_patch_catalog(self.repo_root, self._registered_model_patches())
        except CuratedModelPatchError as exc:
            raise base.StableAmdBridgeError(str(exc)) from exc
        return {"root": str(root), "models": models}

    def install_curated_model_patch(self, model_id: str) -> dict[str, Any]:
        try:
            return install_curated_model_patch(
                self.repo_root,
                model_id,
                registered_patches=self._registered_model_patches(),
            )
        except CuratedModelPatchError as exc:
            raise base.StableAmdBridgeError(str(exc)) from exc


class StableAmdApi(editing.StableAmdApi):
    _curated_model_patch_install_fields = {"id"}

    def _validate_curated_model_patch_install(self, request: dict[str, Any]) -> str:
        unsupported = sorted(set(request) - self._curated_model_patch_install_fields)
        if unsupported:
            raise ValueError("Unsupported curated model patch install field(s): " + ", ".join(unsupported))
        model_id = request.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("Curated model patch id is required.")
        return model_id.strip()

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        path = target.split("?", 1)[0]
        try:
            if method == "GET" and path == "/api/model-patches/catalog":
                return 200, self.bridge.curated_model_patches()
            if method == "POST" and path == "/api/model-patches/install":
                model_id = self._validate_curated_model_patch_install(self._decode_json(body))
                return 200, self.bridge.install_curated_model_patch(model_id)
        except ValueError as exc:
            return 400, {"error": str(exc)}
        return super().dispatch(method, target, body)


# The renamed base module installs the accepted edit-aware classes first.
# Replace only the final extension points with the dependency-aware subclasses.
base.PowerShellBridge = PowerShellBridge
base.StableAmdApi = StableAmdApi


def main() -> int:
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
