@echo off
title MT5 auf dem VPS (SSH-Tunnel)
echo ============================================================
echo   MetaTrader 5 auf dem VPS anzeigen
echo ============================================================
echo.
echo Der Browser oeffnet gleich den MT5-Bildschirm des VPS.
echo Dieses Fenster OFFEN lassen, solange du MT5 bedienst.
echo Zum Beenden: dieses Fenster schliessen (MT5 laeuft auf dem VPS weiter).
echo.
start "" cmd /c "timeout /t 4 >nul & start http://localhost:6080/vnc.html?autoconnect=true^&resize=scale"
"%SystemRoot%\System32\OpenSSH\ssh.exe" -N -o ExitOnForwardFailure=yes -L 6080:127.0.0.1:6080 root@116.203.115.99
echo.
echo Verbindung beendet.
pause
