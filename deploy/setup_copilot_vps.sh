#!/usr/bin/env bash
# Copilot auf dem VPS einrichten (Oberfläche + Sicherheitsüberwachung), wiederholbar.
# Aufruf auf dem VPS:  cd /home/tradingbot/Bot && sudo bash deploy/setup_copilot_vps.sh
# Voraussetzung: copilot.env im Repo-Ordner (Paper-Konto des Copilot) mit
#   ALPACA_API_KEY=...  ALPACA_SECRET_KEY=...  ALPACA_PAPER=true  COPILOT_PASSWORD=<langes Passwort>
set -euo pipefail

BOT_USER=tradingbot
BOT_DIR=/home/$BOT_USER/Bot
cd "$BOT_DIR"

if [ "$(id -u)" -ne 0 ]; then echo "Bitte mit sudo ausführen."; exit 1; fi

echo "== 1/5 Code aktualisieren und Pakete installieren"
sudo -u "$BOT_USER" git pull --ff-only
sudo -u "$BOT_USER" .venv/bin/python -m pip install -q -r requirements-gui.txt

echo "== 2/5 copilot.env prüfen (Werte werden nicht angezeigt)"
if [ ! -f copilot.env ]; then
  echo "FEHLT: $BOT_DIR/copilot.env -- vom PC kopieren (siehe Anleitung) und Skript erneut starten."; exit 1
fi
for key in ALPACA_API_KEY ALPACA_SECRET_KEY COPILOT_PASSWORD; do
  grep -Eq "^${key}=.+" copilot.env || { echo "FEHLT in copilot.env: $key"; exit 1; }
done
grep -Eiq "^ALPACA_PAPER=true" copilot.env || { echo "copilot.env: ALPACA_PAPER=true fehlt (nur Paper erlaubt)"; exit 1; }
chown "$BOT_USER": copilot.env && chmod 600 copilot.env
[ -f copilot_journal.jsonl ] && chown "$BOT_USER": copilot_journal.jsonl

echo "== 3/5 Dienste installieren und starten"
cp deploy/copilot-gui.service deploy/copilot-watch.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now copilot-watch.service copilot-gui.service
sleep 5
systemctl --no-pager --lines=0 status copilot-watch.service copilot-gui.service || true

echo "== 4/5 Tailscale (nur eigene Geräte, nicht öffentlich)"
if ! command -v tailscale >/dev/null; then
  echo "Tailscale ist nicht installiert. Installieren mit:"
  echo "  curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
  echo "(den angezeigten Link im Browser öffnen und mit deinem Tailscale-Konto anmelden), dann Skript erneut starten."
  exit 1
fi
if ! tailscale status >/dev/null 2>&1; then
  echo "Tailscale ist nicht angemeldet: 'sudo tailscale up' ausführen, Link öffnen, dann Skript erneut starten."; exit 1
fi
tailscale serve --bg 8501

echo "== 5/5 Fertig. Adresse für Handy und PC (nur im eigenen Tailscale-Netz erreichbar):"
tailscale serve status
echo
echo "Auf dem PC in copilot.env eintragen:  COPILOT_VPS_URL=<obige https-Adresse>"
echo "Dann öffnet 'Copilot starten.bat' nur noch die VPS-Seite (ein Journal, eine Überwachung)."
