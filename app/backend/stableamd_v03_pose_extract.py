from __future__ import annotations

import base64
import colorsys
import importlib
import importlib.util
import io
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import stableamd_v03_depth_control as depthcontrol

controlnet = depthcontrol.controlnet
base = controlnet.base

DWPOSE_DEPENDENCY_ID = "dwpose-openpose"
DWPOSE_SOURCE_REPOSITORY = "https://github.com/reallyigor/easy_dwpose.git"
DWPOSE_SOURCE_COMMIT = "6935d6537ab49c005a00fa7e9ff470542c9f6369"
DWPOSE_SOURCE_LICENSE = "Apache-2.0"
DWPOSE_MODEL_REPOSITORY = "yzd-v/DWPose"
DWPOSE_MODEL_REVISION = "f7c16a3d45ad3783db41471848c80fbc281cabac"
DWPOSE_DETECTOR_FILENAME = "yolox_l.onnx"
DWPOSE_DETECTOR_BYTES = 216_746_733
DWPOSE_DETECTOR_SHA256 = "7860ae79de6c89a3c1eb72ae9a2756c0ccfbe04b7791bb5880afabd97855a411"
DWPOSE_POSE_FILENAME = "dw-ll_ucoco_384.onnx"
DWPOSE_POSE_BYTES = 134_399_116
DWPOSE_POSE_SHA256 = "724f4ff2439ed61afb86fb8a1951ec39c6220682803b4a8bd4f598cd913b1843"
DWPOSE_LICENSE = "Apache-2.0"
DWPOSE_DETECTOR_URL = (
    f"https://huggingface.co/{DWPOSE_MODEL_REPOSITORY}/resolve/"
    f"{DWPOSE_MODEL_REVISION}/{DWPOSE_DETECTOR_FILENAME}?download=true"
)
DWPOSE_POSE_URL = (
    f"https://huggingface.co/{DWPOSE_MODEL_REPOSITORY}/resolve/"
    f"{DWPOSE_MODEL_REVISION}/{DWPOSE_POSE_FILENAME}?download=true"
)
DWPOSE_ONNXRUNTIME_VERSION = "1.23.2"
DWPOSE_OPENCV_VERSION = "4.11.0.86"

_BODY_EDGES = (
    (1, 2), (2, 3), (3, 4), (1, 5), (5, 6), (6, 7),
    (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
    (1, 0), (0, 14), (14, 16), (0, 15), (15, 17),
)
_BODY_COLORS = (
    (255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0),
    (170, 255, 0), (85, 255, 0), (0, 255, 0), (0, 255, 85),
    (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255),
    (0, 0, 255), (85, 0, 255), (170, 0, 255), (255, 0, 255),
    (255, 0, 170), (255, 0, 85),
)
_HAND_EDGES = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
)
_SCORE_THRESHOLD = 0.30


