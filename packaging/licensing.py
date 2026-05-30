"""Machine-locked license verification — Ed25519 offline signatures."""
from __future__ import annotations

import base64
import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path

# Ed25519 public key (raw 32 bytes, base64-encoded).
# The matching private key stays with the developer — never commit it.
_PUBLIC_KEY_B64 = "XMrbv2YVIQXcIbjRgUbNrIxMsjnjc+dxQULvhfbpTpA="

# Update this once your license server is deployed on Railway.
LICENSE_SERVER_URL = "https://grain-scanner-license.up.railway.app"


def get_machine_id() -> str:
    """Return a stable 24-char hardware fingerprint for this machine."""
    parts: list[str] = []

    # MAC-address-based node id (stdlib, cross-platform)
    import uuid
    parts.append(str(uuid.getnode()))

    if platform.system() == "Windows":
        # Windows hardware UUID via WMI
        try:
            result = subprocess.run(
                ["wmic", "csproduct", "get", "UUID"],
                capture_output=True, text=True, timeout=5,
            )
            lines = [l.strip() for l in result.stdout.splitlines()
                     if l.strip() and l.strip() != "UUID"]
            if lines:
                parts.append(lines[0])
        except Exception:
            pass

        # Volume serial of the system drive
        try:
            result = subprocess.run(
                ["vol", "C:"],
                capture_output=True, text=True, shell=True, timeout=5,
            )
            parts.append(result.stdout.strip())
        except Exception:
            pass

    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:24].upper()


def verify_license(machine_id: str, license_key: str) -> bool:
    """Return True if *license_key* is a valid Ed25519 signature for *machine_id*."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature

        pub_bytes = base64.b64decode(_PUBLIC_KEY_B64)
        public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        signature = base64.b64decode(license_key)
        public_key.verify(signature, machine_id.encode())
        return True
    except Exception:
        return False


def _license_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("APPDATA", "~")).expanduser() / "GrainScanner"
    else:
        base = Path(__file__).parent
    base.mkdir(parents=True, exist_ok=True)
    return base / "license.key"


def load_license() -> str | None:
    p = _license_path()
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def save_license(license_key: str) -> None:
    _license_path().write_text(license_key.strip(), encoding="utf-8")


def check_license() -> None:
    """Raise LicenseError if no valid license is found for this machine."""
    machine_id = get_machine_id()
    key = load_license()
    if key and verify_license(machine_id, key):
        return
    raise LicenseError(machine_id)


def activate_with_coupon(machine_id: str, coupon_code: str) -> str:
    """Call the license server, validate the coupon, and return the license key.

    Raises ActivationError on any failure (invalid coupon, network error, etc.).
    """
    import urllib.request
    import urllib.error
    import json

    payload = json.dumps({
        "machine_id": machine_id,
        "coupon_code": coupon_code,
    }).encode()

    req = urllib.request.Request(
        f"{LICENSE_SERVER_URL}/activate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            return body["license_key"]
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        raise ActivationError(detail) from exc
    except Exception as exc:
        raise ActivationError(
            "Could not reach the license server.\nCheck your internet connection and try again."
        ) from exc


class LicenseError(Exception):
    def __init__(self, machine_id: str) -> None:
        self.machine_id = machine_id
        super().__init__(f"No valid license for machine {machine_id}")


class ActivationError(Exception):
    pass
