from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_svg_vectorizer as vectorizer


class _BytesResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class _Completed:
    returncode = 0
    stdout = ""
    stderr = ""


class SvgVectorizerDependencyTests(unittest.TestCase):
    def test_dependency_constants_are_pinned(self):
        self.assertEqual(vectorizer.VECTOR_DEPENDENCY_ID, "text-to-svg-v1")
        self.assertEqual(vectorizer.VTRACER_VERSION, "1.0.0-alpha.4")
        self.assertEqual(
            vectorizer.VTRACER_URL,
            "https://github.com/visioncortex/vtracer/releases/download/1.0.0-alpha.4/vtracer-x86_64-pc-windows-msvc.zip",
        )
        self.assertEqual(vectorizer.VTRACER_BYTES, 965_231)
        self.assertEqual(
            vectorizer.VTRACER_SHA256,
            "8eadb5529864265f003f791ad9cb128e1b9b8b8af8c21016f38b04706bcf3531",
        )
        self.assertEqual(vectorizer.RESVG_PY_VERSION, "0.5.0")

    def test_dependency_status_reports_missing_invalid_and_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(vectorizer.metadata, "version", side_effect=vectorizer.metadata.PackageNotFoundError):
                missing = vectorizer.vector_dependency_status(root)
            self.assertFalse(missing["ready"])
            self.assertEqual(missing["status"], "missing")
            self.assertEqual(missing["vtracer"]["status"], "missing")
            self.assertEqual(missing["previewRenderer"]["status"], "missing")
            self.assertFalse(missing["restartRequired"])

            exe = vectorizer.vtracer_executable(root)
            exe.parent.mkdir(parents=True, exist_ok=True)
            exe.write_bytes(b"MZ-unverified")
            with mock.patch.object(vectorizer.metadata, "version", return_value=vectorizer.RESVG_PY_VERSION):
                invalid = vectorizer.vector_dependency_status(root)
            self.assertFalse(invalid["ready"])
            self.assertEqual(invalid["status"], "invalid")
            self.assertEqual(invalid["vtracer"]["status"], "invalid")
            self.assertEqual(invalid["previewRenderer"]["status"], "ready")

            vectorizer.vtracer_manifest(root).write_text(
                json.dumps({
                    "version": vectorizer.VTRACER_VERSION,
                    "archiveBytes": vectorizer.VTRACER_BYTES,
                    "archiveSha256": vectorizer.VTRACER_SHA256,
                }),
                encoding="utf-8",
            )
            with mock.patch.object(vectorizer.metadata, "version", return_value=vectorizer.RESVG_PY_VERSION):
                ready = vectorizer.vector_dependency_status(root)
            self.assertTrue(ready["ready"])
            self.assertEqual(ready["status"], "ready")
            self.assertEqual(ready["vtracer"]["status"], "ready")
            self.assertEqual(ready["previewRenderer"]["status"], "ready")

    def test_installer_validates_archive_and_promotes_only_verified_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            executable_payload = b"MZ-fake-vtracer"
            archive_buffer = io.BytesIO()
            with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("vtracer.exe", executable_payload)
            archive_payload = archive_buffer.getvalue()

            def fake_urlopen(request, timeout=60):
                self.assertEqual(request.full_url, vectorizer.VTRACER_URL)
                return _BytesResponse(archive_payload)

            calls = []

            def fake_run(args, **kwargs):
                calls.append(list(args))
                return _Completed()

            expected_hash = hashlib.sha256(archive_payload).hexdigest()
            with (
                mock.patch.object(vectorizer, "VTRACER_BYTES", len(archive_payload)),
                mock.patch.object(vectorizer, "VTRACER_SHA256", expected_hash),
                mock.patch.object(
                    vectorizer.metadata,
                    "version",
                    side_effect=[vectorizer.metadata.PackageNotFoundError(), vectorizer.RESVG_PY_VERSION, vectorizer.RESVG_PY_VERSION],
                ),
            ):
                result = vectorizer.install_vector_dependencies(root, urlopen_fn=fake_urlopen, run_fn=fake_run)
                manifest = json.loads(vectorizer.vtracer_manifest(root).read_text(encoding="utf-8"))

            exe = vectorizer.vtracer_executable(root)
            self.assertTrue(exe.is_file())
            self.assertEqual(exe.read_bytes(), executable_payload)
            self.assertEqual(manifest["version"], vectorizer.VTRACER_VERSION)
            self.assertEqual(manifest["archiveBytes"], len(archive_payload))
            self.assertEqual(manifest["archiveSha256"], expected_hash)
            self.assertTrue(result["ready"])
            self.assertFalse(result["restartRequired"])
            self.assertEqual(result["status"], "ready")
            self.assertEqual(len(calls), 1)
            self.assertIn("resvg_py==0.5.0", calls[0])
            tools_root = exe.parents[1]
            leftovers = [p.name for p in tools_root.iterdir() if ".partial-" in p.name or ".tmp-" in p.name]
            self.assertEqual(leftovers, [])

    def test_installer_rejects_wrong_archive_hash_without_promoting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_payload = b"not-the-pinned-archive"

            def fake_urlopen(request, timeout=60):
                return _BytesResponse(archive_payload)

            with (
                mock.patch.object(vectorizer, "VTRACER_BYTES", len(archive_payload)),
                mock.patch.object(vectorizer, "VTRACER_SHA256", "0" * 64),
            ):
                with self.assertRaisesRegex(vectorizer.base.StableAmdBridgeError, "checksum"):
                    vectorizer.install_vector_dependencies(root, urlopen_fn=fake_urlopen, run_fn=lambda *args, **kwargs: _Completed())

            self.assertFalse(vectorizer.vtracer_executable(root).exists())
            self.assertFalse(vectorizer.vtracer_manifest(root).exists())
            tools_root = root / ".runtime" / "stableamd" / "tools" / "vtracer"
            leftovers = list(tools_root.glob(".*partial-*")) + list(tools_root.glob(".*tmp-*")) if tools_root.exists() else []
            self.assertEqual(leftovers, [])


class SvgVectorizerArgumentTests(unittest.TestCase):
    def test_profiles_map_to_fixed_cli_and_optional_max_colors(self):
        source = Path("input.png")
        output = Path("output.svg")
        medium = vectorizer.build_vtracer_args(source, output, "medium", 8)
        self.assertEqual(medium[:4], ["--input", str(source), "--output", str(output)])
        self.assertIn("--preset", medium)
        self.assertIn("poster", medium)
        self.assertIn("--max-colors", medium)
        self.assertEqual(medium[medium.index("--max-colors") + 1], "8")

        automatic = vectorizer.build_vtracer_args(source, output, "simple", None)
        self.assertNotIn("--max-colors", automatic)

        with self.assertRaisesRegex(vectorizer.base.StableAmdBridgeError, "detail"):
            vectorizer.build_vtracer_args(source, output, "unknown", None)
        with self.assertRaisesRegex(vectorizer.base.StableAmdBridgeError, "colors"):
            vectorizer.build_vtracer_args(source, output, "medium", 3)


if __name__ == "__main__":
    unittest.main()
