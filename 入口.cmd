@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   ModelKing Workbench
echo   首次双击：自动安装依赖并启动
echo   之后每次双击：直接启动（已就绪项会跳过）
echo ============================================================
echo.

REM ============================================================
REM 1. 探测 Python —— 优先 py 启动器（绕开 WindowsApps 占位符）
REM ============================================================
set "PY="
where py >nul 2>nul
if not errorlevel 1 (
  py -3 --version >nul 2>nul
  if not errorlevel 1 set "PY=py -3"
)
if not defined PY (
  REM 退路：遍历 where python，排除 WindowsApps 占位符
  for /f "delims=" %%i in ('where python 2^>nul') do (
    set "CAND=%%i"
    set "SKIP="
    if /i not "!CAND:WindowsApps=!"=="!CAND!" set "SKIP=1"
    if not defined SKIP if not defined PY (
      "!CAND!" --version >nul 2>nul
      if not errorlevel 1 set "PY="!CAND!""
    )
  )
)
if not defined PY (
  echo [X] 未找到可用的 Python 3。
  echo     请到 https://www.python.org/downloads/ 安装 Python 3.11+，
  echo     安装时务必勾选 "Add python.exe to PATH" 和 "py launcher"。
  echo.
  pause
  exit /b 1
)
echo [OK] Python:
%PY% --version

REM ============================================================
REM 2. 探测 Node.js / npm
REM ============================================================
where npm >nul 2>nul
if errorlevel 1 (
  echo [X] 未找到 npm。请到 https://nodejs.org/ 安装 LTS 版。
  echo.
  pause
  exit /b 1
)
echo [OK] Node:
call node --version

REM ============================================================
REM 3. .env —— 没有就从 .env.example 复制并打开记事本
REM ============================================================
if not exist ".env" (
  if not exist ".env.example" (
    echo [X] 缺少 .env 和 .env.example，无法继续。
    pause
    exit /b 1
  )
  copy ".env.example" ".env" >nul
  echo [!] 已从 .env.example 创建 .env。
  echo     请在记事本里填入你自己的 TUSHARE_TOKEN / GLM_API_KEY，保存后关闭记事本，
  echo     然后重新双击本脚本。
  echo.
  notepad ".env"
  pause
  exit /b 0
)
echo [OK] .env 已存在

REM ============================================================
REM 4. Python 依赖（缺才装，用清华镜像）
REM ============================================================
echo.
echo [*] 检查 Python 依赖...
%PY% -c "import tushare, pandas, fastapi, uvicorn, fitz, yaml, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo     缺失，安装中（清华镜像，首次较慢）...
  %PY% -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  if errorlevel 1 (
    echo [X] pip install 失败。
    pause
    exit /b 1
  )
  echo [OK] Python 依赖装好了
) else (
  echo [OK] Python 依赖已就绪
)

REM ============================================================
REM 5. 前端依赖（node_modules 缺才装）
REM ============================================================
if not exist "node_modules" (
  echo.
  echo [*] 安装前端依赖（首次较慢）...
  call npm install
  if errorlevel 1 (
    echo [X] npm install 失败。
    pause
    exit /b 1
  )
) else (
  echo [OK] node_modules 已就绪
)

REM ============================================================
REM 6. 构建前端（app/dist 缺才 build）
REM ============================================================
if not exist "app\dist\index.html" (
  echo.
  echo [*] 构建前端...
  call npm run build
  if errorlevel 1 (
    echo [X] npm run build 失败。
    pause
    exit /b 1
  )
) else (
  echo [OK] app\dist 已就绪
)

REM ============================================================
REM 7. 杀掉 8765 端口僵尸进程（避免上次没退干净导致启动失败）
REM ============================================================
echo.
set "KILLED="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765 " ^| findstr "LISTENING"') do (
  echo [*] 杀掉占用 8765 的进程 PID=%%a
  taskkill /F /PID %%a >nul 2>nul
  set "KILLED=1"
)
if not defined KILLED echo [OK] 8765 端口空闲

REM ============================================================
REM 8. 启动 Workbench
REM ============================================================
echo.
echo ============================================================
echo   启动 ModelKing Workbench
echo   浏览器应自动打开: http://127.0.0.1:8765
echo   （关闭本窗口即停止服务）
echo ============================================================
%PY% -m src.workbench
if errorlevel 1 (
  echo.
  echo [X] 启动失败，请看上方报错。
  pause
)
endlocal
