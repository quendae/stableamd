from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server

base = server.base


class BlockingBridge:
    def __init__(self, *, fail: bool = False):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.fail = fail
        self.requests: list[dict] = []

    def generate(self, request):
        self.requests.append(dict(request))
        self.started.set()
        self.release.wait(5)
        try:
            if self.fail:
                raise base.StableAmdBridgeError("synthetic generation failure")
            return {"PromptId": "prompt-async", "ImagePath": "C:/StableAMD/output/result.png"}
        finally:
            self.finished.set()


class StableAmdGenerationJobTests(unittest.TestCase):
    def _wait_status(self, api, job_id, expected, timeout=2.0):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            code, payload = api.dispatch("GET", f"/api/generation-jobs/{job_id}")
            self.assertEqual(code, 200)
            last = payload
            if payload.get("status") == expected:
                return payload
            time.sleep(0.01)
        self.fail(f"job {job_id} did not reach {expected}; last={last}")

    def test_async_generate_returns_job_immediately_then_exposes_result(self):
        bridge = BlockingBridge()
        api = server.StableAmdApi(bridge)
        request = {"prompt": "slow image", "asyncJob": True}

        code, submitted = api.dispatch("POST", "/api/generate", json.dumps(request).encode("utf-8"))

        self.assertEqual(code, 202)
        self.assertTrue(submitted.get("jobId"))
        self.assertIn(submitted.get("status"), {"queued", "running"})
        self.assertFalse(bridge.finished.is_set())
        self.assertTrue(bridge.started.wait(1))

        job_id = submitted["jobId"]
        status = self._wait_status(api, job_id, "running")
        self.assertNotIn("result", status)

        bridge.release.set()
        completed = self._wait_status(api, job_id, "completed")
        self.assertEqual(completed["status"], "completed")

        result_code, result = api.dispatch("GET", f"/api/generation-jobs/{job_id}/result")
        self.assertEqual(result_code, 200)
        self.assertEqual(result["PromptId"], "prompt-async")
        self.assertEqual(len(bridge.requests), 1)
        self.assertNotIn("asyncJob", bridge.requests[0])
        self.assertEqual(bridge.requests[0]["_generationTimeoutSeconds"], 21600)

    def test_async_failed_job_reports_error_without_hanging_request(self):
        bridge = BlockingBridge(fail=True)
        api = server.StableAmdApi(bridge)
        code, submitted = api.dispatch(
            "POST",
            "/api/generate",
            json.dumps({"prompt": "fail", "asyncJob": True}).encode("utf-8"),
        )
        self.assertEqual(code, 202)
        self.assertTrue(bridge.started.wait(1))
        bridge.release.set()

        failed = self._wait_status(api, submitted["jobId"], "failed")
        self.assertIn("synthetic generation failure", failed["error"])
        result_code, result = api.dispatch("GET", f"/api/generation-jobs/{submitted['jobId']}/result")
        self.assertEqual(result_code, 500)
        self.assertIn("synthetic generation failure", result["error"])

    def test_generation_job_routes_reject_unknown_ids_and_running_results(self):
        bridge = BlockingBridge()
        api = server.StableAmdApi(bridge)
        code, payload = api.dispatch("GET", "/api/generation-jobs/does-not-exist")
        self.assertEqual(code, 404)
        self.assertIn("not found", payload["error"].lower())

        code, submitted = api.dispatch(
            "POST",
            "/api/generate",
            json.dumps({"prompt": "slow", "asyncJob": True}).encode("utf-8"),
        )
        self.assertEqual(code, 202)
        self.assertTrue(bridge.started.wait(1))
        result_code, result = api.dispatch("GET", f"/api/generation-jobs/{submitted['jobId']}/result")
        self.assertEqual(result_code, 409)
        self.assertIn(result["status"], {"queued", "running"})
        bridge.release.set()
        self._wait_status(api, submitted["jobId"], "completed")

    def test_async_krea_timeout_budget_is_six_hours(self):
        bridge = server.PowerShellBridge(REPO_ROOT, powershell=sys.executable)
        self.assertEqual(bridge._generation_timeout_seconds({"_generationTimeoutSeconds": 21600}), 21600)
        self.assertEqual(bridge._generation_timeout_seconds({}), 900)

    def test_frontend_uses_job_submit_poll_and_result_contract(self):
        source = (REPO_ROOT / "app" / "frontend" / "app-generation-jobs.js").read_text(encoding="utf-8")
        loader = (REPO_ROOT / "app" / "frontend" / "app-generate-upscale.js").read_text(encoding="utf-8")
        self.assertIn("payload.asyncJob = true", source)
        self.assertIn("/api/generation-jobs/", source)
        self.assertIn("/result", source)
        self.assertIn("/app-generation-jobs.js", loader)


if __name__ == "__main__":
    unittest.main()
