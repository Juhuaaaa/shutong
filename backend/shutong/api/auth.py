"""Single-user password login: scrypt hash in settings, an HMAC-signed session cookie."""
import hashlib
import hmac
import secrets
import time
from typing import Optional

from fastapi import HTTPException, Request, WebSocket

from shutong.store.db import Database
from shutong.store.settings import SettingsStore

COOKIE = "shutong_session"
SESSION_SECONDS = 30 * 86400
MIN_PASSWORD = 8
_HASH_KEY = "auth.password_hash"
_SECRET_KEY = "auth.session_secret"


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt${0}${1}".format(salt.hex(), digest.hex())


def check_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, _ = stored.split("$")
    except (AttributeError, ValueError):
        return False
    return scheme == "scrypt" and hmac.compare_digest(hash_password(password, bytes.fromhex(salt)), stored)


class Auth:
    def __init__(self, db: Database) -> None:
        self.settings = SettingsStore(db)
        if not self.settings.get(_SECRET_KEY, None):
            self.settings.set(_SECRET_KEY, secrets.token_hex(32))

    @property
    def configured(self) -> bool:
        return bool(self.settings.get(_HASH_KEY, None))

    def set_password(self, password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise HTTPException(422, "密码至少 {0} 位".format(MIN_PASSWORD))
        self.settings.set(_HASH_KEY, hash_password(password))

    def verify(self, password: str) -> bool:
        return check_password(password, self.settings.get(_HASH_KEY, None) or "")

    def issue(self) -> str:
        expiry = str(int(time.time()) + SESSION_SECONDS)
        return "{0}.{1}".format(expiry, self._sign(expiry))

    def valid(self, token: Optional[str]) -> bool:
        if not token or "." not in token or not self.configured:
            return False
        expiry, signature = token.split(".", 1)
        if not expiry.isdigit() or int(expiry) < time.time():
            return False
        return hmac.compare_digest(signature, self._sign(expiry))

    def _sign(self, value: str) -> str:
        secret = self.settings.get(_SECRET_KEY).encode("ascii")
        return hmac.new(secret, value.encode("ascii"), hashlib.sha256).hexdigest()


def require_login(request: Request) -> None:
    if not request.app.state.auth.valid(request.cookies.get(COOKIE)):
        raise HTTPException(401, "未登录")


def websocket_logged_in(websocket: WebSocket) -> bool:
    return websocket.app.state.auth.valid(websocket.cookies.get(COOKIE))
