@echo off
REM Windows double-click entry. Mirrors truthcv.sh; Windows ships no shell
REM the other two can share, so this is the one place logic is duplicated.
REM Keep it in step with truthcv.sh when either changes.
setlocal enabledelayedexpansion
cd /d "%~dp0..\.."

where docker >nul 2>&1
if errorlevel 1 (
  echo TruthCV needs Docker Desktop, which isn't installed.
  echo Download it from https://docs.docker.com/get-docker/ then run this again.
  pause & exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo Docker Desktop isn't running. Start it, wait for the whale icon to
  echo settle, then run this again.
  pause & exit /b 1
)

REM No --user here: Docker Desktop for Windows maps ownership itself, and
REM there is no id command to read a uid from.
call :read_port
if errorlevel 1 exit /b 1

docker compose images -q app 2>nul | findstr /r "." >nul
if errorlevel 1 (
  echo Setting up TruthCV for the first time.
  echo This takes about 10 minutes and only happens once.
)

set /a ATTEMPT=1
:up
docker compose up -d --build 2>compose.err
if not errorlevel 1 goto ready
findstr /i /c:"port is already allocated" /c:"address already in use" /c:"bind for" compose.err >nul
if errorlevel 1 (
  type compose.err
  echo TruthCV couldn't start. The log above says why.
  pause & exit /b 1
)
if !ATTEMPT! GEQ 10 (
  echo Tried 10 ports and every one was busy. Restart the machine and try again.
  pause & exit /b 1
)
call :read_port --bump APP_PORT
if errorlevel 1 exit /b 1
set /a ATTEMPT+=1
goto up

:ready
del /q compose.err 2>nul
echo TruthCV is starting at http://localhost:!APP_PORT!

REM Poll for readiness like truthcv.sh does, instead of a flat wait: after a
REM ~10 minute first build the app may well not be serving yet at a fixed
REM delay. Relies on curl.exe, bundled with Windows 10 (1803+) and Windows
REM 11; on an older Windows without it this loop just waits out its full
REM budget and opens anyway, same as if the app were still starting.
for /l %%i in (1,1,60) do (
  curl -fsS -o nul "http://localhost:!APP_PORT!" >nul 2>&1 && goto open
  timeout /t 2 /nobreak >nul
)
:open
start "" "http://localhost:!APP_PORT!"
exit /b 0

REM Captures the bootstrap container's stdout into APP_PORT, checking at
REM every step that it actually got one. A `for /f` that finds no output
REM otherwise leaves the previous value in place: on retry that silently
REM reuses the stale, still-conflicting port and burns every attempt on it;
REM on the first call it lets the script sail on to `docker compose up`
REM with no port set at all.
:read_port
set "PORTLINE="
set "APP_PORT="
for /f "delims=" %%p in ('docker run --rm -v "%CD%:/work" -w /work python:3-alpine python -m launcher --repo /work %*') do set "PORTLINE=%%p"
for /f "tokens=2 delims==" %%v in ("!PORTLINE!") do set "APP_PORT=%%v"
if not defined APP_PORT (
  echo TruthCV could not prepare its configuration. Make sure Docker Desktop is running, then try again.
  pause & exit /b 1
)
echo !APP_PORT!|findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo TruthCV could not work out which port to use. Please report this.
  pause & exit /b 1
)
exit /b 0
