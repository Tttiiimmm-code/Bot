#!/bin/sh
# Einrichtung MetaTrader 5 (GoldBreakout-EA, OANDA-Demo) unter Wine auf dem VPS -- als root, einmalig (2026-10-19).
# Der offizielle Installer meldet unter Wine/KVM fälschlich "A debugger has been found" -> stattdessen terminal64.exe
# vom PC kopieren und portabel (C:\MT5) betreiben. MT5 aktualisiert sich danach selbst (LiveUpdate).
# Anmeldung am Demokonto macht der Nutzer selbst über "MT5 VPS anzeigen.bat" (SSH-Tunnel + noVNC, nur 127.0.0.1).
set -eu
export DEBIAN_FRONTEND=noninteractive
dpkg --add-architecture i386
mkdir -pm755 /etc/apt/keyrings
wget -qO /etc/apt/keyrings/winehq-archive.key https://dl.winehq.org/wine-builds/winehq.key
wget -qNP /etc/apt/sources.list.d/ https://dl.winehq.org/wine-builds/ubuntu/dists/noble/winehq-noble.sources
apt-get update -qq
apt-get install -y -qq --install-recommends winehq-stable
apt-get install -y -qq xvfb x11vnc novnc websockify xdotool x11-apps imagemagick
id mt5 >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin mt5
usermod -aG mt5 tradingbot                      # backup-data liest gold_breakout_trades.csv
cp /home/tradingbot/Bot/deploy/mt5-display.service /home/tradingbot/Bot/deploy/mt5.service \
   /home/tradingbot/Bot/deploy/mt5-vnc.service /home/tradingbot/Bot/deploy/mt5-novnc.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mt5-display
sudo -u mt5 env HOME=/home/mt5 DISPLAY=:99 WINEPREFIX=/home/mt5/.wine WINEDLLOVERRIDES="mscoree,mshtml=" wineboot -i
sudo -u mt5 env HOME=/home/mt5 DISPLAY=:99 WINEPREFIX=/home/mt5/.wine wine winecfg /v win10
sudo -u mt5 mkdir -p /home/mt5/.wine/drive_c/MT5/MQL5/Experts /home/mt5/.wine/drive_c/MT5/MQL5/Profiles/Charts/GoldBreakout \
                     /home/mt5/.wine/drive_c/MT5/config
echo "Jetzt vom PC kopieren (scp) nach /home/mt5/.wine/drive_c/MT5/:"
echo "  terminal64.exe, Terminal.ico, Sounds/  (C:\\Program Files\\MetaTrader 5)"
echo "  MQL5/Experts/GoldBreakout.ex5, config/servers.dat, Chart mit EA als MQL5/Profiles/Charts/GoldBreakout/chart01.chr"
echo "  config/common.ini (UTF-16): Login, Server=OANDATMS-MT5, ProfileLast=GoldBreakout, [Experts] Enabled=1 Account=0 Profile=0"
echo "Danach: chown -R mt5:mt5 /home/mt5/.wine/drive_c/MT5 && systemctl enable --now mt5 mt5-vnc mt5-novnc"
