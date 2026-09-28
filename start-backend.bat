@echo off
chcp 65001 >nul
echo ===== 启动后端 (项目内 venv: backend\.venv, 全部依赖在 D 盘) =====
cd /d %~dp0backend
if not exist ".venv\Scripts\python.exe" (
  echo [错误] 未找到 backend\.venv, 请先在 backend 目录执行:
  echo   D:\software\miniconda\python.exe -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
