@echo off
rem Holt die naechtlichen Sicherungsarchive vom VPS (nur fehlende) nach backups\ im Bot-Ordner.
cd /d "%~dp0"
if not exist backups mkdir backups
scp -q -o BatchMode=yes -o ConnectTimeout=20 root@116.203.115.99:/home/tradingbot/backups/bot-data-*.tar.gz backups\
if errorlevel 1 (echo Sicherung holen fehlgeschlagen & exit /b 1)
echo Sicherung aktuell:
dir /b backups
