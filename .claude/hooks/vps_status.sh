#!/usr/bin/env bash
# SessionStart-Hook: VPS-Zustand (main.py health --check, nur lesend) in den Kontext der Claude-Sitzung.
out=$(ssh -o ConnectTimeout=8 -o BatchMode=yes root@116.203.115.99 \
    'cd /home/tradingbot/Bot && timeout 40 .venv/bin/python main.py health --check' 2>&1) \
    || out="VPS-Prüfung fehlgeschlagen (VPS nicht erreichbar oder Fehler): ${out:0:300}"
echo "$out"
echo "Bei Problemen: dem Nutzer zuerst davon berichten."
