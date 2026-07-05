@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Starting Juno Training Studio...
start http://127.0.0.1:8765
python "%~dp0juno_training_server.py"
pause
