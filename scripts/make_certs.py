"""Generate a self-signed TLS certificate for the LAN, so phones get a secure origin.

    python scripts/make_certs.py

Browsers only allow service workers, the Notification API and the Push API on a *secure* origin.
``localhost`` counts as secure; ``http://192.168.1.20:8000`` does not - which is exactly the address a
lifeguard's phone uses. Without HTTPS the lifeguard app still works, but it cannot be installed to the
home screen and cannot receive an alert while closed.

This writes a certificate covering ``localhost``, ``127.0.0.1`` and this machine's LAN address, so the
same certificate works from the PC and from a phone on the same Wi-Fi.

It is **self-signed**: the first time a phone opens the address it shows a warning, and someone has to
tap through it once per device ("Advanced" -> "Proceed"). That is acceptable for a prototype on a
closed network. A real deployment uses a certificate from a certificate authority for a real hostname -
a self-signed certificate gives you encryption but no proof of identity, so it must not be treated as
production security.
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / "data" / "certs"
VALID_DAYS = 825  # the longest most browsers accept for a leaf certificate


def lan_ip() -> str:
    """This machine's address on the local network (no packet is actually sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(CERT_DIR), help="directory for cert.pem / key.pem")
    ap.add_argument("--host", action="append", default=[],
                    help="extra hostname or IP to cover (repeatable)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing certificate")
    args = ap.parse_args(argv)

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError:
        print("This needs the tls extra:  pip install -e \".[tls]\"", file=sys.stderr)
        return 2

    out = Path(args.out)
    cert_path, key_path = out / "cert.pem", out / "key.pem"
    if cert_path.exists() and not args.force:
        print(f"{cert_path} already exists. Use --force to replace it (every phone will have to accept "
              f"the new certificate once).", file=sys.stderr)
        return 1

    ip = lan_ip()
    names = ["localhost", ip, *args.host]
    alt: list[x509.GeneralName] = []
    for name in dict.fromkeys(names):      # de-duplicate, keep order
        try:
            alt.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            alt.append(x509.DNSName(name))
    alt.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "OceanEye prototype"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OceanEye (self-signed, not for production)"),
    ])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))  # tolerate a slightly slow phone clock
        .not_valid_after(now + dt.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    out.mkdir(parents=True, exist_ok=True)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    try:
        key_path.chmod(0o600)
    except OSError:
        pass

    print(f"\nCertificate: {cert_path}\nPrivate key: {key_path}")
    print(f"Covers: {', '.join(dict.fromkeys(names))}\n")
    print("Add these to .env:\n")
    print(f"OCEANEYE_SSL_CERTFILE={cert_path.as_posix()}")
    print(f"OCEANEYE_SSL_KEYFILE={key_path.as_posix()}\n")
    print("Then start with:  python scripts/run_api.py --lan")
    print(f"On a phone open:  https://{ip}:8000/ui/lifeguard.html")
    print("The phone will warn that the certificate is not trusted - tap Advanced, then Proceed. "
          "Once per device.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
