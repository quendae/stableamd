from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from curated_model_patches import (
    CuratedModelPatchError,
    install_curated_model_patch,
    load_curated_model_patches,
    public_catalog,
)


class FakeResponse(io.BytesIO):
    pass


class CuratedModelPatchTests(unittest.TestCase):
    def _repo_with_catalog(self, root: Path, payload: bytes = b"stableamd-model-patch") -> tuple[Path, dict]:
        repo = root / "repo"
        (repo / "config").mkdir(parents=True)
        item = {
            "id": "test-patch",
            "name": "Test Patch",
            "family": "z-image-turbo",
            "filename": "test-patch.safetensors",
            "purpose": "test",
            "sourceUrl": "https://huggingface.co/example/test/resolve/main/test-patch.safetensors",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "sizeBytes": len(payload),
            "license": "Apache-2.0",
            "homepage": "https://huggingface.co/example/test",
        }
        (repo / "config" / "model-patches.v0.3.json").write_text(
            json.dumps({"schemaVersion": 1, "models": [item]}), encoding="utf-8"
        )
        return repo, item

    def test_repository_catalog_pins_union_21_lite_dependency(self):
        items = load_curated_model_patches(REPO_ROOT)
        union = next(item for item in items if item["id"] == "zimage-union21-lite-2602-8step")
        self.assertEqual(union["filename"], "Z-Image-Turbo-Fun-Controlnet-Union-2.1-lite-2602-8steps.safetensors")
        self.assertEqual(union["sizeBytes"], 2016627488)
        self.assertEqual(union["sha256"], "3ea098db9bd145be525c7e2366920b6d76c5ffd46b3d7aa8169bbc943fdaee35")
        self.assertEqual(union["family"], "z-image-turbo")

    def test_installs_only_after_size_and_checksum_match(self):
        payload = b"verified-model-patch"
        with tempfile.TemporaryDirectory() as temp:
            repo, item = self._repo_with_catalog(Path(temp), payload)

            result = install_curated_model_patch(
                repo,
                item["id"],
                registered_patches=[],
                opener=lambda request, timeout=60: FakeResponse(payload),
            )

            destination = repo / ".runtime" / "stableamd" / "models" / "model_patches" / item["filename"]
            self.assertTrue(destination.is_file())
            self.assertEqual(destination.read_bytes(), payload)
            self.assertTrue(result["installed"])
            self.assertTrue(result["restartRequired"])
            self.assertFalse(result["ready"])

            catalog = public_catalog(repo, [item["filename"]])
            self.assertTrue(catalog[0]["ready"])
            self.assertEqual(catalog[0]["integrity"], "size-ok")

    def test_rejects_bad_download_without_promoting_partial_file(self):
        payload = b"expected"
        with tempfile.TemporaryDirectory() as temp:
            repo, item = self._repo_with_catalog(Path(temp), payload)
            with self.assertRaisesRegex(CuratedModelPatchError, "size mismatch"):
                install_curated_model_patch(
                    repo,
                    item["id"],
                    opener=lambda request, timeout=60: FakeResponse(b"bad"),
                )
            root = repo / ".runtime" / "stableamd" / "models" / "model_patches"
            self.assertFalse((root / item["filename"]).exists())
            self.assertEqual(list(root.glob("*.partial-*")), [])

    def test_catalog_reports_existing_wrong_size_as_invalid_not_ready(self):
        payload = b"expected-model-patch"
        with tempfile.TemporaryDirectory() as temp:
            repo, item = self._repo_with_catalog(Path(temp), payload)
            root = repo / ".runtime" / "stableamd" / "models" / "model_patches"
            root.mkdir(parents=True)
            (root / item["filename"]).write_bytes(b"x")

            catalog = public_catalog(repo, [item["filename"]])
            self.assertTrue(catalog[0]["installedOnDisk"])
            self.assertFalse(catalog[0]["ready"])
            self.assertEqual(catalog[0]["integrity"], "size-mismatch")


if __name__ == "__main__":
    unittest.main()
