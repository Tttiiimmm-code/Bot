"""Angemeldet bleiben in der Copilot-Oberfläche: nach richtiger Passworteingabe ein Cookie (30 Tage).

Im Cookie steht nicht das Passwort, sondern ein daraus abgeleiteter Prüfwert (HMAC). Wird COPILOT_PASSWORD geändert,
passt der Prüfwert nicht mehr -- alle gespeicherten Anmeldungen sind dann ungültig. Gesetzt wird das Cookie per
Skript im Browser (Streamlit kann Cookies nur lesen); über https (Tailscale) mit Secure-Flag.
"""

from __future__ import annotations

import hashlib
import hmac

COOKIE = "copilot_auth"
DAYS = 30


def login_token(password: str) -> str:
    return hmac.new(password.encode(), b"copilot-login-v1", hashlib.sha256).hexdigest()


def cookie_ok(cookie: str | None, password: str) -> bool:
    if not isinstance(cookie, str) or not cookie or not password:
        return False
    return hmac.compare_digest(cookie, login_token(password))


def set_cookie_js(token: str, days: int = DAYS) -> str:
    return ("<script>(function(){var s=window.parent.location.protocol==='https:'?'; Secure':'';"
            f"window.parent.document.cookie='{COOKIE}={token}; Max-Age={days * 86400}; Path=/; SameSite=Strict'+s;"
            "})();</script>")


def clear_cookie_js() -> str:
    return f"<script>window.parent.document.cookie='{COOKIE}=; Max-Age=0; Path=/; SameSite=Strict';</script>"
