#!/usr/bin/env bash
# Deploy auf dem VPS, als root:   bash /home/tradingbot/Bot/deploy/deploy.sh [--jetzt]
#
# 1. git pull (als tradingbot), danach läuft die frisch geholte Fassung dieses Skripts weiter.
# 2. Geänderte Unit-Dateien aus deploy/ nach /etc/systemd/system kopieren (nur bereits installierte; neue Units
#    werden nur genannt -- ein neuer Bot wird bewusst von Hand aktiviert), daemon-reload, geänderte Timer neu laden.
# 3. requirements.txt geändert -> pip install.
# 4. Dauerdienste neu starten, deren Code oder Unit jünger ist als ihr Start. Handelnde Dienste nicht während der
#    US-Sitzung (Mo-Fr 15:20-22:10 deutsche Zeit), außer mit --jetzt; ein späterer Aufruf holt das nach.
#    mt5/mt5-display nur bei geänderter Unit. Timer-Läufe (forward-* usw.) nutzen den neuen Code automatisch.
# 5. Zustand ausgeben (main.py health --check).
set -euo pipefail

REPO=/home/tradingbot/Bot
UNITS=/etc/systemd/system
PY_SERVICES="momentum overnight liq-recorder copilot-watch copilot-gui pelosi-bot"
TRADING="momentum overnight copilot-watch copilot-gui pelosi-bot"      # nicht während der US-Sitzung
OTHER_SERVICES="mt5-display mt5"

[[ $EUID -eq 0 ]] || { echo "Bitte als root ausführen." >&2; exit 1; }
cd "$REPO"

if [[ "${1:-}" != "--nach-pull" ]]; then
    old=$(git rev-parse HEAD)
    sudo -u tradingbot git pull -q --ff-only
    exec bash "$REPO/deploy/deploy.sh" --nach-pull "$old" "$@"
fi
old=$2
shift 2
jetzt=0
[[ "${1:-}" == "--jetzt" ]] && jetzt=1

echo "Stand: $(git log --oneline -1)"
if [[ "$old" == "$(git rev-parse HEAD)" ]]; then
    echo "Keine neuen Commits."
else
    git log --oneline "$old..HEAD" | sed 's/^/  neu: /'
fi

# --- Unit-Dateien
reload=0
changed_units=""
for f in deploy/*.service deploy/*.timer; do
    dst="$UNITS/$(basename "$f")"
    [[ -e "$dst" ]] || continue
    if ! cmp -s "$f" "$dst"; then
        cp "$f" "$dst"
        reload=1
        changed_units="$changed_units $(basename "$f")"
        echo "Unit aktualisiert: $(basename "$f")"
    fi
done
for f in $(git diff --name-only --diff-filter=A "$old" HEAD -- deploy/ | grep -E '\.(service|timer)$' || true); do
    [[ -e "$UNITS/$(basename "$f")" ]] || echo "Neue Unit (nicht installiert): $f -- bei Bedarf kopieren und 'systemctl enable --now'"
done
if (( reload )); then
    systemctl daemon-reload
    for u in $changed_units; do
        if [[ "$u" == *.timer ]]; then
            systemctl restart "$u" && echo "Timer neu geladen: $u"
        fi
    done
fi

# --- Abhängigkeiten
if ! git diff --quiet "$old" HEAD -- requirements.txt; then
    echo "requirements.txt geändert -> pip install"
    sudo -u tradingbot .venv/bin/pip install -q -r requirements.txt
fi

# --- Dauerdienste
started() { systemctl show --timestamp=unix -p ActiveEnterTimestamp --value "$1" | tr -d '@'; }
code_mtime=$(git ls-files 'main.py' 'tradingbot/*.py' requirements.txt | xargs stat -c %Y | sort -n | tail -1)
now=$(TZ=Europe/Berlin date +%u%H%M)
session=0
if (( ${now:0:1} <= 5 && 10#${now:1} >= 1520 && 10#${now:1} <= 2210 )); then session=1; fi

restart() {
    local s=$1 st
    if (( session && ! jetzt )) && [[ " $TRADING " == *" $s "* ]]; then
        echo "NICHT neu gestartet (US-Sitzung): $s -- später erneut deploy.sh oder mit --jetzt"
        return
    fi
    systemctl restart "$s"
    sleep 3
    st=$(systemctl is-active "$s" || true)
    echo "Neu gestartet: $s -> $st"
    [[ "$st" == "active" ]] || echo "  Achtung: $s nicht aktiv (StartLimit? 'systemctl reset-failed $s')"
}

for s in $PY_SERVICES; do
    [[ "$(systemctl is-enabled "$s" 2>/dev/null || true)" == "enabled" ]] || continue
    t=$(started "$s")
    unit_mtime=$(stat -c %Y "$UNITS/$s.service")
    if [[ -z "$t" || "$t" -lt "$code_mtime" || "$t" -lt "$unit_mtime" ]]; then
        restart "$s"
    fi
done
for s in $OTHER_SERVICES; do
    if [[ " $changed_units " == *" $s.service "* ]]; then restart "$s"; fi
done

echo
.venv/bin/python main.py health --check
