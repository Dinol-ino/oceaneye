"""Interpret a user-supplied video source string (CLI / notebook / config).

Pure Python (no OpenCV), so it is unit-testable everywhere. Handles the Windows cases that bite in
practice: drive letters (``C:\\clips\\a.mp4`` is NOT a URL), spaces, UNC paths, pasted quotes,
``%USERPROFILE%`` style variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

from app.core.exceptions import DomainValidationError

STREAM_SCHEMES = ("rtsp", "rtsps", "rtmp", "http", "https")


class SourceKind(str, Enum):
    FILE = "file"
    WEBCAM = "webcam"
    STREAM = "stream"


@dataclass(frozen=True)
class SourceSpec:
    kind: SourceKind
    value: str  # file path, stream URL, or webcam index as a string

    @property
    def webcam_index(self) -> int:
        return int(self.value)

    @property
    def is_live(self) -> bool:
        return self.kind is not SourceKind.FILE

    @property
    def display_name(self) -> str:
        """Short, filesystem-safe label (used for run folder names). Never contains credentials."""
        if self.kind is SourceKind.WEBCAM:
            return f"webcam{self.value}"
        if self.kind is SourceKind.STREAM:
            return "stream"
        name = self.value.replace("\\", "/").rstrip("/").split("/")[-1]
        stem = name.rsplit(".", 1)[0] if "." in name else name
        safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)
        return safe or "video"


def parse_source(raw: "str | int") -> SourceSpec:
    if isinstance(raw, int):
        if raw < 0:
            raise DomainValidationError("webcam index must be >= 0")
        return SourceSpec(SourceKind.WEBCAM, str(raw))
    text = str(raw).strip().strip('"').strip("'").strip()
    if not text:
        raise DomainValidationError("video source is empty")
    if text.isdigit():
        return SourceSpec(SourceKind.WEBCAM, text)
    if "://" in text:  # a Windows drive letter ("C:\\") never contains "://"
        scheme = text.split("://", 1)[0].lower()
        if scheme in STREAM_SCHEMES:
            return SourceSpec(SourceKind.STREAM, text)
        if scheme == "file":
            text = text.split("://", 1)[1]
            if len(text) > 2 and text[0] == "/" and text[2] == ":":  # file:///C:/x -> C:/x
                text = text[1:]
        else:
            raise DomainValidationError(f"unsupported source scheme '{scheme}'")
    text = os.path.expanduser(os.path.expandvars(text))
    return SourceSpec(SourceKind.FILE, text)
