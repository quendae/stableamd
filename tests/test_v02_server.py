import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from stableamd_server import PowerShellBridge, StableAmdApi


class V02Bridge:
    def __init__(self):
        self.calls = []

    def generation_options(self):
        self.calls.append(("generation_options", None))
        return {
            "samplers": ["euler", "dpmpp_2m"],
            "schedulers": ["normal", "karras"],
            "loras": ["styles\\storybook.safetensors"],
        }

    def generation_profiles(self):
        self.calls.append(("generation_profiles", None))
        return {
            "schemaVersion": 1,
            "profiles": [
                {
                    "id": "sdxl-base",
                    "family": "sdxl",
                    "defaults": {"width": 1024, "height": 1024, "steps": 25, "cfg": 6.0},
                    "combinations": [
                        {"sampler": "dpmpp_2m", "scheduler": "karras", "steps": 25, "cfg": 6.0}
                    ],
                }
            ],
        }

    def lora_roots(self):
        self.calls.append(("lora_roots", None))
        return [{"path": "D:\\AI\\LoRA", "exists": True, "managed": False}]

    def browse_lora_root(self):
        self.calls.append(("browse_lora_root", None))
        return {"cancelled": False, "path": "D:\\AI\\LoRA"}

    def add_lora_root(self, path):
        self.calls.append(("add_lora_root", path))
        return {"added": True, "path": path, "restartRequired": True}

    def remove_lora_root(self, path):
        self.calls.append(("remove_lora_root", path))
        return {"removed": True, "path": path, "restartRequired": True}

    def generate(self, request):
        self.calls.append(("generate", request))
        return {"PromptId": "v02", "LoraName": request.get("loraName", "")}


class StableAmdV02ApiTests(unittest.TestCase):
    def setUp(self):
        self.bridge = V02Bridge()
        self.api = StableAmdApi(self.bridge)

    def test_generation_options_are_exposed_as_product_metadata(self):
        status, payload = self.api.dispatch("GET", "/api/generation-options")
        self.assertEqual(status, 200)
        self.assertIn("euler", payload["samplers"])
        self.assertIn("karras", payload["schedulers"])
        self.assertEqual(payload["loras"], ["styles\\storybook.safetensors"])
        self.assertEqual(self.bridge.calls, [("generation_options", None)])

    def test_generation_profiles_are_exposed_as_versioned_product_metadata(self):
        status, payload = self.api.dispatch("GET", "/api/generation-profiles")
        self.assertEqual(status, 200)
        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["profiles"][0]["family"], "sdxl")
        self.assertEqual(payload["profiles"][0]["combinations"][0]["scheduler"], "karras")
        self.assertEqual(self.bridge.calls, [("generation_profiles", None)])

    def test_lora_folder_routes_browse_add_remove_and_list(self):
        status, payload = self.api.dispatch("GET", "/api/lora-roots")
        self.assertEqual(status, 200)
        self.assertEqual(payload[0]["path"], "D:\\AI\\LoRA")

        status, payload = self.api.dispatch("POST", "/api/lora-roots/browse", b"{}")
        self.assertEqual(status, 200)
        self.assertFalse(payload["cancelled"])

        body = json.dumps({"path": "D:\\AI\\LoRA2"}).encode("utf-8")
        status, payload = self.api.dispatch("POST", "/api/lora-roots", body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["added"])
        self.assertTrue(payload["restartRequired"])

        status, payload = self.api.dispatch("POST", "/api/lora-roots/remove", body)
        self.assertEqual(status, 200)
        self.assertTrue(payload["removed"])
        self.assertTrue(payload["restartRequired"])

    def test_generation_accepts_one_lora_with_separate_strengths(self):
        request = {
            "prompt": "storybook cat",
            "modelId": "mdl_sdxl",
            "loraName": "styles\\storybook.safetensors",
            "loraModelStrength": 0.8,
            "loraClipStrength": 0.65,
        }
        status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(payload["LoraName"], request["loraName"])
        self.assertEqual(self.bridge.calls[-1], ("generate", request))

    def test_generation_rejects_invalid_lora_strengths(self):
        for value in ("strong", True, 101, -101):
            request = {"prompt": "cat", "loraName": "style.safetensors", "loraModelStrength": value}
            before = len(self.bridge.calls)
            status, payload = self.api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))
            self.assertEqual(status, 400)
            self.assertIn("loraModelStrength", payload["error"])
            self.assertEqual(len(self.bridge.calls), before)

    def test_comfy_choice_parser_reads_node_enum_contract(self):
        payload = {
            "KSampler": {
                "input": {
                    "required": {
                        "sampler_name": [["euler", "dpmpp_2m"]],
                    }
                }
            }
        }
        self.assertEqual(
            PowerShellBridge._comfy_choice_list(payload, "KSampler", "sampler_name"),
            ["euler", "dpmpp_2m"],
        )


if __name__ == "__main__":
    unittest.main()
