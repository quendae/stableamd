import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_server import StableAmdApi, resolve_output_image, validate_loopback_host


class FakeBridge:
    def __init__(self):
        self.calls = []

    def status(self):
        self.calls.append(("status", None))
        return {"Status": "running", "Healthy": True, "Url": "http://127.0.0.1:8190/"}

    def models(self):
        self.calls.append(("models", None))
        return [{"id": "mdl_abc", "name": "sdxl.safetensors", "family": "sdxl"}]

    def scan_models(self):
        self.calls.append(("scan_models", None))
        return self.models()

    def model_roots(self):
        self.calls.append(("model_roots", None))
        return [{"path": r"C:\AI\Models", "exists": True, "managed": False}]

    def browse_model_root(self):
        self.calls.append(("browse_model_root", None))
        return {"cancelled": False, "path": r"D:\Models"}

    def add_model_root(self, path):
        self.calls.append(("add_model_root", path))
        return {"added": True, "path": path, "models": self.models()}

    def remove_model_root(self, path):
        self.calls.append(("remove_model_root", path))
        return {"removed": True, "path": path, "models": self.models()}

    def install_model(self, request):
        self.calls.append(("install_model", request))
        return {"id": "mdl_new", "name": request.get("filename") or Path(request.get("localPath", "model.safetensors")).name}

    def history(self, limit=0):
        self.calls.append(("history", limit))
        return [{"promptId": "p1", "prompt": "a red biplane"}]

    def generate(self, request):
        self.calls.append(("generate", request))
        return {"PromptId": "p2", "ImagePath": "C:/StableAMD/output/image.png", "Seed": request.get("seed", 1)}

    def start_backend(self):
        self.calls.append(("start_backend", None))
        return {"Status": "running", "Healthy": True}

    def stop_backend(self):
        self.calls.append(("stop_backend", None))
        return {"Status": "stopped", "Healthy": False}

    def diagnostics(self):
        self.calls.append(("diagnostics", None))
        return {"runtime": {"status": "running"}, "logs": []}


class StableAmdApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()
        self.api = StableAmdApi(self.bridge)

    def test_only_loopback_hosts_are_accepted(self):
        self.assertEqual(validate_loopback_host("127.0.0.1"), "127.0.0.1")
        self.assertEqual(validate_loopback_host("localhost"), "127.0.0.1")
        with self.assertRaises(ValueError):
            validate_loopback_host("0.0.0.0")
        with self.assertRaises(ValueError):
            validate_loopback_host("192.168.1.50")

    def test_health_is_local_and_does_not_invoke_powershell(self):
        status, payload = self.api.dispatch("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "StableAMD")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(self.bridge.calls, [])

    def test_product_get_routes_use_only_known_service_contracts(self):
        status, payload = self.api.dispatch("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["Healthy"])

        status, payload = self.api.dispatch("GET", "/api/models")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["family"], "sdxl")

        status, payload = self.api.dispatch("GET", "/api/model-roots")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["path"], r"C:\AI\Models")

        status, payload = self.api.dispatch("GET", "/api/history?limit=12")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["promptId"], "p1")

        status, payload = self.api.dispatch("GET", "/api/diagnostics")
        self.assertEqual(status, 200)
        self.assertEqual(payload["runtime"]["status"], "running")

        self.assertEqual(
            self.bridge.calls,
            [("status", None), ("models", None), ("model_roots", None), ("history", 12), ("diagnostics", None)],
        )

    def test_model_folder_routes_browse_add_remove_and_scan(self):
        status, payload = self.api.dispatch("POST", "/api/model-roots/browse", b"{}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["path"], r"D:\Models")

        request = {"path": r"D:\Models"}
        status, payload = self.api.dispatch("POST", "/api/model-roots", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertTrue(payload["added"])

        status, payload = self.api.dispatch("POST", "/api/models/scan", b"{}")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["id"], "mdl_abc")

        status, payload = self.api.dispatch("POST", "/api/model-roots/remove", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertTrue(payload["removed"])

        self.assertIn(("browse_model_root", None), self.bridge.calls)
        self.assertIn(("add_model_root", r"D:\Models"), self.bridge.calls)
        self.assertIn(("scan_models", None), self.bridge.calls)
        self.assertIn(("remove_model_root", r"D:\Models"), self.bridge.calls)

    def test_model_folder_routes_reject_missing_path_and_extra_fields(self):
        for target, request in (
            ("/api/model-roots", {}),
            ("/api/model-roots", {"path": r"D:\Models", "command": "whoami"}),
            ("/api/model-roots/remove", {"path": "   "}),
        ):
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", target, json.dumps(request).encode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("error", payload)
            self.assertEqual(len(self.bridge.calls), before)

    def test_generate_accepts_product_fields_and_rejects_raw_workflow_fields(self):
        request = {
            "prompt": "a red biplane",
            "negativePrompt": "blurry",
            "modelId": "mdl_abc",
            "width": 1024,
            "height": 1024,
            "steps": 20,
            "cfg": 7.0,
            "seed": 123,
            "samplerName": "euler",
            "scheduler": "normal",
            "startBackendIfNeeded": True,
        }
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["PromptId"], "p2")
        self.assertEqual(self.bridge.calls[-1][0], "generate")
        self.assertEqual(self.bridge.calls[-1][1]["prompt"], "a red biplane")

        for forbidden in ("workflow", "rawWorkflow", "command", "script"):
            bad = dict(request)
            bad[forbidden] = {"anything": True}
            status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(bad).encode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("unsupported", payload["error"].lower())

    def test_generate_requires_non_empty_prompt(self):
        status, payload = self.api.dispatch("POST", "/api/generate", b'{"prompt":"   "}')
        self.assertEqual(status, 400)
        self.assertIn("prompt", payload["error"].lower())

    def test_backend_lifecycle_routes_are_explicit(self):
        status, payload = self.api.dispatch("POST", "/api/backend/start", b"{}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["Status"], "running")

        status, payload = self.api.dispatch("POST", "/api/backend/stop", b"{}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["Status"], "stopped")

    def test_local_model_install_uses_product_contract(self):
        request = {
            "source": "local",
            "localPath": r"C:\AI\juggernautXL.safetensors",
            "moveLocal": False,
            "expectedSha256": "",
        }
        status, payload = self.api.dispatch("POST", "/api/models/install", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], "mdl_new")
        self.assertEqual(self.bridge.calls[-1], ("install_model", request))

    def test_huggingface_model_install_uses_product_contract(self):
        request = {
            "source": "huggingface",
            "repository": "stabilityai/stable-diffusion-xl-base-1.0",
            "filename": "sd_xl_base_1.0.safetensors",
            "revision": "main",
            "token": "",
            "expectedSha256": "",
        }
        status, payload = self.api.dispatch("POST", "/api/models/install", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "sd_xl_base_1.0.safetensors")
        self.assertEqual(self.bridge.calls[-1], ("install_model", request))

    def test_model_install_rejects_unknown_sources_missing_fields_and_arbitrary_commands(self):
        invalid_requests = [
            {"source": "ftp", "repository": "x", "filename": "x.safetensors"},
            {"source": "local"},
            {"source": "huggingface", "repository": "owner/repo"},
            {"source": "local", "localPath": r"C:\x.safetensors", "command": "whoami"},
        ]
        for request in invalid_requests:
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", "/api/models/install", json.dumps(request).encode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("error", payload)
            self.assertEqual(len(self.bridge.calls), before)

    def test_unknown_route_is_not_executed(self):
        status, payload = self.api.dispatch("POST", "/api/run-command", b'{"command":"whoami"}')
        self.assertEqual(status, 404)
        self.assertIn("not found", payload["error"].lower())
        self.assertEqual(self.bridge.calls, [])


class StableAmdOutputImageTests(unittest.TestCase):
    def test_resolves_only_existing_supported_images_under_output_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            output_root = repo_root / ".runtime" / "stableamd" / "output"
            nested = output_root / "session"
            nested.mkdir(parents=True)
            image = nested / "result.png"
            image.write_bytes(b"fake-png")

            resolved = resolve_output_image(repo_root, str(image))
            self.assertEqual(resolved, image.resolve())

    def test_rejects_paths_outside_output_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            output_root = repo_root / ".runtime" / "stableamd" / "output"
            output_root.mkdir(parents=True)
            outside = repo_root / "secret.png"
            outside.write_bytes(b"secret")

            with self.assertRaises(ValueError):
                resolve_output_image(repo_root, str(outside))

    def test_rejects_non_image_extensions_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            output_root = repo_root / ".runtime" / "stableamd" / "output"
            output_root.mkdir(parents=True)
            text_file = output_root / "notes.txt"
            text_file.write_text("not an image", encoding="utf-8")

            with self.assertRaises(ValueError):
                resolve_output_image(repo_root, str(text_file))
            with self.assertRaises(ValueError):
                resolve_output_image(repo_root, str(output_root / "missing.webp"))


if __name__ == "__main__":
    unittest.main()
