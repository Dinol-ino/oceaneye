from __future__ import annotations

from app.camera.domain.sources import CameraSource
from app.camera.infrastructure.mock_source import MockCameraSource
from app.camera.infrastructure.opencv_source import OpenCvCameraSource
from app.camera.infrastructure.source_spec import SourceKind, parse_source
from app.core.entities.camera import Camera
from app.core.enums import CameraSourceType
from app.core.exceptions import DomainValidationError

_OPENCV_TYPES = {
    CameraSourceType.RTSP: SourceKind.STREAM,
    CameraSourceType.IP_CCTV: SourceKind.STREAM,
    CameraSourceType.MOBILE_TEST: SourceKind.STREAM,
    CameraSourceType.VIDEO_FILE: SourceKind.FILE,
    CameraSourceType.WEBCAM: SourceKind.WEBCAM,
}


class CameraSourceFactory:
    """Maps a Camera to a CameraSource. Creating a source never connects; ``open()`` does."""

    def create(self, camera: Camera) -> CameraSource:
        if camera.source_type is CameraSourceType.MOCK:
            return MockCameraSource(camera.id)
        expected = _OPENCV_TYPES[camera.source_type]
        spec = parse_source(camera.stream_url)
        if spec.kind is not expected:
            raise DomainValidationError(
                f"camera source_type '{camera.source_type.value}' does not match stream_url kind '{spec.kind.value}'"
            )
        return OpenCvCameraSource(camera.id, camera.source_type, spec)
