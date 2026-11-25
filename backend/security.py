import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _fernet(secret: str):
    if not secret:
        return None
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"trimiq-live-stream-key",
        iterations=390000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    return Fernet(key)


def encrypt_secret(value: str, secret: str) -> str:
    cipher = _fernet(secret)
    if cipher is None:
        raise RuntimeError("KEY_ENCRYPTION_KEY is required")
    return cipher.encrypt(value.encode()).decode()


def decrypt_secret(value: str, secret: str) -> str:
    cipher = _fernet(secret)
    if cipher is None:
        raise RuntimeError("KEY_ENCRYPTION_KEY is required")
    return cipher.decrypt(value.encode()).decode()
