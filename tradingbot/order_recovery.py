"""Orders mit fester client_order_id: eine verlorene Antwort (Timeout nach Annahme) führt nicht zum Doppelkauf.

Alpaca lehnt eine zweite Order mit derselben client_order_id ab. Scheitert das Senden, wird deshalb per
client_order_id nachgeschlagen: existiert die Order, gilt sie als gesendet; sonst bleibt der Fehler bestehen und
der nächste Versuch sendet mit derselben ID erneut (ein Duplikat wird dann abgelehnt und wiedergefunden).
"""

from __future__ import annotations

import hashlib
import re


def client_order_id(*parts) -> str:
    """Deterministische ID aus den Teilen; nur Buchstaben, Ziffern, '-', '_' und höchstens 128 Zeichen."""
    raw = "-".join(str(p) for p in parts)
    clean = re.sub(r"[^A-Za-z0-9_-]", "-", raw)
    if clean != raw or len(clean) > 128:
        clean = clean[:95] + "-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return clean


def find_order(client, cid: str):
    """Order zur client_order_id oder None, wenn Alpaca sie sicher nicht kennt (404). Andere Fehler (Netz)
    werden weitergereicht -- dann ist unklar, ob die Order existiert."""
    try:
        return client.get_order_by_client_id(cid)
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "status_code", None) == 404 or "not found" in str(exc).lower():
            return None
        raise


def submit_once(client, request):
    """Sendet `request` (mit gesetzter client_order_id). Bei einem Fehler wird nachgeschlagen, ob Alpaca die
    Order trotzdem angenommen hat; nur dann gilt sie als gesendet."""
    try:
        return client.submit_order(request)
    except Exception:
        order = find_order(client, request.client_order_id)
        if order is not None:
            return order
        raise
