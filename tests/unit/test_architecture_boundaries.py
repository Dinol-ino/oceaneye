"""Executable architecture rules: enforces the dependency direction documented in docs/architecture.md."""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
FORBIDDEN_IN_CORE = {"fastapi", "starlette", "sqlalchemy", "pydantic", "pydantic_settings", "uvicorn", "cv2", "torch", "ultralytics"}


def imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def files(pkg: str):
    return [p for p in (APP / pkg).rglob("*.py")]


def test_core_is_framework_independent_and_depends_on_nothing_else():
    for p in files("core"):
        for name in imports(p):
            assert name.split(".")[0] not in FORBIDDEN_IN_CORE, f"{p}: {name}"
            if name.startswith("app."):
                assert name.startswith("app.core"), f"{p} imports {name}"


def test_domain_modules_do_not_import_api_or_infrastructure():
    banned = ("fastapi", "sqlalchemy", "starlette")
    for pkg in ("vision", "risk", "events/domain", "events/services", "alerts/services", "alerts/escalation",
                "alerts/notifications", "environment/zones", "environment/water_motion",
                "environment/external_data", "camera/domain", "camera/services", "evidence", "worker"):
        for p in files(pkg):
            if "/api/" in p.as_posix():
                continue
            for name in imports(p):
                assert not name.startswith(banned), f"{p} imports {name}"


def test_no_module_imports_persistence_models_except_persistence_and_main():
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).parts[0]
        if rel in ("persistence", "main"):
            continue
        for name in imports(p):
            assert not name.startswith("app.persistence"), f"{p} imports {name}"


def test_events_and_risk_do_not_know_alerts_or_websocket():
    for pkg in ("events", "risk", "vision"):
        for p in files(pkg):
            for name in imports(p):
                assert not name.startswith(("app.alerts", "app.websocket")), f"{p} imports {name}"


def test_alerts_do_not_import_websocket_module():
    for p in files("alerts"):
        for name in imports(p):
            assert not name.startswith("app.websocket"), f"{p} imports {name}"


def test_api_process_does_not_import_vision_or_risk_engines():
    for p in (APP / "main").rglob("*.py"):
        for name in imports(p):
            assert not name.startswith(("app.vision", "app.risk", "app.worker")), f"{p} imports {name}"


HEAVY = {"cv2", "numpy", "ultralytics", "torch"}
LAZY_ONLY = {"cv2", "ultralytics", "torch"}  # must be imported inside functions, never at module level
HEAVY_ALLOWED = {
    "camera/infrastructure/opencv_source.py", "vision/detection/yolo.py", "vision/tracking/bytetrack.py",
    "vision/devices.py", "vision/visualization/overlay.py", "vision/runner.py", "vision/media.py",
    "vision/pose/yolo_pose.py",
}


def test_heavy_libraries_only_in_allowlisted_vision_files_and_lazy_where_required():
    for p in APP.rglob("*.py"):
        rel = p.relative_to(APP).as_posix()
        tree = ast.parse(p.read_text(encoding="utf-8"))
        all_roots = {n.split(".")[0] for n in imports(p)}
        used = all_roots & HEAVY
        if used:
            assert rel in HEAVY_ALLOWED, f"{rel} imports {used}; allowed only in {sorted(HEAVY_ALLOWED)}"
        top_level = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                top_level |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top_level.add(node.module.split(".")[0])
        eager = top_level & LAZY_ONLY
        # overlay.py and runner.py are CV-only modules: importing them already means "vision extras installed"
        if rel not in {"vision/visualization/overlay.py", "vision/runner.py", "vision/media.py"}:
            assert not eager, f"{rel} imports {eager} at module level (must be lazy)"


def test_processing_core_is_framework_free_and_api_never_imports_cv():
    for name in ("service.py", "metrics.py", "live.py", "supervisor.py"):
        for imp in imports(APP / "processing" / name):
            assert not imp.startswith(("fastapi", "starlette", "sqlalchemy", "app.persistence")), f"{name} imports {imp}"
            assert imp.split(".")[0] not in HEAVY and not imp.startswith(("app.vision", "app.worker")), f"{name} imports {imp}"
