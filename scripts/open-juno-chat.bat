@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title Juno Chat
python "%~dp0restart-juno.py"
set URL=http://127.0.0.1:8765/chat
start "" %URL%
