import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from lora_catalog import classify_lora, families_compatible, scan_lora_catalog


def write_safetensors(path: Path, metadata: dict[str, str] | None = None) -> None:
    header = {"__metadata__": metadata or {}}
    encoded = json.dumps(header, separators=(",", ":")).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(encoded)) + encoded)


class LoraCatalogTests(unittest.TestCase):
    def test_metadata_has_priority_over_folder_and_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "sdxl" / "looks-like-flux.safetensors"
            write_safetensors(path, {"ss_base_model_version": "sdxl_base_v1-0"})

            entry = classify_lora(path, root)
            self.assertEqual(entry["family"], "sdxl")
            self.assertEqual(entry["confidence"], "metadata")
            self.assertIn("ss_base_model_version", entry["reason"])

    def test_managed_family_folder_is_used_when_metadata_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "z-image" / "cinematic.safetensors"
            write_safetensors(path)

            entry = classify_lora(path, root)
            self.assertEqual(entry["family"], "z-image")
            self.assertEqual(entry["confidence"], "folder")

    def test_clear_filename_hint_is_only_a_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "external" / "portrait_flux_lora.safetensors"
            write_safetensors(path)

            entry = classify_lora(path, root)
            self.assertEqual(entry["family"], "flux")
            self.assertEqual(entry["confidence"], "filename")

    def test_unclassified_external_lora_stays_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "external" / "my-style.safetensors"
            write_safetensors(path)

            entry = classify_lora(path, root)
            self.assertEqual(entry["family"], "unknown")
            self.assertEqual(entry["confidence"], "unknown")

    def test_scan_recurses_deduplicates_and_keeps_comfy_relative_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_safetensors(root / "sdxl" / "style.safetensors")
            write_safetensors(root / "flux" / "detail.safetensors")

            result = scan_lora_catalog([root, root])
            self.assertEqual(len(result), 2)
            self.assertEqual(
                {item["name"] for item in result},
                {"sdxl/style.safetensors", "flux/detail.safetensors"},
            )

    def test_known_cross_family_adapters_are_incompatible_but_unknown_and_shared_are_not_blocked(self):
        self.assertTrue(families_compatible("sdxl", "sdxl"))
        self.assertTrue(families_compatible("sdxl-turbo", "sdxl"))
        self.assertTrue(families_compatible("z-image-turbo", "z-image"))
        self.assertFalse(families_compatible("z-image-turbo", "sdxl"))
        self.assertFalse(families_compatible("flux", "sdxl"))
        self.assertTrue(families_compatible("sdxl", "unknown"))
        self.assertTrue(families_compatible("sdxl", "shared"))


if __name__ == "__main__":
    unittest.main()
