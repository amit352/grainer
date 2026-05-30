"""
Developer tool — generate license keys for specific machine IDs.

Usage:
    # Step 1 (one-time): generate keypair
    python packaging/keygen.py --generate-keys

    # Step 2: generate a license for a customer machine
    python packaging/keygen.py --machine-id ABCD1234EFGH5678IJKL9012 --private-key <base64>

The private key must be kept secret. The public key is already embedded in
packaging/licensing.py. Do NOT commit the private key to source control.
"""
from __future__ import annotations

import argparse
import base64
import sys


def cmd_generate_keys() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption,
    )

    priv = Ed25519PrivateKey.generate()
    pub  = priv.public_key()

    priv_b64 = base64.b64encode(priv.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
    pub_b64  = base64.b64encode(pub.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()

    print("=" * 60)
    print("PRIVATE KEY — keep this secret, never commit to git:")
    print(priv_b64)
    print()
    print("PUBLIC KEY — embed in packaging/licensing.py:")
    print(pub_b64)
    print("=" * 60)


def cmd_generate_license(machine_id: str, private_key_b64: str) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

    priv_bytes = base64.b64decode(private_key_b64)
    priv = Ed25519PrivateKey.from_private_bytes(priv_bytes)
    signature = priv.sign(machine_id.upper().encode())
    license_key = base64.b64encode(signature).decode()

    print(f"Machine ID   : {machine_id.upper()}")
    print(f"License key  : {license_key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Grain Scanner license key generator")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate-keys", action="store_true",
                       help="Generate a new Ed25519 keypair")
    group.add_argument("--machine-id", metavar="ID",
                       help="Machine ID to issue a license for")

    parser.add_argument("--private-key", metavar="B64",
                        help="Base64-encoded private key (required with --machine-id)")

    args = parser.parse_args()

    if args.generate_keys:
        cmd_generate_keys()
    else:
        if not args.private_key:
            parser.error("--private-key is required when using --machine-id")
        cmd_generate_license(args.machine_id, args.private_key)


if __name__ == "__main__":
    main()
