@echo off
rem Double-click this file to install or update Solar Eclipse Workbench on Windows.
rem It runs install-sew.ps1 from the same folder, and downloads it from GitHub
rem first when it is not there.  Options are passed on, for example:
rem     install-sew.cmd -Update
setlocal
set "SCRIPT=%~dp0install-sew.ps1"
if exist "%SCRIPT%" goto run

set "SCRIPT=%TEMP%\install-sew.ps1"
echo Downloading the Solar Eclipse Workbench installer...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference = 'SilentlyContinue'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/AstroWimSara/SolarEclipseWorkbench/main/scripts/windows/install-sew.ps1' -OutFile $env:SCRIPT"
if errorlevel 1 goto download_failed

:run
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
exit /b %ERRORLEVEL%

:download_failed
echo.
echo Could not download the installer.  Check the internet connection, or download
echo install-sew.ps1 from https://github.com/AstroWimSara/SolarEclipseWorkbench into
echo the folder of this file and run this file again.
pause
exit /b 1
