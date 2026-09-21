from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import stableamd_v03_krea_identity_edit as identity
import stableamd_v03_edit_server as server


class KreaIdentityDependencyTests(unittest.TestCase):
    def test_dependency_requires_both_nodes_and_identity_lora(self):
        class Parent:
            repo_root = Path(".")

            def _node_available(self, name):
                return name in {
                    "Krea2EditModelPatch",
                    "Krea2EditGroundedEncode",
                    "LoraLoaderModelOnly",
                }

            def _lora_choice_by_leaf(self, filename, node_name="LoraLoaderModelOnly"):
                if filename == identity.KREA_IDENTITY_LORA_FILENAME:
                    return f"krea/{filename}"
                return None

        class Bridge(identity.KreaIdentityEditBridgeMixin, Parent):
            pass

        self.assertTrue(Bridge()._krea_identity_edit_ready())

        class MissingNodeParent(Parent):
            def _node_available(self, name):
                return name != "Krea2EditGroundedEncode"

        class MissingNodeBridge(identity.KreaIdentityEditBridgeMixin, MissingNodeParent):
            pass

        self.assertFalse(MissingNodeBridge()._krea_identity_edit_ready())

    def test_dependency_metadata_is_pinned_and_installable(self):
        dep = identity.KreaIdentityEditBridgeMixin._dependency_descriptor_static()
        self.assertEqual(dep["id"], "krea2-identity-edit-v1.2")
        self.assertTrue(dep["installable"])
        self.assertEqual(dep["plugin"]["repository"], "https://github.com/lbouaraba/comfyui-krea2edit.git")
        self.assertEqual(dep["plugin"]["commit"], identity.KREA_IDENTITY_PLUGIN_COMMIT)
        self.assertEqual(dep["model"]["repository"], "conradlocke/krea2-identity-edit")
        self.assertEqual(dep["model"]["filename"], "krea2_identity_edit_v1_2.safetensors")
        self.assertEqual(dep["model"]["sizeBytes"], 1_828_256_432)
        self.assertEqual(
            dep["model"]["sha256"],
            "6adf9a69cc9502d286db7b69964d37da7e9cfe4b05b4d004bc275f087d3fd3cf",
        )

    def test_api_exposes_dependency_and_validates_install_request(self):
        class Bridge:
            def krea_identity_dependency(self):
                return {"id": identity.KREA_IDENTITY_DEPENDENCY_ID, "ready": False}

            def install_krea_identity_dependency(self):
                return {"id": identity.KREA_IDENTITY_DEPENDENCY_ID, "installed": True}

        api = server.StableAmdApi(Bridge())
        status, payload = api.dispatch("GET", "/api/krea-identity/dependency")
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], identity.KREA_IDENTITY_DEPENDENCY_ID)

        status, payload = api.dispatch("POST", "/api/krea-identity/install", b"{}")
        self.assertEqual(status, 200)
        self.assertTrue(payload["installed"])

        status, payload = api.dispatch(
            "POST",
            "/api/krea-identity/install",
            b'{"id":"krea2-identity-edit-v1.2"}',
        )
        self.assertEqual(status, 200)

        status, payload = api.dispatch(
            "POST",
            "/api/krea-identity/install",
            b'{"id":"wrong"}',
        )
        self.assertEqual(status, 400)
        self.assertIn("krea2-identity-edit-v1.2", payload["error"])

        status, payload = api.dispatch(
            "POST",
            "/api/krea-identity/install",
            b'{"unexpected":true}',
        )
        self.assertEqual(status, 400)
        self.assertIn("Unsupported", payload["error"])


if __name__ == "__main__":
    unittest.main()
