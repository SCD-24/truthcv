"""Generate a Fernet ENCRYPTION_KEY.

Usage:  python -m api.genkey
Copy the printed value into ENCRYPTION_KEY in your .env.
"""

from __future__ import annotations


def generate() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("utf-8")


if __name__ == "__main__":  # pragma: no cover
    print(generate())
