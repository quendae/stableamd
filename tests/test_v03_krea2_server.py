import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_lora_server as server


class StableAmdV03Krea2ServerTests(unittest.TestCase):
    def _model(self, root: Path):
        diffusion = root / "krea2_turbo_fp8_scaled.safetensors"
        encoder = root / "qwen3vl_4b_fp8_scaled.safetensors"
        vae = root / "qwen_image_vae.safetensors"
        for path in (diffusion, encoder, vae):
            path.write_bytes(b"x")
        return {
            "id": "bnd_krea2",
            "name": "Krea 2 Turbo (FP8)",
            "family": "krea2",
            "provider": "krea2-bundle",
            "assetMode": "bundle",
            "assets": {
                "diffusion_model": [str(diffusion)],
                "text_encoder": [str(encoder)],
                "vae": [str(vae)],
            },
        }

    def test_generation_routes_krea2_bundle_before_generic_bundle_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = server.PowerShellBridge(Path(temporary), powershell=sys.executable)
            model = self._model(Path(temporary))
            bridge.models = lambda: [model]
            with patch.object(bridge, "_generate_krea2_turbo", return_value={"ok": True}) as generate:
                result = bridge.generate({"modelId": "bnd_krea2", "prompt": "test", "mode": "txt2img"})
            self.assertEqual(result, {"ok": True})
            generate.assert_called_once()

    def test_post_comfy_json_accepts_successful_empty_response(self):
        class EmptyResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            @staticmethod
            def read():
                return b""

        with tempfile.TemporaryDirectory() as temporary:
            bridge = server.PowerShellBridge(Path(temporary), powershell=sys.executable)
            bridge._backend_base_url = lambda: "http://127.0.0.1:8190/"
            with patch("stableamd_v03_server.urlopen", return_value=EmptyResponse()):
                result = bridge._post_comfy_json(
                    "free",
                    {"unload_models": True, "free_memory": True},
                    timeout=10,
                )
        self.assertIsNone(result)

    def test_krea2_execution_uses_official_turbo_defaults_and_records_family(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bridge = server.PowerShellBridge(root, powershell=sys.executable)
            model = self._model(root)
            image = root / ".runtime" / "stableamd" / "output" / "result.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"png")
            captured = {}

            bridge._backend_base_url = lambda: "http://127.0.0.1:8190/"
            bridge._resolve_comfy_bundle_asset_for = lambda node, input_name, path, label: path.name

            def run_script(name, parameters=None):
                captured["name"] = name
                captured["parameters"] = list(parameters or [])
                return {"9": {"class_type": "SaveImage", "inputs": {}}}

            bridge._run_script = run_script
            bridge._post_comfy_json = lambda path, payload: {"prompt_id": "krea-prompt", "node_errors": {}}
            bridge._comfy_json = lambda path: {
                "krea-prompt": {"status": {"status_str": "success", "completed": True}, "outputs": {}}
            }
            bridge._resolve_bundle_output = lambda label, prompt_id, history: image
            bridge._save_bundle_history = lambda record: root / "history.json"

            result = bridge._generate_krea2_turbo({"prompt": "test", "mode": "txt2img", "seed": 7}, model)

            params = dict(captured["parameters"])
            self.assertEqual(captured["name"], "Build-StableAmdWorkflow.ps1")
            self.assertEqual(params["Family"], "krea2")
            self.assertEqual(params["Steps"], 8)
            self.assertEqual(params["Cfg"], 1.0)
            self.assertEqual(params["SamplerName"], "euler")
            self.assertEqual(params["Scheduler"], "simple")
            self.assertEqual(params["DiffusionModelName"], "krea2_turbo_fp8_scaled.safetensors")
            self.assertEqual(params["TextEncoderName"], "qwen3vl_4b_fp8_scaled.safetensors")
            self.assertEqual(params["VaeName"], "qwen_image_vae.safetensors")
            self.assertEqual(result["Family"], "krea2")
            self.assertEqual(result["Provider"], "krea2-bundle")
            self.assertEqual(result["ImagePath"], str(image))

    def test_krea2_rejects_lora_until_product_capability_is_enabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = server.PowerShellBridge(Path(temporary), powershell=sys.executable)
            model = self._model(Path(temporary))
            with self.assertRaisesRegex(server.base.StableAmdBridgeError, "LoRA execution is not enabled"):
                bridge._generate_krea2_turbo(
                    {"prompt": "test", "mode": "txt2img", "loraStack": [{"name": "style.safetensors"}]},
                    model,
                )


if __name__ == "__main__":
    unittest.main()
