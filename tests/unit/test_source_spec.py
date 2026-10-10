import pytest

from app.camera.infrastructure.source_spec import SourceKind, parse_source
from app.core.exceptions import DomainValidationError


@pytest.mark.parametrize("raw,kind,value", [
    (0, SourceKind.WEBCAM, "0"),
    ("1", SourceKind.WEBCAM, "1"),
    ("rtsp://192.168.1.20:8080/live", SourceKind.STREAM, "rtsp://192.168.1.20:8080/live"),
    ("http://10.0.0.5:8080/video", SourceKind.STREAM, "http://10.0.0.5:8080/video"),
    (r"C:\Users\me\My Videos\beach 01.mp4", SourceKind.FILE, r"C:\Users\me\My Videos\beach 01.mp4"),
    ('"C:\\clips\\beach.mp4"', SourceKind.FILE, "C:\\clips\\beach.mp4"),  # quotes pasted from Explorer "Copy as path"
    ("C:/clips/beach.mp4", SourceKind.FILE, "C:/clips/beach.mp4"),
    (r"\\nas\share\beach.mp4", SourceKind.FILE, r"\\nas\share\beach.mp4"),  # UNC
    ("file:///C:/clips/beach.mp4", SourceKind.FILE, "C:/clips/beach.mp4"),
    ("clips/beach.mp4", SourceKind.FILE, "clips/beach.mp4"),
])
def test_parse(raw, kind, value):
    spec = parse_source(raw)
    assert spec.kind is kind and spec.value == value


def test_windows_drive_letter_is_not_a_url_scheme():
    assert parse_source(r"D:\footage\a.mp4").kind is SourceKind.FILE


def test_env_vars_expand(monkeypatch):
    monkeypatch.setenv("OE_CLIPS", "/data/clips")
    assert parse_source("$OE_CLIPS/a.mp4").value == "/data/clips/a.mp4"


@pytest.mark.parametrize("bad", ["", "   ", "ftp://x/y", -1])
def test_rejects_bad(bad):
    with pytest.raises(DomainValidationError):
        parse_source(bad)


def test_display_name_is_filesystem_safe_and_hides_credentials():
    assert parse_source(r"C:\a b\Beach (1).mp4").display_name == "Beach__1_"
    assert parse_source("rtsp://user:secret@10.0.0.1/live").display_name == "stream"
    assert parse_source(2).display_name == "webcam2"
