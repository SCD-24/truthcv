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
for /f "delims=" %%p in ('docker run --rm -v "%CD%:/work" -w /work python:3-alpine python -m launcher --repo /work') do set "PORTLINE=%%p"
for /f "tokens=2 delims==" %%v in ("!PORTLINE!") do set "APP_PORT=%%v"

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
for /f "delims=" %%p in ('docker run --rm -v "%CD%:/work" -w /work python:3-alpine python -m launcher --repo /work --bump APP_PORT') do set "PORTLINE=%%p"
for /f "tokens=2 delims==" %%v in ("!PORTLINE!") do set "APP_PORT=%%v"
set /a ATTEMPT+=1
goto up

:ready
del /q compose.err 2>nul
echo TruthCV is starting at http://localhost:!APP_PORT!
timeout /t 20 /nobreak >nul
start "" "http://localhost:!APP_PORT!"
