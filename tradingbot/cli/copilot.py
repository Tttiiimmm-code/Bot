"""Befehl copilot und seine Unterbefehle (scan, buy, status, close, watch, report, ...)."""
from __future__ import annotations


def cmd_copilot(args):
    """Trading-Copilot (tradingbot/copilot.py) auf einem EIGENEN Paper-Konto."""
    import time as _time
    from datetime import datetime, timezone
    from pathlib import Path

    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.trading.client import TradingClient

    from tradingbot.copilot import Copilot, CopilotRules
    from tradingbot.report import read_account_env

    if not Path(args.env_file).exists():
        raise RuntimeError(
            f"{args.env_file} nicht gefunden. Der Copilot braucht ein EIGENES Alpaca-Paper-Konto "
            "(der Momentum-Bot stellt fremde Positionen glatt): ALPACA_API_KEY, ALPACA_SECRET_KEY, "
            "ALPACA_PAPER=true dort eintragen."
        )
    key, secret, paper = read_account_env(args.env_file)
    if not paper:
        raise RuntimeError("Der Copilot ist nur für Paper-Trading gedacht (ALPACA_PAPER=true setzen).")
    rules = CopilotRules(risk_per_trade=args.risk, max_daily_loss=args.max_daily_loss,
                         max_trades_per_day=args.max_trades)
    cp = Copilot(TradingClient(key, secret, paper=True), StockHistoricalDataClient(key, secret), rules,
                 Path(args.journal))
    now = datetime.now(timezone.utc)
    sub = args.copilot_command
    if sub == "scan":
        from types import SimpleNamespace

        from tradingbot.scanner import ScanCriteria, Scanner

        criteria = ScanCriteria(min_price=args.min_price, max_price=args.max_price,
                                min_percent_change=args.min_change, min_relative_volume=args.min_relvol)
        found = Scanner(SimpleNamespace(api_key=key, secret_key=secret, paper=True)).scan(criteria)
        if not found:
            print("Keine Kandidaten mit diesen Kriterien.")
        for c in found:
            print(f"{c.symbol:6s} {c.price:8.2f} $ {c.percent_change:+7.1f} %  RelVol {c.relative_volume:5.1f}x")
    elif sub == "buy":
        print(cp.buy(args.symbol, args.stop, args.setup, now, target=args.target, note=args.note,
                     breakeven=args.breakeven))
    elif sub == "status":
        print(cp.status(now))
    elif sub == "close":
        print(cp.close(None if args.symbol.lower() == "all" else args.symbol))
    elif sub == "weekly":
        from tradingbot.weekly_report import build_weekly

        title, text = build_weekly(cp, now)
        print(title)
        print(text)
    elif sub == "notify-test":
        from tradingbot.notify import notifier_from_env

        n = notifier_from_env(args.env_file)
        if not n.enabled:
            print("NTFY_TOPIC fehlt in der .env-Datei -- Benachrichtigungen sind aus.")
        else:
            ok = n.send("Copilot: Test", "Wenn du das liest, kommen die Benachrichtigungen an.", "default", "bell")
            print("Testnachricht gesendet." if ok else "Senden fehlgeschlagen (Netz/Server?).")
    elif sub == "watch":
        import threading

        from tradingbot.notify import CopilotAlerts, notifier_from_env
        from tradingbot.orb_scanner import CUTOFF_ET, READY_ET, orb_setups
        from tradingbot.orb_scanner import NY as NY_TZ
        from tradingbot.weekly_report import build_weekly

        print("Copilot-Überwachung läuft (Strg+C beendet): Tagesverlustgrenze, Glattstellen 15:55 ET, "
              "Stop auf Einstand bei +1 R (wenn beim Kauf gewählt).")
        alerts = CopilotAlerts(notifier_from_env(args.env_file))
        if alerts.notifier.enabled:
            print("Handy-Benachrichtigungen (ntfy) an: Setup-Melder und Positionen.")

            def melder_loop():
                # Eigener Thread: das erste Laden des Tages dauert Minuten und darf die Sicherheit nicht aufhalten
                while True:
                    try:
                        t = datetime.now(timezone.utc)
                        et = t.astimezone(NY_TZ)
                        if READY_ET <= et.time() <= CUTOFF_ET and cp.trading_client.get_clock().is_open:
                            for m in alerts.melder_step(t, orb_setups(cp, t)):
                                print(f"[Melder] {m}")
                    except Exception as e:  # Netzfehler o.ä.: nächster Versuch
                        print(f"Fehler im Setup-Melder (nächster Versuch in 5 Min.): {e}")
                    _time.sleep(300)

            threading.Thread(target=melder_loop, daemon=True, name="melder").start()
        else:
            print("Handy-Benachrichtigungen aus (NTFY_TOPIC in copilot.env eintragen, um sie einzuschalten).")
        last_status = 0.0
        while True:
            try:
                now = datetime.now(timezone.utc)
                msg = cp.watch_step(now)
                if msg:
                    print(msg)
                if alerts.notifier.enabled:
                    open_syms = {p.symbol for p in cp.trading_client.get_all_positions()}
                    alerts.positions_step(now, open_syms, msg, lambda: cp.state(now).realized_pnl)
                    for m in alerts.weekly_step(now, lambda: build_weekly(cp, now)):
                        print(f"{m} gesendet.")
                if _time.time() - last_status > 300:
                    print(cp.status(now))
                    last_status = _time.time()
            except KeyboardInterrupt:
                break
            except Exception as e:  # Netzfehler o.ä.: weiter überwachen
                print(f"Fehler in der Überwachung (nächster Versuch in 20 s): {e}")
            _time.sleep(20)
    elif sub == "report":
        print(cp.report(now, args.days))
