"""Kommandozeile: `python -m ramsuche lauf | liste | meldung-test` (aus dem Projektordner)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import dotenv_values

from ramsuche import bot
from tradingbot.notify import Notifier


def _werte(env_file: str) -> dict:
    return dict(dotenv_values(env_file)) if Path(env_file).exists() else {}


def _notifier(werte: dict, ersatz_env: str) -> Notifier:
    """ntfy-Thema aus ramsuche.env, sonst das schon abonnierte aus copilot.env."""
    topic, server = werte.get("NTFY_TOPIC"), werte.get("NTFY_SERVER")
    if not topic:
        ersatz = _werte(ersatz_env)
        topic, server = ersatz.get("NTFY_TOPIC"), server or ersatz.get("NTFY_SERVER")
    return Notifier(topic, server or "https://ntfy.sh")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ramsuche", description="Sucht günstigen DDR5-RAM auf Kleinanzeigen und eBay.")
    p.add_argument("--env", default="ramsuche.env", help="Einstellungen (Vorlage ramsuche.env.example)")
    p.add_argument("--ntfy-ersatz", default="copilot.env", help="ntfy-Thema von hier, wenn ramsuche.env keins hat")
    p.add_argument("--db", default=str(bot.DB_PATH))
    sub = p.add_subparsers(dest="befehl", required=True)
    lauf = sub.add_parser("lauf", help="Ein Suchlauf (für den Timer alle 15 Minuten).")
    lauf.add_argument("--still", action="store_true", help="Nichts aufs Handy senden, nur anzeigen.")
    sub.add_parser("liste", help="Marktpreise und die günstigsten passenden Anzeigen anzeigen.")
    sub.add_parser("meldung-test", help="Testnachricht ans Handy.")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    werte = _werte(args.env)
    notifier = _notifier(werte, args.ntfy_ersatz)

    if args.befehl == "meldung-test":
        if not notifier.enabled:
            print("Kein NTFY_TOPIC (weder in ramsuche.env noch in copilot.env).")
            return 1
        ok = notifier.send("RAM-Suche: Test", "Benachrichtigungen der RAM-Suche kommen an.")
        print("gesendet" if ok else "Senden fehlgeschlagen")
        return 0 if ok else 1

    db = bot.verbinden(args.db)
    try:
        if args.befehl == "liste":
            print(bot.liste(db))
            return 0
        cfg = bot.Einstellungen.aus_env(werte)
        if args.still:
            notifier = Notifier(None)
        treffer = bot.lauf(db, bot.quellen_aus_env(werte, cfg), cfg, notifier)
        print(f"{len(treffer)} neue Schnäppchen" + ("" if notifier.enabled else " (ohne Handy-Meldung)"))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
