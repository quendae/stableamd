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

import curated_upscalers
import stableamd_v03_lora_server as server


class CuratedApiBridge:
    def __init__(self):
        self.installed = []

    def curated_upscalers(self):
        return {"root": "C:/stableamd/upscale_models", "models": [{"id": "realesrgan-x4plus", "ready": False}]}

    def install_curated_upscaler(self, model_id):
        self.installed.append(model_id)
        return {"id": model_id, "installed": True, "restartRequired": True}


class StableAmdCuratedUpscalerTests(unittest.TestCase):
    def _repo_with_model(self, payload: bytes, sha256: str | None = None, size: int | None = None):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        config = root / "config"
        config.mkdir(parents=True)
        checksum = sha256 or hashlib.sha256(payload).hexdigest()
        catalog = {
            "schemaVersion": 1,
            "catalogVersion": "test",
            "models": [
                {
                    "id": "test-x4",
                    "name": "Test x4",
                    "filename": "test-4x.safetensors",
                    "nativeScale": 4,
                    "purpose": "test",
                    "sourceUrl": "https://huggingface.co/example/test/resolve/main/test-4x.safetensors",
                    "sha256": checksum,
                    "sizeBytes": size if size is not None else len(payload),
                    "license": "test-license",
                    "homepage": "https://huggingface.co/example/test",
                    "nonCommercial": False,
                }
            ],
        }
        (config / "upscalers.v0.3.json").write_text(json.dumps(catalog), encoding="utf-8")
        return temporary, root

    def test_repository_catalog_contains_pinned_x2_x4_and_ultrasharp(self):
        models = curated_upscalers.load_curated_upscalers(REPO_ROOT)
        by_id = {item["id"]: item for item in models}
        self.assertEqual(set(by_id), {"realesrgan-x2plus", "realesrgan-x4plus", "ultrasharp-x4"})
        self.assertEqual(by_id["realesrgan-x4plus"]["nativeScale"], 4)
        self.assertEqual(len(by_id["realesrgan-x4plus"]["sha256"]), 64)
        self.assertTrue(by_id["ultrasharp-x4"]["nonCommercial"])
        self.assertTrue(by_id["ultrasharp-x4"]["filename"].endswith(".safetensors"))

    def test_installs_to_managed_folder_only_after_size_and_checksum_match(self):
        payload = b"stableamd-curated-upscaler"
        temporary, root = self._repo_with_model(payload)
        self.addCleanup(temporary.cleanup)

        def opener(_request, timeout=0):
            self.assertEqual(timeout, 60)
            return io.BytesIO(payload)

        result = curated_upscalers.install_curated_upscaler(root, "test-x4", opener=opener)
        destination = root / ".runtime" / "stableamd" / "models" / "upscale_models" / "test-4x.safetensors"
        self.assertTrue(destination.is_file())
        self.assertEqual(destination.read_bytes(), payload)
        self.assertTrue(result["installed"])
        self.assertTrue(result["restartRequired"])

    def test_checksum_mismatch_never_promotes_partial_download(self):
        payload = b"wrong-content"
        temporary, root = self._repo_with_model(payload, sha256="0" * 64)
        self.addCleanup(temporary.cleanup)

        with self.assertRaises(curated_upscalers.CuratedUpscalerError):
            curated_upscalers.install_curated_upscaler(root, "test-x4", opener=lambda *_args, **_kwargs: io.BytesIO(payload))

        managed = root / ".runtime" / "stableamd" / "models" / "upscale_models"
        self.assertFalse((managed / "test-4x.safetensors").exists())
        self.assertEqual(list(managed.glob("*.partial-*")), [])

    def test_lora_server_exposes_catalog_and_strict_install_route(self):
        bridge = CuratedApiBridge()
        api = server.StableAmdApi(bridge)

        status, payload = api.dispatch("GET", "/api/upscale-models/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(payload["models"][0]["id"], "realesrgan-x4plus")

        status, payload = api.dispatch(
            "POST",
            "/api/upscale-models/install",
            json.dumps({"id": "realesrgan-x4plus"}).encode("utf-8"),
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["installed"])
        self.assertEqual(bridge.installed, ["realesrgan-x4plus"])

        status, payload = api.dispatch(
            "POST",
            "/api/upscale-models/install",
            json.dumps({"id": "x", "url": "https://example.invalid/model"}).encode("utf-8"),
        )
        self.assertEqual(status, 400)
        self.assertIn("Unsupported curated upscaler install field", payload["error"])


if __name__ == "__main__":
    unittest.main()
