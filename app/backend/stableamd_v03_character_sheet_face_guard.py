from __future__ import annotations

from typing import Any

import stableamd_v03_character_sheet_face_refine as face_refine
import stableamd_v03_character_sheet_v2 as sheetv2


class CharacterSheetV2FacePanelGuardBridgeMixin:
    """Keep the FACE close-up on the stable first detail pass.

    Physical RX 6950 XT acceptance showed that the second tight-face pass can
    create duplicated/ghost facial features specifically in the already-large
    FACE panel. FRONT and THREE_QUARTER still benefit from the tight pass, so
    only FACE bypasses CharacterSheetV2FaceRefineBridgeMixin and delegates
    directly to the first-pass v2 detailer below it in the MRO.
    """

    def _refine_v2_panel(
        self,
        request: dict[str, Any],
        model: dict[str, Any],
        panel: sheetv2.CharacterSheetV2Panel,
        source: dict[str, Any],
    ) -> dict[str, Any]:
        role = str(panel.role or "").strip().lower()
        if role != "face":
            return super()._refine_v2_panel(request, model, panel, source)

        # Deliberately skip only CharacterSheetV2FaceRefineBridgeMixin. The
        # next implementation in the final MRO is the accepted first-pass v2
        # detailer, so FACE still receives identity correction once.
        first = super(face_refine.CharacterSheetV2FaceRefineBridgeMixin, self)._refine_v2_panel(
            request,
            model,
            panel,
            source,
        )
        result = dict(first)
        result["faceIdentityStatus"] = "skipped"
        result["faceIdentitySkipped"] = "close-up-panel"
        return result
