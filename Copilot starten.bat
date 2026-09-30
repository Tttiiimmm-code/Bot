@echo off
rem Startet die Copilot-Oberfläche (Browser) und die Sicherheitsüberwachung (eigenes Fenster).
cd /d "%~dp0"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  mkdir "%USERPROFILE%\.streamlit" 2>nul
  echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
  echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"
)
rem cmd /k: das Fenster bleibt bei einem Fehler (z.B. copilot.env fehlt) offen und zeigt ihn an
start "Copilot-Sicherheit (OFFEN LASSEN)" cmd /k .venv\Scripts\python.exe main.py copilot watch
.venv\Scripts\python.exe -m streamlit run gui\copilot_app.py --browser.gatherUsageStats false
