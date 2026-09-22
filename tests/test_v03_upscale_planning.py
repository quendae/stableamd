import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "app" / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import upscale_support


class StableAmdUpscalePlanningTests(unittest.TestCase):
    def test_prefers_single_native_model_for_exact_factor(self):
        models = ["RealESRGAN_x2plus.pth", "4x-UltraSharp.pth"]
        self.assertEqual(
            upscale_support.plan_upscale_chain(models, 4),
            ["4x-UltraSharp.pth"],
        )

    def test_chains_x2_model_for_4x_and_8x(self):
        models = ["RealESRGAN_x2plus.pth"]
        self.assertEqual(
            upscale_support.plan_upscale_chain(models, 4),
            ["RealESRGAN_x2plus.pth", "RealESRGAN_x2plus.pth"],
        )
        self.assertEqual(
            upscale_support.plan_upscale_chain(models, 8),
            ["RealESRGAN_x2plus.pth", "RealESRGAN_x2plus.pth", "RealESRGAN_x2plus.pth"],
        )

    def test_uses_4x_plus_2x_for_8x_when_available(self):
        models = ["RealESRGAN_x2plus.pth", "4x-UltraSharp.pth"]
        plan = upscale_support.plan_upscale_chain(models, 8)
        self.assertEqual(len(plan), 2)
        self.assertEqual(
            sorted(upscale_support.infer_upscale_scale(item) for item in plan),
            [2, 4],
        )

    def test_rejects_factor_that_cannot_be_reached_exactly(self):
        with self.assertRaisesRegex(ValueError, "exact 8x"):
            upscale_support.plan_upscale_chain(["4x-UltraSharp.pth"], 8)

    def test_preferred_model_is_used_when_it_can_reach_target(self):
        models = ["RealESRGAN_x2plus.pth", "4x-UltraSharp.pth"]
        self.assertEqual(
            upscale_support.plan_upscale_chain(models, 4, preferred_model="RealESRGAN_x2plus.pth"),
            ["RealESRGAN_x2plus.pth", "RealESRGAN_x2plus.pth"],
        )


if __name__ == "__main__":
    unittest.main()
