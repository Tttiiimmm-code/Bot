#!/bin/sh
# Nächtliche Sicherung der Daten, die nur auf dem VPS entstehen (keine Schlüssel/.env, keine neu ladbaren Caches).
# Der PC holt die Archive mit "VPS-Sicherung holen.bat" ab (Windows-Aufgabe, täglich).
set -eu
cd /home/tradingbot/Bot
DEST=/home/tradingbot/backups
mkdir -p "$DEST"
FILES=""
for f in copilot_journal.jsonl replay_journal.jsonl copilot_settings.json forward_trades.csv forward_orb.csv forward_quality.csv forward_smallvq.csv forward_gold.csv forward_pelosi.csv pelosi_bot_state.json pelosi_bot_trades.csv gold_live_trades.csv gold_live_state.json news_intel.csv \
         momentum_state.json overnight_state.json overnight_trades.csv data_cache/liquidations; do
  [ -e "$f" ] && FILES="$FILES $f"
done
# shellcheck disable=SC2086
tar -czf "$DEST/bot-data-$(date +%F).tar.gz" $FILES
find /home/tradingbot/Bot/data_cache/copilot_orb -mindepth 1 -maxdepth 1 -type d -mtime +3 -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name 'bot-data-*.tar.gz' -mtime +14 -delete
ls -la "$DEST" | tail -3
