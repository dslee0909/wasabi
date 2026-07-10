@echo off
cd /d "%~dp0"
title Discord Bot (Wasabi)
echo ============================================
echo   Starting Discord bot...
echo   Close this window to stop the bot.
echo ============================================
echo.
:loop
".venv\Scripts\python.exe" -u bot.py
echo.
echo [!] Bot stopped. Restarting in 5 seconds...
echo     (Close this window to quit completely)
timeout /t 5 >nul
goto loop
