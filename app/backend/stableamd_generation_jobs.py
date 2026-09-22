from __future__ import annotations

import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock, Thread
from typing import Any
from urllib.parse import urlsplit

import stableamd_server as base

ASYNC_GENERATION_TIMEOUT_SECONDS = 6 * 60 * 60


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GenerationJobsApiMixin:
    """Short-lived HTTP transport for long-running local work.

    The legacy synchronous POST /api/generate contract remains available. The
    StableAMD UI opts into asyncJob, receives a job id immediately, then polls
    status and fetches the result through short HTTP requests. All heavy bridge
    jobs share one serialization lock so GPU-backed requests cannot compete for
    the same VRAM and Vector can reuse the transport without a second queue.
    """

    def __init__(self, bridge: Any):
        super().__init__(bridge)
        self._generation_jobs: dict[str, dict[str, Any]] = {}
        self._generation_jobs_lock = RLock()
        self._generation_run_lock = Lock()
        self._vector_run_lock = Lock()

    @staticmethod
    def _public_generation_job(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "jobId": record["jobId"],
            "jobKind": record.get("jobKind", "generation"),
            "status": record["status"],
            "createdAtUtc": record["createdAtUtc"],
            "startedAtUtc": record.get("startedAtUtc"),
            "completedAtUtc": record.get("completedAtUtc"),
            "error": record.get("error"),
        }

    def _generation_job(self, job_id: str) -> dict[str, Any] | None:
        with self._generation_jobs_lock:
            record = self._generation_jobs.get(job_id)
            return dict(record) if isinstance(record, dict) else None

    def _set_generation_job(self, job_id: str, **values: Any) -> None:
        with self._generation_jobs_lock:
            record = self._generation_jobs.get(job_id)
            if isinstance(record, dict):
                record.update(values)

    def _run_bridge_job(
        self,
        job_id: str,
        request: dict[str, Any],
        bridge_method: str,
    ) -> None:
        with self._generation_run_lock:
            self._set_generation_job(job_id, status="running", startedAtUtc=_utc_now())
            try:
                runner = getattr(self.bridge, bridge_method)
                if not callable(runner):
                    raise base.StableAmdBridgeError(
                        f"StableAMD bridge method '{bridge_method}' is unavailable."
                    )
                result = runner(request)
            except Exception as exc:
                self._set_generation_job(
                    job_id,
                    status="failed",
                    completedAtUtc=_utc_now(),
                    error=str(exc) or exc.__class__.__name__,
                )
                return
            self._set_generation_job(
                job_id,
                status="completed",
                completedAtUtc=_utc_now(),
                result=result,
                error=None,
            )

    def _run_generation_job(self, job_id: str, request: dict[str, Any]) -> None:
        self._run_bridge_job(job_id, request, "generate")

    def _run_vector_job(self, job_id: str, request: dict[str, Any], bridge_method: str) -> None:
        # Local Image-to-SVG work is CPU-bound and must not wait behind GPU
        # generation. Creative mode acquires the GPU lock only inside the bridge
        # for its Krea preprocessing stage.
        with self._vector_run_lock:
            self._set_generation_job(job_id, status="running", startedAtUtc=_utc_now())
            try:
                runner = getattr(self.bridge, bridge_method)
                if not callable(runner):
                    raise base.StableAmdBridgeError(
                        f"StableAMD bridge method '{bridge_method}' is unavailable."
                    )
                result = runner(request)
            except Exception as exc:
                self._set_generation_job(
                    job_id,
                    status="failed",
                    completedAtUtc=_utc_now(),
                    error=str(exc) or exc.__class__.__name__,
                )
                return
            self._set_generation_job(
                job_id,
                status="completed",
                completedAtUtc=_utc_now(),
                result=result,
                error=None,
            )

    def _submit_vector_job(self, request: dict[str, Any], bridge_method: str) -> dict[str, Any]:
        method_name = str(bridge_method or "").strip()
        if not method_name:
            raise ValueError("Vector jobs require a bridge method.")
        job_id = uuid.uuid4().hex
        record = {
            "jobId": job_id,
            "jobKind": "vector",
            "status": "queued",
            "createdAtUtc": _utc_now(),
            "startedAtUtc": None,
            "completedAtUtc": None,
            "error": None,
            "result": None,
        }
        with self._generation_jobs_lock:
            self._generation_jobs[job_id] = record
        worker = Thread(
            target=self._run_vector_job,
            args=(job_id, dict(request), method_name),
            name=f"stableamd-vector-{job_id[:8]}",
            daemon=True,
        )
        worker.start()
        return self._public_generation_job(record)

    def _submit_bridge_job(
        self,
        request: dict[str, Any],
        bridge_method: str,
        *,
        job_kind: str,
    ) -> dict[str, Any]:
        method_name = str(bridge_method or "").strip()
        kind = str(job_kind or "").strip()
        if not method_name or not kind:
            raise ValueError("Async bridge jobs require a bridge method and job kind.")

        job_id = uuid.uuid4().hex
        record = {
            "jobId": job_id,
            "jobKind": kind,
            "status": "queued",
            "createdAtUtc": _utc_now(),
            "startedAtUtc": None,
            "completedAtUtc": None,
            "error": None,
            "result": None,
        }
        with self._generation_jobs_lock:
            self._generation_jobs[job_id] = record
        worker = Thread(
            target=self._run_bridge_job,
            args=(job_id, dict(request), method_name),
            name=f"stableamd-{kind}-{job_id[:8]}",
            daemon=True,
        )
        worker.start()
        return self._public_generation_job(record)

    def _submit_generation_job(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._submit_bridge_job(
            request,
            "generate",
            job_kind="generation",
        )

    def _dispatch_generation_job_get(self, path: str) -> tuple[int, Any] | None:
        prefix = "/api/generation-jobs/"
        if not path.startswith(prefix):
            return None
        tail = path[len(prefix) :].strip("/")
        if not tail:
            return 404, {"error": "Generation job not found."}

        wants_result = tail.endswith("/result")
        job_id = tail[: -len("/result")].strip("/") if wants_result else tail
        if not job_id or "/" in job_id:
            return 404, {"error": "Generation job not found."}

        record = self._generation_job(job_id)
        if record is None:
            return 404, {"error": "Generation job not found."}
        if not wants_result:
            return 200, self._public_generation_job(record)

        status = str(record.get("status") or "")
        if status == "completed":
            return 200, record.get("result")
        if status == "failed":
            return 500, {"jobId": job_id, "status": status, "error": record.get("error") or "Generation failed."}
        return 409, {"jobId": job_id, "status": status or "queued", "error": None}

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        method = (method or "").upper()
        path = urlsplit(target).path

        if method == "GET":
            routed = self._dispatch_generation_job_get(path)
            if routed is not None:
                return routed

        if method == "POST" and path == "/api/generate":
            try:
                request = self._validate_generation(self._decode_json(body))
            except ValueError as exc:
                return 400, {"error": str(exc)}

            async_job = request.get("asyncJob") is True
            if async_job:
                clean = dict(request)
                clean.pop("asyncJob", None)
                # Private server-side field: callers cannot set it directly.
                # It prevents provider-internal 900 s polling limits from
                # defeating the async HTTP job transport on very slow runs.
                clean["_generationTimeoutSeconds"] = ASYNC_GENERATION_TIMEOUT_SECONDS
                return 202, self._submit_generation_job(clean)

            if "asyncJob" in request:
                clean = dict(request)
                clean.pop("asyncJob", None)
                body = json.dumps(clean, ensure_ascii=False).encode("utf-8")

        return super().dispatch(method, target, body)


class GenerationTimeoutBridgeMixin:
    """Extends Krea's internal history wait only for server-created async jobs.

    Legacy synchronous generation keeps the accepted 900-second behavior. The
    async worker injects a private timeout and this mixin uses it for Krea 2,
    including Krea OpenPose + user LoRA, without changing the workflow graph.
    """

    @staticmethod
    def _generation_timeout_seconds(request: dict[str, Any]) -> int:
        raw = request.get("_generationTimeoutSeconds", 900)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 900
        return max(5, min(24 * 60 * 60, value))

    def _generate_krea2_turbo_long(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        timeout_seconds: int,
    ) -> Any:
        if str(request.get("mode") or "txt2img").lower() != "txt2img":
            raise base.StableAmdBridgeError("Krea 2 Turbo currently supports txt2img only.")

        if request.get("startBackendIfNeeded"):
            try:
                backend_url = self._backend_base_url()
            except base.StableAmdBridgeError:
                self.start_backend()
                backend_url = self._backend_base_url()
        else:
            backend_url = self._backend_base_url()

        label = "Krea 2 Turbo"
        diffusion_path = self._bundle_asset_path_for(model, "diffusion_model", label)
        encoder_path = self._bundle_asset_path_for(model, "text_encoder", label)
        vae_path = self._bundle_asset_path_for(model, "vae", label)
        diffusion_name = self._resolve_comfy_bundle_asset_for("UNETLoader", "unet_name", diffusion_path, label)
        encoder_name = self._resolve_comfy_bundle_asset_for("CLIPLoader", "clip_name", encoder_path, label)
        vae_name = self._resolve_comfy_bundle_asset_for("VAELoader", "vae_name", vae_path, label)

        seed = int(request["seed"]) if "seed" in request else secrets.randbits(63)
        width = int(request.get("width", 1024))
        height = int(request.get("height", 1024))
        steps = int(request.get("steps", 8))
        cfg = float(request.get("cfg", 1.0))
        sampler = str(request.get("samplerName") or "euler")
        scheduler = str(request.get("scheduler") or "simple")
        filename_prefix = f"StableAMD_KREA2_TURBO_{uuid.uuid4().hex}"
        started = time.monotonic()

        workflow = self._run_script(
            "Build-StableAmdWorkflow.ps1",
            [
                ("Family", "krea2"),
                ("Mode", "txt2img"),
                ("Prompt", request["prompt"]),
                ("Width", width),
                ("Height", height),
                ("Steps", steps),
                ("Cfg", cfg),
                ("Seed", seed),
                ("SamplerName", sampler),
                ("Scheduler", scheduler),
                ("FilenamePrefix", filename_prefix),
                ("DiffusionModelName", diffusion_name),
                ("TextEncoderName", encoder_name),
                ("VaeName", vae_name),
            ],
        )
        if not isinstance(workflow, dict):
            raise base.StableAmdBridgeError("StableAMD Krea 2 workflow builder did not return a workflow object.")

        client_id = uuid.uuid4().hex
        queued = self._post_comfy_json("prompt", {"prompt": workflow, "client_id": client_id})
        prompt_id = str(queued.get("prompt_id") or "") if isinstance(queued, dict) else ""
        if not prompt_id:
            raise base.StableAmdBridgeError("ComfyUI /prompt did not return a prompt_id for Krea 2.")
        node_errors = queued.get("node_errors") if isinstance(queued, dict) else None
        if isinstance(node_errors, dict) and node_errors:
            raise base.StableAmdBridgeError(
                "ComfyUI rejected the StableAMD Krea 2 workflow: " + json.dumps(node_errors, ensure_ascii=False)
            )

        deadline = time.monotonic() + timeout_seconds
        history_entry: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            history = self._comfy_json(f"history/{prompt_id}")
            candidate = history.get(prompt_id) if isinstance(history, dict) else None
            if isinstance(candidate, dict):
                status = candidate.get("status") or {}
                status_str = str(status.get("status_str") or "") if isinstance(status, dict) else ""
                if status_str == "error":
                    raise base.StableAmdBridgeError(
                        "ComfyUI reported a Krea 2 execution error: " + json.dumps(status, ensure_ascii=False)
                    )
                if status_str == "success" or bool(status.get("completed")):
                    history_entry = candidate
                    break
            time.sleep(0.25)
        if history_entry is None:
            raise base.StableAmdBridgeError(
                f"Krea 2 did not complete within {timeout_seconds} seconds. Prompt ID: {prompt_id}"
            )

        image_path = self._resolve_bundle_output(label, prompt_id, history_entry)
        generation_seconds = round(time.monotonic() - started, 3)
        model_id = str(model.get("id") or model.get("Id") or "")
        model_name = str(model.get("name") or model.get("Name") or "Krea 2 Turbo (FP8)")
        assets = {
            "diffusion_model": [str(diffusion_path)],
            "text_encoder": [str(encoder_path)],
            "vae": [str(vae_path)],
        }
        record = {
            "schemaVersion": 3,
            "createdAtUtc": datetime.now(timezone.utc).isoformat(),
            "promptId": prompt_id,
            "mode": "txt2img",
            "prompt": request["prompt"],
            "negativePrompt": "",
            "negativeConditioning": "zeroed-positive",
            "modelId": model_id,
            "modelName": model_name,
            "modelPath": str(diffusion_path),
            "family": "krea2",
            "provider": "krea2-bundle",
            "assetMode": "bundle",
            "bundleAssets": assets,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg": cfg,
            "seed": seed,
            "sampler": sampler,
            "scheduler": scheduler,
            "loraStack": [],
            "generationSeconds": generation_seconds,
            "imagePath": str(image_path),
            "backendUrl": backend_url,
        }
        history_path = self._save_bundle_history(record)
        return {
            "PromptId": prompt_id,
            "Mode": "txt2img",
            "Prompt": record["prompt"],
            "NegativePrompt": "",
            "ModelId": model_id,
            "ModelName": model_name,
            "ModelPath": str(diffusion_path),
            "Family": "krea2",
            "Provider": "krea2-bundle",
            "AssetMode": "bundle",
            "BundleAssets": assets,
            "Width": width,
            "Height": height,
            "Steps": steps,
            "Cfg": cfg,
            "Seed": seed,
            "Sampler": sampler,
            "Scheduler": scheduler,
            "LoraStack": [],
            "GenerationSeconds": generation_seconds,
            "ImagePath": str(image_path),
            "HistoryPath": str(history_path),
            "BackendUrl": backend_url,
        }

    def _generate_krea2_turbo(self, request: dict[str, Any], model: dict[str, Any]) -> Any:
        if "_generationTimeoutSeconds" not in request:
            return super()._generate_krea2_turbo(request, model)

        timeout_seconds = self._generation_timeout_seconds(request)
        resolver = getattr(self, "_resolve_krea_loras", None)
        stack = resolver(request) if callable(resolver) else []
        clean_request = dict(request)
        clean_request.pop("loraStack", None)
        clean_request.pop("loraName", None)
        clean_request.pop("loraModelStrength", None)
        clean_request.pop("loraClipStrength", None)

        context = getattr(self, "_krea_lora_context", None)
        if context is not None:
            context.stack = stack
        try:
            result = self._generate_krea2_turbo_long(clean_request, model, timeout_seconds)
        finally:
            if context is not None:
                context.stack = []

        enabled = [entry for entry in stack if entry.get("enabled", True) is not False]
        result["LoraStack"] = stack
        result["LoraName"] = enabled[0]["name"] if len(enabled) == 1 else ""
        result["LoraModelStrength"] = enabled[0]["modelStrength"] if len(enabled) == 1 else None
        result["LoraClipStrength"] = 0.0 if len(enabled) == 1 else None
        persist = getattr(self, "_persist_krea_lora_history", None)
        if stack and callable(persist):
            persist(result, stack)
        return result
