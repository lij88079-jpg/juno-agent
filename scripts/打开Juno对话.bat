@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title Juno Chat

:: 若已在跑则只开窗口
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/chat/status' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  start /min "" python "%~dp0juno_training_server.py"
  timeout /t 2 /nobreak >nul
)

:: 独立窗口模式（Edge 优先，其次 Chrome）
set URL=http://127.0.0.1:8765/chat
where msedge >nul 2>&1 && (
  start "" msedge --app=%URL% --window-size=980,720
  exit /b 0
)
where chrome >nul 2>&1 && (
  start "" chrome --app=%URL% --window-size=980,720
  exit /b 0
)
start "" %URL%
