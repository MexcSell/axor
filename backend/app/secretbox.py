"""Encrypted storage for server secrets (e.g. the Claude API key) set from the UI.

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under a key kept in DATA_DIR/secret.key
(created on first use, file mode 0600) or supplied as SECRET_KEY. Secrets never leave the server:
the API only ever returns a masked form.
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

class SecretBox:
    def __init__(self, db, data_dir):
        self.db = db
        key = os.getenv("SECRET_KEY")
        if not key:
            path = Path(data_dir) / "secret.key"
            if not path.exists():
                path.write_bytes(Fernet.generate_key())
                os.chmod(path, 0o600)
            key = path.read_bytes().strip()
        self.f = Fernet(key)

    def get(self, name):
        v = self.db.setting("secret:" + name)
        if not v: return None
        try: return self.f.decrypt(v.encode()).decode()
        except InvalidToken: return None  # secret.key changed: treat as unset

    def set(self, name, value):
        self.db.setting("secret:" + name, v=self.f.encrypt(value.encode()).decode())

    def delete(self, name):
        self.db.q("DELETE FROM app_settings WHERE k=?", ("secret:" + name,))

def fingerprint(key):
    """A key's audit name: sha256 of the whole key, 12 hex characters. Tells two keys apart; reveals none of either."""
    import hashlib
    return None if not key else "sha256:" + hashlib.sha256(str(key).encode()).hexdigest()[:12]


def mask(key):
    return None if not key else f"{key[:7]}…{key[-4:]}" if len(key) > 14 else "••••"
