@echo off
rem Startet die Copilot-Oberflaeche (Browser) und die Sicherheitsueberwachung (eigenes Fenster).
rem Laeuft der Copilot auf dem VPS (COPILOT_VPS_URL in copilot.env), wird nur dessen Seite geoeffnet:
rem ein Journal und eine Ueberwachung -- sonst wuesste die VPS-Ueberwachung nichts von hier gekauften Trades.
rem (Nur ASCII in dieser Datei: cmd liest sie nicht als UTF-8.)
cd /d "%~dp0"
set "VPS_URL="
if exist copilot.env for /f "usebackq tokens=1,* delims==" %%A in ("copilot.env") do if /i "%%A"=="COPILOT_VPS_URL" set "VPS_URL=%%B"
if defined VPS_URL (
  echo Copilot laeuft auf dem VPS: %VPS_URL%
  start "" "%VPS_URL%"
  exit /b
)
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
  echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"
)
rem cmd /k: das Fenster bleibt bei einem Fehler (z.B. copilot.env fehlt) offen und zeigt ihn an
start "Copilot-Sicherheit (OFFEN LASSEN)" cmd /k .venv\Scripts\python.exe main.py copilot watch
.venv\Scripts\python.exe -m streamlit run gui\copilot_app.py --browser.gatherUsageStats false
