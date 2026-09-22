from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))

import stableamd_v03_image_to_svg as image_to_svg


class _Bridge:
    def _krea_image_edit_ready(self):
        return False


class _Api(image_to_svg.ImageToSvgApiMixin):
    def __init__(self):
        self.bridge = _Bridge()

    @staticmethod
    def _decode_json(body):
        import json
        return json.loads(body.decode("utf-8"))

    def _submit_vector_job(self, request, method):
        return {"jobId": "test-job", "jobKind": "vector", "status": "queued"}

    def dispatch(self, method, target, body=None):
        return super().dispatch(method, target, body)


def test_image_to_svg_capabilities_gate_creative():
    capabilities = image_to_svg.image_to_svg_capabilities(_Bridge())
    assert capabilities["creative"]["provider"] == "krea2-ostris-edit"
    assert capabilities["creative"]["ready"] is False
    assert capabilities["modes"] == ["artwork", "photo-direct", "photo-stylized"]


def test_image_to_svg_api_rejects_creative_when_krea_is_unavailable():
    import json
    payload = {
        "source": {"kind": "gallery", "id": "gallery-1"},
        "mode": "photo-stylized",
        "stylization": "creative",
    }
    status, result = _Api().dispatch(
        "POST",
        "/api/vector/image-to-svg",
        json.dumps(payload).encode("utf-8"),
    )
    assert status == 409
    assert "Krea Image Edit" in result["error"]


def test_image_to_svg_api_submits_local_mode():
    import json
    payload = {
        "source": {"kind": "gallery", "id": "gallery-1"},
        "mode": "photo-direct",
        "detail": "simple",
        "colors": 4,
        "cropMode": "auto",
    }
    api = _Api()
    status, result = api.dispatch(
        "POST",
        "/api/vector/image-to-svg",
        json.dumps(payload).encode("utf-8"),
    )
    assert status == 202
    assert result["jobKind"] == "vector"
    assert result["status"] == "queued"
