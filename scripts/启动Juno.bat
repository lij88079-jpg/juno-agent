@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title Juno · 独立启动

:: 若已在跑则只开窗口
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8765/api/chat/status' -TimeoutSec 2 -UseBasicParsing | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  start /min "" python "%~dp0juno_training_server.py"
  timeout /t 2 /nobreak >nul
)

:: 确保 Ollama 在跑
powershell -NoProfile -Command "try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  where ollama >nul 2>&1 && start "" ollama serve && timeout /t 3 /nobreak >nul
)

:: 打开独立对话窗口
set URL=http://127.0.0.1:8765/chat
where msedge >nul 2>&1 && ( start "" msedge --app=%URL% --window-size=980,720 & exit /b 0 )
where chrome >nul 2>&1 && ( start "" chrome --app=%URL% --window-size=980,720 & exit /b 0 )
start "" %URL%