class PoseExtractBridgeMixin:
    """Managed CPU DWPose photo -> OpenPose-map preprocessing.

    The generated PNG is provider-neutral. Existing Z-Image and Krea OpenPose
    routes receive it exactly like an uploaded/prepared skeleton map, so their
    already accepted graph semantics stay untouched.
    """

    def __post_init__(self) -> None:
        super().__post_init__()
        self._stableamd_dwpose_runtime: Any | None = None

    def _dwpose_source_root(self) -> Path:
        return (
            self.repo_root
            / ".runtime"
            / "stableamd"
            / "preprocessors"
            / "easy_dwpose"
        ).resolve()

    def _dwpose_model_root(self) -> Path:
        return (
            self.repo_root
            / ".runtime"
            / "stableamd"
            / "models"
            / "preprocessors"
            / "dwpose"
        ).resolve()

    def _dwpose_detector_path(self) -> Path:
        return self._dwpose_model_root() / DWPOSE_DETECTOR_FILENAME

    def _dwpose_pose_path(self) -> Path:
        return self._dwpose_model_root() / DWPOSE_POSE_FILENAME

    def _dwpose_runtime_ready(self) -> bool:
        return all(
            importlib.util.find_spec(name) is not None
            for name in ("numpy", "PIL", "onnxruntime", "cv2")
        )

    def _dwpose_source_ready(self) -> bool:
        root = self._dwpose_source_root()
        head = root / ".git" / "HEAD"
        package = root / "easy_dwpose" / "body_estimation"
        if not head.is_file() or not package.is_dir():
            return False
        try:
            revision = head.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        if revision.lower() != DWPOSE_SOURCE_COMMIT.lower():
            return False
        return all(
            (package / filename).is_file()
            for filename in ("__init__.py", "wholebody.py", "detector.py", "pose.py", "utils.py")
        )

    def _dwpose_models_ready(self) -> bool:
        detector = self._dwpose_detector_path()
        pose = self._dwpose_pose_path()
        return (
            detector.is_file()
            and detector.stat().st_size == DWPOSE_DETECTOR_BYTES
            and pose.is_file()
            and pose.stat().st_size == DWPOSE_POSE_BYTES
        )

    def _dwpose_ready(self) -> bool:
        return self._dwpose_runtime_ready() and self._dwpose_source_ready() and self._dwpose_models_ready()

    def controlnet_dependencies(self) -> dict[str, Any]:
        payload = super().controlnet_dependencies()
        dependencies = payload.setdefault("dependencies", [])
        detector = self._dwpose_detector_path()
        pose = self._dwpose_pose_path()
        dependencies.append(
            {
                "id": DWPOSE_DEPENDENCY_ID,
                "name": "DWPose photo extractor",
                "family": "shared-preprocessor",
                "type": "openpose-preprocessor",
                "ready": self._dwpose_ready(),
                "installable": True,
                "restartRequired": False,
                "source": {
                    "repository": DWPOSE_SOURCE_REPOSITORY,
                    "commit": DWPOSE_SOURCE_COMMIT,
                    "license": DWPOSE_SOURCE_LICENSE,
                    "installedOnDisk": self._dwpose_source_ready(),
                },
                "detector": {
                    "repository": DWPOSE_MODEL_REPOSITORY,
                    "revision": DWPOSE_MODEL_REVISION,
                    "filename": DWPOSE_DETECTOR_FILENAME,
                    "sizeBytes": DWPOSE_DETECTOR_BYTES,
                    "sha256": DWPOSE_DETECTOR_SHA256,
                    "license": DWPOSE_LICENSE,
                    "installedOnDisk": detector.is_file(),
                    "integrity": (
                        "size-ok"
                        if detector.is_file() and detector.stat().st_size == DWPOSE_DETECTOR_BYTES
                        else ("size-mismatch" if detector.is_file() else "missing")
                    ),
                },
                "poseModel": {
                    "repository": DWPOSE_MODEL_REPOSITORY,
                    "revision": DWPOSE_MODEL_REVISION,
                    "filename": DWPOSE_POSE_FILENAME,
                    "sizeBytes": DWPOSE_POSE_BYTES,
                    "sha256": DWPOSE_POSE_SHA256,
                    "license": DWPOSE_LICENSE,
                    "installedOnDisk": pose.is_file(),
                    "integrity": (
                        "size-ok"
                        if pose.is_file() and pose.stat().st_size == DWPOSE_POSE_BYTES
                        else ("size-mismatch" if pose.is_file() else "missing")
                    ),
                },
                "runtimeReady": self._dwpose_runtime_ready(),
                "note": (
                    "Runs DWPose locally on CPU and extracts body, hand and face keypoints for all detected people."
                ),
            }
        )
        return payload

    def _install_dwpose_python_runtime(self) -> bool:
        requirements: list[str] = []
        if importlib.util.find_spec("onnxruntime") is None:
            requirements.append(f"onnxruntime=={DWPOSE_ONNXRUNTIME_VERSION}")
        if importlib.util.find_spec("cv2") is None:
            requirements.append(f"opencv-python-headless=={DWPOSE_OPENCV_VERSION}")
        if not requirements:
            return False

        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            *requirements,
        ]
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        if process.returncode != 0:
            detail = (process.stderr or process.stdout or "pip install failed").strip()
            raise base.StableAmdBridgeError(f"Could not install the DWPose CPU runtime: {detail}")
        importlib.invalidate_caches()
        if not self._dwpose_runtime_ready():
            raise base.StableAmdBridgeError(
                "DWPose runtime packages were installed, but onnxruntime/OpenCV are not importable in the StableAMD Python runtime."
            )
        return True

    def _install_dwpose_source(self) -> bool:
        root = self._dwpose_source_root()
        if root.exists():
            if self._dwpose_source_ready():
                return False
            raise base.StableAmdBridgeError(
                f"'{root}' already exists but is not the pinned DWPose source revision. "
                "Move it aside before managed installation."
            )

        git = shutil.which("git.exe") or shutil.which("git")
        if not git:
            raise base.StableAmdBridgeError("Git is required to install the pinned DWPose source.")
        root.parent.mkdir(parents=True, exist_ok=True)
        temporary = root.parent / f".stableamd-easy-dwpose-{uuid.uuid4().hex}"
        try:
            clone = subprocess.run(
                [git, "clone", "--filter=blob:none", "--no-checkout", DWPOSE_SOURCE_REPOSITORY, str(temporary)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
            if clone.returncode != 0:
                raise base.StableAmdBridgeError((clone.stderr or clone.stdout or "git clone failed").strip())
            checkout = subprocess.run(
                [git, "-C", str(temporary), "checkout", "--detach", DWPOSE_SOURCE_COMMIT],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            if checkout.returncode != 0:
                raise base.StableAmdBridgeError((checkout.stderr or checkout.stdout or "git checkout failed").strip())
            temporary.replace(root)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        if not self._dwpose_source_ready():
            raise base.StableAmdBridgeError("Pinned DWPose source checkout did not pass integrity checks.")
        return True

    def _install_dwpose(self) -> dict[str, Any]:
        runtime_changed = self._install_dwpose_python_runtime()
        source_changed = self._install_dwpose_source()
        model_root = self._dwpose_model_root()
        model_root.mkdir(parents=True, exist_ok=True)
        detector_changed = controlnet._download_pinned(
            DWPOSE_DETECTOR_URL,
            self._dwpose_detector_path(),
            DWPOSE_DETECTOR_BYTES,
            DWPOSE_DETECTOR_SHA256,
        )
        pose_changed = controlnet._download_pinned(
            DWPOSE_POSE_URL,
            self._dwpose_pose_path(),
            DWPOSE_POSE_BYTES,
            DWPOSE_POSE_SHA256,
        )
        self._stableamd_dwpose_runtime = None
        importlib.invalidate_caches()
        ready = self._dwpose_ready()
        if not ready:
            raise base.StableAmdBridgeError("DWPose installation completed, but the managed preprocessor is not ready.")
        return {
            "id": DWPOSE_DEPENDENCY_ID,
            "installed": True,
            "ready": True,
            "restartRequired": False,
            "runtimeChanged": runtime_changed,
            "sourceChanged": source_changed,
            "detectorChanged": detector_changed,
            "poseModelChanged": pose_changed,
            "sourceCommit": DWPOSE_SOURCE_COMMIT,
            "detectorSha256": DWPOSE_DETECTOR_SHA256,
            "poseModelSha256": DWPOSE_POSE_SHA256,
            "license": DWPOSE_LICENSE,
        }

    def install_controlnet_dependency(self, dependency_id: str) -> dict[str, Any]:
        if str(dependency_id or "").strip() == DWPOSE_DEPENDENCY_ID:
            return self._install_dwpose()
        return super().install_controlnet_dependency(dependency_id)

    def _load_dwpose_runtime(self) -> Any:
        if not self._dwpose_ready():
            raise base.StableAmdBridgeError(
                "OpenPose photo extraction requires the managed DWPose dependency. "
                "Use Extract from photo once and allow StableAMD to install it."
            )
        if self._stableamd_dwpose_runtime is not None:
            return self._stableamd_dwpose_runtime

        package_root = self._dwpose_source_root() / "easy_dwpose" / "body_estimation"
        module_name = "_stableamd_easy_dwpose_body_estimation"
        try:
            module = sys.modules.get(module_name)
            if module is None:
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    package_root / "__init__.py",
                    submodule_search_locations=[str(package_root)],
                )
                if spec is None or spec.loader is None:
                    raise ImportError("could not create package spec")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except Exception:
                    sys.modules.pop(module_name, None)
                    raise
            wholebody = getattr(module, "Wholebody")
            runtime = wholebody(
                model_det=str(self._dwpose_detector_path()),
                model_pose=str(self._dwpose_pose_path()),
                device="cpu",
            )
        except Exception as exc:
            raise base.StableAmdBridgeError(f"DWPose CPU runtime could not be loaded: {exc}") from exc
        self._stableamd_dwpose_runtime = runtime
        return runtime

    @staticmethod
    def _draw_dwpose_map(candidates: Any, scores: Any, width: int, height: int) -> tuple[Any, int]:
        try:
            from PIL import Image, ImageDraw
            import numpy as np
        except Exception as exc:
            raise base.StableAmdBridgeError("DWPose rendering requires Pillow and NumPy.") from exc

        candidates = np.asarray(candidates)
        scores = np.asarray(scores)
        if candidates.ndim != 3 or scores.ndim != 2 or candidates.shape[0] != scores.shape[0]:
            raise base.StableAmdBridgeError("DWPose returned an unexpected keypoint tensor shape.")

        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        scale = max(1, int(round(min(width, height) / 512.0)))
        body_width = max(3, 5 * scale)
        joint_radius = max(3, 4 * scale)
        hand_width = max(1, 2 * scale)
        face_radius = max(1, 2 * scale)
        people_detected = 0

        for person_index in range(candidates.shape[0]):
            person_points = candidates[person_index]
            person_scores = scores[person_index]
            if person_points.shape[0] < 18 or person_scores.shape[0] < 18:
                continue
            visible_body = int(np.count_nonzero(person_scores[:18] > _SCORE_THRESHOLD))
            if visible_body < 4:
                continue
            people_detected += 1

            for edge_index, (a, b) in enumerate(_BODY_EDGES):
                if person_scores[a] <= _SCORE_THRESHOLD or person_scores[b] <= _SCORE_THRESHOLD:
                    continue
                pa = tuple(float(v) for v in person_points[a][:2])
                pb = tuple(float(v) for v in person_points[b][:2])
                draw.line((pa, pb), fill=_BODY_COLORS[edge_index % len(_BODY_COLORS)], width=body_width)

            for joint_index in range(18):
                if person_scores[joint_index] <= _SCORE_THRESHOLD:
                    continue
                x, y = (float(v) for v in person_points[joint_index][:2])
                color = _BODY_COLORS[joint_index % len(_BODY_COLORS)]
                draw.ellipse(
                    (x - joint_radius, y - joint_radius, x + joint_radius, y + joint_radius),
                    fill=color,
                )

            if person_points.shape[0] >= 92 and person_scores.shape[0] >= 92:
                for keypoint_index in range(24, 92):
                    if person_scores[keypoint_index] <= _SCORE_THRESHOLD:
                        continue
                    x, y = (float(v) for v in person_points[keypoint_index][:2])
                    draw.ellipse(
                        (x - face_radius, y - face_radius, x + face_radius, y + face_radius),
                        fill=(255, 255, 255),
                    )

            for hand_start in (92, 113):
                if person_points.shape[0] < hand_start + 21 or person_scores.shape[0] < hand_start + 21:
                    continue
                hand_points = person_points[hand_start : hand_start + 21]
                hand_scores = person_scores[hand_start : hand_start + 21]
                for edge_index, (a, b) in enumerate(_HAND_EDGES):
                    if hand_scores[a] <= _SCORE_THRESHOLD or hand_scores[b] <= _SCORE_THRESHOLD:
                        continue
                    hue = edge_index / max(1, len(_HAND_EDGES))
                    rgb = tuple(int(round(value * 255)) for value in colorsys.hsv_to_rgb(hue, 1.0, 1.0))
                    pa = tuple(float(v) for v in hand_points[a][:2])
                    pb = tuple(float(v) for v in hand_points[b][:2])
                    draw.line((pa, pb), fill=rgb, width=hand_width)
                for keypoint_index in range(21):
                    if hand_scores[keypoint_index] <= _SCORE_THRESHOLD:
                        continue
                    x, y = (float(v) for v in hand_points[keypoint_index][:2])
                    draw.ellipse(
                        (x - face_radius, y - face_radius, x + face_radius, y + face_radius),
                        fill=(255, 0, 0),
                    )

        return canvas, people_detected

    def preprocess_openpose(self, image_payload: Any) -> dict[str, Any]:
        try:
            from PIL import Image
            import numpy as np
        except Exception as exc:
            raise base.StableAmdBridgeError("OpenPose photo extraction requires Pillow and NumPy.") from exc

        _, image_bytes = base._decode_input_image(image_payload)
        try:
            source = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception as exc:
            raise base.StableAmdBridgeError(f"OpenPose source photo could not be decoded: {exc}") from exc

        width, height = source.size
        runtime = self._load_dwpose_runtime()
        try:
            candidates, scores = runtime(np.asarray(source))
            pose_map, people_detected = self._draw_dwpose_map(candidates, scores, width, height)
        except base.StableAmdBridgeError:
            raise
        except Exception as exc:
            raise base.StableAmdBridgeError(f"DWPose extraction failed: {exc}") from exc

        if people_detected < 1:
            raise base.StableAmdBridgeError(
                "DWPose did not find a usable person in this photo. Try a clearer image with the body visible."
            )
        output = io.BytesIO()
        pose_map.save(output, format="PNG", optimize=True)
        image = {
            "name": "stableamd-openpose-extracted.png",
            "mimeType": "image/png",
            "dataBase64": base64.b64encode(output.getvalue()).decode("ascii"),
        }
        return {
            "image": image,
            "width": width,
            "height": height,
            "preprocessor": DWPOSE_DEPENDENCY_ID,
            "peopleDetected": people_detected,
            "parts": {"body": True, "hands": True, "face": True},
        }


class PoseExtractApiMixin:
    """Adds photo-to-OpenPose preprocessing without changing generation requests."""

    def dispatch(self, method: str, target: str, body: bytes | None = None) -> tuple[int, Any]:
        path = target.split("?", 1)[0]
        if method == "POST" and path == "/api/controlnet/preprocess/openpose":
            try:
                request = self._decode_json(body)
                unsupported = sorted(set(request) - {"image"})
                if unsupported:
                    raise ValueError("Unsupported OpenPose preprocess field(s): " + ", ".join(unsupported))
                if "image" not in request:
                    raise ValueError("OpenPose preprocessing requires image.")
                base._decode_input_image(request["image"])
                return 200, self.bridge.preprocess_openpose(request["image"])
            except ValueError as exc:
                return 400, {"error": str(exc)}
            except base.StableAmdBridgeError as exc:
                return 409, {"error": str(exc)}
        return super().dispatch(method, target, body)
