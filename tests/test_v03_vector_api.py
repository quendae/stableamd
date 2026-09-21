from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_server as base
from stableamd_generation_jobs import GenerationJobsApiMixin
import stableamd_v03_vector as vector


class VectorApiBridge:
    def __init__(self):
        self.vector_requests: list[dict] = []
        self.install_requests: list[str] = []

    def vector_dependency(self):
        return {"id": "text-to-svg-v1", "ready": False, "status": "missing", "restartRequired": False}

    def install_vector_dependency(self, dependency_id):
        self.install_requests.append(dependency_id)
        return {"id": dependency_id, "ready": True, "status": "ready", "restartRequired": False}

    def text_to_svg(self, request):
        self.vector_requests.append(dict(request))
        return {"assetType": "svg", "provider": "zimage-vtrace", "prompt": request["prompt"]}


class TestVectorApi(vector.VectorApiMixin, GenerationJobsApiMixin, base.StableAmdApi):
    def _validate_generation(self, request):
        raise AssertionError("Vector API must not route its request through generation validation")


class VectorApiTests(unittest.TestCase):
    def _wait_completed(self, api, job_id, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            code, payload = api.dispatch("GET", f"/api/generation-jobs/{job_id}")
            self.assertEqual(code, 200)
            if payload.get("status") == "completed":
                return
            if payload.get("status") == "failed":
                self.fail(payload.get("error"))
            time.sleep(0.01)
        self.fail("Vector job did not complete")

    def test_dependency_get_and_strict_install_contract(self):
        bridge = VectorApiBridge()
        api = TestVectorApi(bridge)

        code, dependency = api.dispatch("GET", "/api/vector/dependency")
        self.assertEqual(code, 200)
        self.assertEqual(dependency["id"], "text-to-svg-v1")
        self.assertFalse(dependency["ready"])

        for body in ({}, {"id": "text-to-svg-v1"}):
            code, installed = api.dispatch("POST", "/api/vector/install", json.dumps(body).encode("utf-8"))
            self.assertEqual(code, 200)
            self.assertTrue(installed["ready"])

        self.assertEqual(bridge.install_requests, ["text-to-svg-v1", "text-to-svg-v1"])

        code, payload = api.dispatch(
            "POST",
            "/api/vector/install",
            json.dumps({"id": "other"}).encode("utf-8"),
        )
        self.assertEqual(code, 400)
        self.assertIn("text-to-svg-v1", payload["error"])

        code, payload = api.dispatch(
            "POST",
            "/api/vector/install",
            json.dumps({"id": "text-to-svg-v1", "extra": True}).encode("utf-8"),
        )
        self.assertEqual(code, 400)
        self.assertIn("Unsupported", payload["error"])

    def test_text_to_svg_validates_its_own_body_and_returns_async_job(self):
        bridge = VectorApiBridge()
        api = TestVectorApi(bridge)
        code, submitted = api.dispatch(
            "POST",
            "/api/vector/text-to-svg",
            json.dumps({
                "prompt": "fox mark",
                "style": "icon",
                "detail": "medium",
                "colors": 4,
                "background": "transparent",
                "seed": 12,
            }).encode("utf-8"),
        )
        self.assertEqual(code, 202)
        self.assertEqual(submitted["jobKind"], "vector")
        self.assertTrue(submitted["jobId"])

        self._wait_completed(api, submitted["jobId"])
        result_code, result = api.dispatch("GET", f"/api/generation-jobs/{submitted['jobId']}/result")
        self.assertEqual(result_code, 200)
        self.assertEqual(result["assetType"], "svg")
        self.assertEqual(bridge.vector_requests, [{
            "prompt": "fox mark",
            "style": "icon",
            "detail": "medium",
            "colors": 4,
            "background": "transparent",
            "seed": 12,
        }])
        self.assertNotIn("_generationTimeoutSeconds", bridge.vector_requests[0])

    def test_text_to_svg_rejects_invalid_body_before_job_submission(self):
        bridge = VectorApiBridge()
        api = TestVectorApi(bridge)
        code, payload = api.dispatch(
            "POST",
            "/api/vector/text-to-svg",
            json.dumps({"prompt": "x", "sampler": "euler"}).encode("utf-8"),
        )
        self.assertEqual(code, 400)
        self.assertIn("Unsupported", payload["error"])
        self.assertEqual(bridge.vector_requests, [])


if __name__ == "__main__":
    unittest.main()
