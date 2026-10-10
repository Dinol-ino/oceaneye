"""Start OceanEye (API + the three web interfaces; it launches worker processes itself).

    python scripts/run_api.py            # this PC only   -> http://127.0.0.1:8000
    python scripts/run_api.py --lan      # phones on the same Wi-Fi can reach it
    python scripts/run_api.py --reload   # auto-reload while editing (stops running workers on reload)

TLS is used automatically when OCEANEYE_SSL_CERTFILE / _KEYFILE are set (see scripts/make_certs.py).
Phones need it for installable apps and background alerts.
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # allow running without installing

import uvicorn  # noqa: E402

from app.config.settings import get_settings  # noqa: E402
from app.shared.hardware import probe  # noqa: E402


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces (phones on the same network)")
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    host = "0.0.0.0" if args.lan else s.host
    scheme = "https" if s.tls_enabled else "http"
    hw = probe()

    ssl_args = {}
    if s.tls_enabled:
        for label, path in (("certificate", s.ssl_certfile), ("private key", s.ssl_keyfile)):
            if not Path(path).is_file():
                print(f"\n  TLS {label} not found: {path}\n  Run: python scripts/make_certs.py\n", file=sys.stderr)
                return 1
        ssl_args = {"ssl_certfile": str(s.ssl_certfile), "ssl_keyfile": str(s.ssl_keyfile)}

    print(f"\n  OceanEye {s.app_version}")
    print(f"  Machine        {hw.describe()}  ->  {s.max_workers} worker slot(s)")
    print(f"  Control Room   {scheme}://127.0.0.1:{s.port}/ui/control.html   (this PC)")
    if args.lan:
        ip = lan_ip()
        print(f"  Lifeguard app  {scheme}://{ip}:{s.port}/ui/lifeguard.html   (phone, same Wi-Fi)")
    if not s.tls_enabled:
        print("\n  Running over plain HTTP: phones can use the pages, but cannot install them to the")
        print("  home screen and will not get alerts while the app is closed.")
        print("  To enable both:  python scripts/make_certs.py   (then add the two lines to .env)")
    elif not s.push_enabled:
        print("\n  HTTPS is on. For alerts that reach a closed app, also run:")
        print("  python scripts/make_push_keys.py")
    print("\n  Windows may ask to allow Python through the firewall - allow it on private networks.")
    print("  Stop with Ctrl+C (worker processes are stopped too).\n")

    uvicorn.run("app.main.asgi:app", host=host, port=s.port, reload=args.reload,
                app_dir=str(ROOT), **ssl_args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
