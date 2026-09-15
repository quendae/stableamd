import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_server as v03


CHECKPOINT = {
    "id": "mdl_sdxl",
    "name": "sd_xl_base_1.0.safetensors",
    "family": "sdxl",
    "assetMode": "checkpoint",
    "path": str(REPO_ROOT / "fake-sdxl.safetensors"),
}

ZIMAGE = {
    "id": "bnd_zimage",
    "name": "Z-Image Turbo",
    "family": "z-image-turbo",
    "provider": "z-image-turbo-bundle",
    "assetMode": "bundle",
    "assets": {
        "diffusion_model": [str(REPO_ROOT / "z_image_turbo_bf16.safetensors")],
        "text_encoder": [str(REPO_ROOT / "qwen_3_4b.safetensors")],
        "vae": [str(REPO_ROOT / "ae.safetensors")],
    },
}


class FakeBridge(v03.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)
        self.calls = []
        self.zimage_requests = []

    def _run_script(self, name, parameters=None):
        self.calls.append((name, parameters or []))
        if name == "List-Models.ps1":
            return {"models": [CHECKPOINT]}
        if name == "List-BundleModels.ps1":
            return {"models": [ZIMAGE]}
        if name == "Invoke-Txt2Img.ps1":
            return {"PromptId": "checkpoint-path"}
        return None

    def _generate_zimage_turbo(self, request, model):
        self.zimage_requests.append((request, model))
        return {"PromptId": "zimage-path", "ModelId": model["id"]}


class CompletionBridge(v03.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)
        self.backend_checks = 0

    def _backend_base_url(self):
        self.backend_checks += 1
        if self.backend_checks > 1:
            raise v03.base.StableAmdBridgeError("temporary post-generation health timeout")
        return "http://127.0.0.1:8190/"

    def _bundle_asset_path(self, model, role):
        return Path(model["assets"][role][0])

    def _resolve_comfy_bundle_asset(self, node_name, input_name, path):
        return path.name

    def _run_script(self, name, parameters=None):
        if name == "Build-StableAmdWorkflow.ps1":
            return {"9": {"class_type": "SaveImage", "inputs": {}}}
        return None

    def _post_comfy_json(self, relative_path, payload, timeout=60):
        return {"prompt_id": "prompt-zimage", "node_errors": {}}

    def _comfy_json(self, relative_path):
        return {
            "prompt-zimage": {
                "status": {"status_str": "success", "completed": True},
                "outputs": {"9": {"images": [{"filename": "z.png", "subfolder": ""}]}},
            }
        }

    def _resolve_zimage_output(self, prompt_id, history_entry):
        return REPO_ROOT / ".runtime" / "stableamd" / "output" / "z.png"

    def _save_zimage_history(self, record):
        return REPO_ROOT / ".runtime" / "stableamd" / "history" / "z.json"


class ConcurrentModelBridge(v03.PowerShellBridge):
    def __init__(self):
        super().__init__(REPO_ROOT, powershell=sys.executable)
        self.counter_lock = threading.Lock()
        self.active_scans = 0
        self.max_active_scans = 0

    def _run_script(self, name, parameters=None):
        if name in {"List-Models.ps1", "List-BundleModels.ps1"}:
            with self.counter_lock:
                self.active_scans += 1
                self.max_active_scans = max(self.max_active_scans, self.active_scans)
            try:
                time.sleep(0.05)
                if name == "List-Models.ps1":
                    return {"models": [CHECKPOINT]}
                return {"models": [ZIMAGE]}
            finally:
                with self.counter_lock:
                    self.active_scans -= 1
        return None


class StableAmdV03ZImageBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = FakeBridge()

    def test_models_merge_checkpoint_and_template_bundle_models(self):
        models = self.bridge.models()
        self.assertEqual([model["id"] for model in models], ["mdl_sdxl", "bnd_zimage"])
        self.assertIn(("List-BundleModels.ps1", []), self.bridge.calls)

    def test_txt2img_routes_selected_zimage_bundle_to_zimage_provider(self):
        request = {"prompt": "a glass lighthouse", "modelId": "bnd_zimage"}
        result = self.bridge.generate(request)
        self.assertEqual(result["PromptId"], "zimage-path")
        self.assertEqual(result["ModelId"], "bnd_zimage")
        self.assertEqual(len(self.bridge.zimage_requests), 1)
        self.assertEqual(self.bridge.zimage_requests[0][1]["family"], "z-image-turbo")
        self.assertFalse(any(name == "Invoke-Txt2Img.ps1" for name, _ in self.bridge.calls))

    def test_checkpoint_generation_still_uses_existing_product_command(self):
        request = {"prompt": "a red plane", "modelId": "mdl_sdxl"}
        result = self.bridge.generate(request)
        self.assertEqual(result["PromptId"], "checkpoint-path")
        self.assertTrue(any(name == "Invoke-Txt2Img.ps1" for name, _ in self.bridge.calls))

    def test_successful_zimage_prompt_does_not_require_a_second_backend_health_probe(self):
        bridge = CompletionBridge()
        result = bridge._generate_zimage_turbo(
            {"prompt": "a mountain village", "startBackendIfNeeded": True},
            ZIMAGE,
        )
        self.assertEqual(result["PromptId"], "prompt-zimage")
        self.assertEqual(result["BackendUrl"], "http://127.0.0.1:8190/")
        self.assertEqual(bridge.backend_checks, 1)

    def test_parallel_model_requests_serialize_registry_scans(self):
        bridge = ConcurrentModelBridge()
        errors = []

        def worker():
            try:
                bridge.models()
            except Exception as exc:  # pragma: no cover - captured for assertion
                errors.append(exc)

        threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)

        self.assertEqual(errors, [])
        self.assertEqual(bridge.max_active_scans, 1)


if __name__ == "__main__":
    unittest.main()
