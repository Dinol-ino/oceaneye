from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Short prefixed identifier, e.g. ``evt_3f9a1c0b7d2e`` (format mirrors the reference's evt_/cam_/trk_ ids)."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
