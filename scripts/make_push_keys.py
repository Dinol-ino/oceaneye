"""Generate the VAPID key pair that background phone alerts (Web Push) need.

    python scripts/make_push_keys.py

Writes the private key to ``data/vapid_private.pem`` (never commit it) and prints the two lines to
paste into ``.env``. Run once per installation; regenerating invalidates every phone subscription, so
lifeguards would have to tap "Turn on alerts" again.

Why a key pair at all: the browser's push service will only accept messages from a server that can
prove it is the same one the browser subscribed to (RFC 8292). The public key goes to the browser,
the private key signs each push, and nothing but this server can wake those phones.
"""
from __future__ import annotations

import argparse
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEY_PATH = ROOT / "data" / "vapid_private.pem"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(DEFAULT_KEY_PATH), help="where to write the private key PEM")
    ap.add_argument("--subject", default="mailto:oceaneye@example.invalid",
                    help="contact the push service can reach you at (mailto: or https:)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing key")
    args = ap.parse_args(argv)

    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        print("This needs the push extra:  pip install -e \".[push]\"", file=sys.stderr)
        return 2

    out = Path(args.out)
    if out.exists() and not args.force:
        print(f"{out} already exists. Use --force to replace it (this invalidates every phone "
              f"subscription).", file=sys.stderr)
        return 1

    private = ec.generate_private_key(ec.SECP256R1())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:
        out.chmod(0o600)  # best effort; Windows ignores POSIX modes
    except OSError:
        pass

    # The browser needs the public key as the uncompressed EC point, base64url without padding.
    public_point = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    print(f"\nPrivate key written to: {out}")
    print("Keep it out of version control - data/ is already git-ignored.\n")
    print("Add these to .env (and add web_push to OCEANEYE_NOTIFICATION_CHANNELS):\n")
    print(f"OCEANEYE_VAPID_PUBLIC_KEY={b64url(public_point)}")
    print(f"OCEANEYE_VAPID_PRIVATE_KEY={out.as_posix()}")
    print(f"OCEANEYE_VAPID_SUBJECT={args.subject}")
    print("OCEANEYE_NOTIFICATION_CHANNELS=websocket,mock,web_push\n")
    print("Background alerts also need HTTPS - run scripts/make_certs.py if you have not already.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
