"""Domain enumerations. Framework-independent."""
from enum import Enum


class EventStatus(str, Enum):
    """Event lifecycle states documented in the OceanEye reference (section 7)."""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    FALSE_ALARM = "false_alarm"


class RiskLevel(str, Enum):
    """PROPOSED SCAFFOLD: coarse labels. Score->level mapping belongs to the risk engine."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DistressSignalType(str, Enum):
    """Distress signatures listed in the OceanEye reference (section 2, objective 3)."""

    ERRATIC_MOVEMENT = "erratic_movement"
    VERTICAL_BOBBING = "vertical_bobbing"
    PROLONGED_STILLNESS = "prolonged_stillness"
    REPEATED_SUBMERSION = "repeated_submersion"
    ARMS_RAISED = "arms_raised"
    #: Torso upright in the water while making no headway. Swimming is horizontal; the instinctive
    #: drowning response is vertical. Needs a pose model - see app.vision.pose.yolo_pose.
    VERTICAL_IN_WATER = "vertical_in_water"


class Role(str, Enum):
    """operator / lifeguard / administrator per the brief.

    PROPOSED SCAFFOLD: ``service`` identifies the separate vision/risk process that
    raises candidate events via POST /api/events (the reference requires it to be a
    separate process).
    """

    OPERATOR = "operator"
    LIFEGUARD = "lifeguard"
    ADMINISTRATOR = "administrator"
    SERVICE = "service"


class CameraSourceType(str, Enum):
    RTSP = "rtsp"
    IP_CCTV = "ip_cctv"
    MOBILE_TEST = "mobile_test"  # phone as RTSP camera / browser getUserMedia
    VIDEO_FILE = "video_file"  # recorded footage (reference roadmap: pilot footage / test path)
    WEBCAM = "webcam"  # local webcam index
    MOCK = "mock"


class CameraStatus(str, Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"


class ZoneMode(str, Enum):
    STATIC = "static"  # manually configured polygon (first prototype)
    DYNAMIC = "dynamic"  # FUTURE: water-motion / environment driven


class NotificationChannel(str, Enum):
    WEBSOCKET = "websocket"
    WEB_PUSH = "web_push"  # boundary only
    SMS = "sms"  # boundary only
    MOCK = "mock"


class DeliveryStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class AlertNotificationType(str, Enum):
    CREATED = "alert.created"
    ACKNOWLEDGED = "alert.acknowledged"
    ESCALATED = "alert.escalated"
    CLOSED = "alert.closed"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
