@echo off
chcp 65001 >nul
cd /d "%~dp0.."
title Juno 环境安装

echo.
echo  ╔══════════════════════════════════╗
echo  ║      Juno 环境一键安装           ║
echo  ╚══════════════════════════════════╝
echo.

:: Python
python --version >nul 2>&1
if errorlevel 1 (
  echo [错误] 未找到 Python，请先安装 Python 3.10+
  pause
  exit /b 1
)
echo [OK] Python 已安装

:: Ollama
where ollama >nul 2>&1
if errorlevel 1 (
  echo [安装] 正在通过 winget 安装 Ollama…
  winget install Ollama.Ollama --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo [提示] winget 安装失败，请手动打开 https://ollama.com/download
    start https://ollama.com/download
    pause
    exit /b 1
  )
  echo [提示] Ollama 安装完成，请关闭本窗口后重新打开再运行一次
  pause
  exit /b 0
)
echo [OK] Ollama 已安装

:: 启动 Ollama
powershell -NoProfile -Command "try { Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3 | Out-Null; exit 0 } catch { exit 1 }"
if errorlevel 1 (
  echo [启动] Ollama 服务…
  start "" ollama serve
  timeout /t 4 /nobreak >nul
)

:: 下载推荐中文模型（可选，约 4GB）
echo.
echo [模型] 推荐下载 qwen2.5:7b（中文更好，约 4GB）
set /p PULL=是否现在下载？[Y/n]: 
if /i "%PULL%"=="" set PULL=Y
if /i "%PULL%"=="Y" (
  ollama pull qwen2.5:7b
  if not errorlevel 1 (
    echo {"provider":"ollama","api_base":"http://127.0.0.1:11434","model":"qwen2.5:7b"}> "%~dp0..\config\chat.local.json"
    echo [OK] 已切换默认模型为 qwen2.5:7b
  )
)

:: 桌面快捷方式
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Juno.lnk'); $s.TargetPath='%~dp0启动Juno.bat'; $s.WorkingDirectory='%~dp0..'; $s.Description='Juno 独立对话'; $s.Save()"
echo [OK] 桌面快捷方式「Juno」已创建

echo.
echo  ════════════════════════════════════
echo   安装完成！双击桌面「Juno」即可聊天
echo  ════════════════════════════════════
echo.
pause
