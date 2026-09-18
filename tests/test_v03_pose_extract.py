from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_edit_server as server


class StableAmdV03PoseExtractTests(unittest.TestCase):
    def test_dwpose_dependency_is_pinned(self):
        self.assertEqual(server.DWPOSE_DEPENDENCY_ID, "dwpose-openpose")
        self.assertEqual(server.DWPOSE_SOURCE_REPOSITORY, "https://github.com/reallyigor/easy_dwpose.git")
        self.assertEqual(server.DWPOSE_SOURCE_COMMIT, "6935d6537ab49c005a00fa7e9ff470542c9f6369")
        self.assertEqual(server.DWPOSE_MODEL_REPOSITORY, "yzd-v/DWPose")
        self.assertEqual(server.DWPOSE_MODEL_REVISION, "f7c16a3d45ad3783db41471848c80fbc281cabac")
        self.assertEqual(server.DWPOSE_DETECTOR_FILENAME, "yolox_l.onnx")
        self.assertEqual(server.DWPOSE_DETECTOR_BYTES, 216746733)
        self.assertEqual(
            server.DWPOSE_DETECTOR_SHA256,
            "7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411",
        )
        self.assertEqual(server.DWPOSE_POSE_FILENAME, "dw-ll_ucoco_384.onnx")
        self.assertEqual(server.DWPOSE_POSE_BYTES, 134399116)
        self.assertEqual(
            server.DWPOSE_POSE_SHA256,
            "724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843",
        )
        self.assertEqual(server.DWPOSE_LICENSE, "Apache-2.0")

    def test_final_bridge_composes_pose_extract_before_depth_and_pose_control(self):
        mro = [item.__name__ for item in server.PowerShellBridge.mro()]
        self.assertIn("PoseExtractBridgeMixin", mro)
        self.assertLess(mro.index("PoseExtractBridgeMixin"), mro.index("DepthControlBridgeMixin"))
        self.assertLess(mro.index("PoseExtractBridgeMixin"), mro.index("PoseControlBridgeMixin"))

    def test_control_dependencies_expose_installable_dwpose_preprocessor(self):
        class Parent:
            repo_root = REPO_ROOT

            def controlnet_dependencies(inner_self):
                return {"dependencies": []}

        class TestMixin(server.PoseExtractBridgeMixin, Parent):
            def _dwpose_ready(inner_self):
                return False

            def _dwpose_runtime_ready(inner_self):
                return False

            def _dwpose_source_ready(inner_self):
                return False

            def _dwpose_models_ready(inner_self):
                return False

        payload = TestMixin().controlnet_dependencies()
        dependency = next(item for item in payload["dependencies"] if item.get("id") == "dwpose-openpose")
        self.assertTrue(dependency["installable"])
        self.assertEqual(dependency["type"], "openpose-preprocessor")
        self.assertEqual(dependency["detector"]["sha256"], server.DWPOSE_DETECTOR_SHA256)
        self.assertEqual(dependency["poseModel"]["sha256"], server.DWPOSE_POSE_SHA256)
        self.assertEqual(dependency["source"]["commit"], server.DWPOSE_SOURCE_COMMIT)

    def test_openpose_preprocess_api_routes_to_bridge(self):
        source = (REPO_ROOT / "app" / "backend" / "stableamd_v03_pose_extract.py").read_text(encoding="utf-8")
        self.assertIn('/api/controlnet/preprocess/openpose', source)
        self.assertIn('preprocess_openpose', source)
        self.assertIn('peopleDetected', source)

    def test_frontend_exposes_extract_from_photo_and_uses_result_as_openpose_selection(self):
        source = (REPO_ROOT / "app" / "frontend" / "app-pose-extract.js").read_text(encoding="utf-8")
        loader = (REPO_ROOT / "app" / "frontend" / "app-generate-upscale.js").read_text(encoding="utf-8")
        self.assertIn('Extract from photo', source)
        self.assertIn('/api/controlnet/preprocess/openpose', source)
        self.assertIn('pose-extract-photo', source)
        self.assertIn('peopleDetected', source)
        self.assertIn('stableamd-openpose-extracted.png', source)
        self.assertIn("loadScript('/app-pose-extract.js')", loader)
        self.assertLess(loader.index("loadScript('/app-pose-editor.js')"), loader.index("loadScript('/app-pose-extract.js')"))


if __name__ == "__main__":
    unittest.main()
